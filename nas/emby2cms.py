#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
emby2cms.py —— 把 Emby / Jellyfin 媒体库包装成 TVBox 认识的「苹果CMS v10」接口

为什么要它：
  TVBox 的 type=4 站点只认苹果CMS v10 那套 JSON（ac=list / ac=detail），
  Emby/Jellyfin 不会说这套方言，所以中间要有个翻译。

特性：
  · 单文件、纯标准库，无任何第三方依赖
  · 每个 Emby 媒体库自动变成一个分类（电影 / 剧集 / 动漫 / 综艺 …）
  · 剧集自动展开成「第1集、第2集…」多集播放列表
  · 直连播放（static 直传，不经转码），NAS 不吃 CPU
  · 结果缓存，默认 300 秒刷新一次

用法：
  # 1) 先看参数
  python3 nas/emby2cms.py --help

  # 2) 直接跑
  EMBY_BASE=http://192.168.1.10:8096 \
  EMBY_API_KEY=你的apikey \
  python3 nas/emby2cms.py --port 8000

  # 3) 自检（不连真服务器，验证输出格式）
  python3 nas/emby2cms.py --mock --port 8000
  curl "http://127.0.0.1:8000/api.php/provide/vod/?ac=list"
"""

import argparse
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
BASE = os.environ.get("EMBY_BASE", "http://127.0.0.1:8096").rstrip("/")
API_KEY = os.environ.get("EMBY_API_KEY", "")
USER_ID = os.environ.get("EMBY_USER_ID", "")
CACHE_TTL = int(os.environ.get("CACHE_TTL", "300"))
PAGE_SIZE = int(os.environ.get("PAGE_SIZE", "20"))
LIB_LIMIT = int(os.environ.get("LIBRARY_LIMIT", "5000"))
PLAY_FROM = os.environ.get("PLAY_FROM", "emby")
UA = "okhttp/3.12.0"

LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# 与 Emby 通信
# ---------------------------------------------------------------------------
def api_get(path, params=None, timeout=15):
    url = BASE + path
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "X-Emby-Token": API_KEY})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "ignore"))


def img_url(item_id, tag=None):
    if not tag:
        return ""
    q = urllib.parse.urlencode({"maxHeight": 400, "tag": tag, "api_key": API_KEY})
    return f"{BASE}/Items/{item_id}/Images/Primary?{q}"


def stream_url(item_id):
    """直连播放地址：static=true 表示原样输出，不转码"""
    q = urllib.parse.urlencode(
        {"static": "true", "MediaSourceId": item_id, "api_key": API_KEY, "DeviceId": "tvbox-cms"}
    )
    return f"{BASE}/videos/{item_id}/stream?{q}"


# ---------------------------------------------------------------------------
# 索引缓存
# ---------------------------------------------------------------------------
class Index:
    """把媒体库拉进内存，做 int id ↔ emby id 的双向映射"""

    def __init__(self):
        self.libraries = []        # [{type_id, type_name, emby_id}]
        self.items = {}            # int_id -> normalized item
        self.by_type = {}          # type_id -> [int_id]
        self._ts = 0
        self._next = 1

    # -- 刷新 --------------------------------------------------------------
    def ensure(self):
        with LOCK:
            if time.time() - self._ts < CACHE_TTL and self.items:
                return
            self._rebuild()

    def _rebuild(self):
        self.libraries, self.items, self.by_type, self._next = [], {}, {}, 1
        try:
            folders = api_get("/Library/MediaFolders").get("Items", [])
        except Exception as e:  # noqa: BLE001
            print(f"[warn] 拉取媒体库失败: {e}", file=sys.stderr)
            folders = []

        for i, f in enumerate(folders, start=1):
            if f.get("CollectionType") not in ("movies", "tvshows", "musicvideos", "homevideos", None):
                continue
            tid = i
            self.libraries.append({"type_id": tid, "type_name": f.get("Name", f"分类{tid}"),
                                   "emby_id": f["Id"]})
            self.by_type[tid] = []
            for it in self._fetch_items(f["Id"]):
                iid = self._next
                self._next += 1
                self.items[iid] = self._normalize(it, tid)
                self.by_type[tid].append(iid)
        self._ts = time.time()

    def _fetch_items(self, lib_id):
        out, start = [], 0
        while start < LIB_LIMIT:
            params = {
                "ParentId": lib_id,
                "Recursive": "true",
                "IncludeItemTypes": "Movie,Series",
                "Fields": "Overview,ProductionYear,CommunityRating,OfficialRating,ImageTags,Path,RunTimeTicks",
                "SortBy": "DateCreated,SortName",
                "SortOrder": "Descending",
                "Limit": 200,
                "StartIndex": start,
            }
            if USER_ID:
                params["UserId"] = USER_ID
            try:
                data = api_get("/Items", params)
            except Exception as e:  # noqa: BLE001
                print(f"[warn] 拉取库 {lib_id} 失败: {e}", file=sys.stderr)
                break
            batch = data.get("Items", [])
            out.extend(batch)
            if len(batch) < 200:
                break
            start += 200
        return out

    @staticmethod
    def _normalize(it, tid):
        tags = it.get("ImageTags") or {}
        return {
            "id": it["Id"],
            "name": it.get("Name", ""),
            "type_id": tid,
            "is_series": it.get("Type") == "Series",
            "pic": img_url(it["Id"], tags.get("Primary")),
            "year": str(it.get("ProductionYear") or ""),
            "score": it.get("CommunityRating"),
            "rating": it.get("OfficialRating") or "",
            "overview": (it.get("Overview") or "").strip(),
            "series_name": it.get("SeriesName") or "",
            "index_no": it.get("IndexNumber") or 0,
            "parent_index": it.get("ParentIndexNumber") or 0,
        }

    # -- 查询 --------------------------------------------------------------
    def page(self, tid, pg):
        ids = self.by_type.get(tid, []) if tid else [
            i for lst in self.by_type.values() for i in lst
        ]
        total = len(ids)
        start = (pg - 1) * PAGE_SIZE
        return ids[start:start + PAGE_SIZE], total

    def search(self, kw, pg):
        kw = kw.lower()
        ids = [i for i, it in self.items.items() if kw in it["name"].lower()]
        total = len(ids)
        start = (pg - 1) * PAGE_SIZE
        return ids[start:start + PAGE_SIZE], total

    def episodes(self, int_id):
        """剧集展开成多集；电影返回单条「正片」"""
        it = self.items.get(int_id)
        if not it:
            return []
        if not it["is_series"]:
            return [("正片", stream_url(it["id"]))]

        params = {"Fields": "Overview,ImageTags", "Limit": 500, "SortBy": "ParentIndexNumber,IndexNumber"}
        if USER_ID:
            params["UserId"] = USER_ID
        try:
            eps = api_get(f"/Shows/{it['id']}/Episodes", params).get("Items", [])
        except Exception as e:  # noqa: BLE001
            print(f"[warn] 拉取剧集失败 {it['name']}: {e}", file=sys.stderr)
            return [("正片", stream_url(it["id"]))]

        out = []
        for e in eps:
            se, ep = e.get("ParentIndexNumber"), e.get("IndexNumber")
            label = f"S{se:02d}E{ep:02d}" if se and ep else (e.get("Name") or "剧集")
            if e.get("Name") and e.get("Name") != it["name"]:
                label = f"{label} {e['Name']}"
            out.append((label.strip(), stream_url(e["Id"])))
        return out or [("正片", stream_url(it["id"]))]


IDX = Index()


# ---------------------------------------------------------------------------
# Mock：不连服务器也能验证输出格式
# ---------------------------------------------------------------------------
def install_mock():
    idx = IDX
    idx.libraries = [
        {"type_id": 1, "type_name": "电影", "emby_id": "lib1"},
        {"type_id": 2, "type_name": "剧集", "emby_id": "lib2"},
    ]
    for n, (name, year) in enumerate(
        [("沙丘2", 2024), ("奥本海默", 2023), ("流浪地球2", 2023)], start=1
    ):
        idx.items[n] = {
            "id": f"movie{n}", "name": name, "type_id": 1, "is_series": False,
            "pic": "", "year": str(year), "score": 8.1, "rating": "PG-13",
            "overview": f"{name} 的简介。", "series_name": "", "index_no": 0, "parent_index": 0,
        }
        idx.by_type.setdefault(1, []).append(n)
    for n, name in enumerate(["三体", "漫长的季节"], start=4):
        idx.items[n] = {
            "id": f"series{n}", "name": name, "type_id": 2, "is_series": True,
            "pic": "", "year": "2023", "score": 9.0, "rating": "",
            "overview": f"{name} 的简介。", "series_name": "", "index_no": 0, "parent_index": 0,
        }
        idx.by_type.setdefault(2, []).append(n)
    idx._next = 6
    idx._ts = time.time() + 10 ** 9  # 永不过期

    def _mock_eps(int_id):
        it = IDX.items[int_id]
        if not it["is_series"]:
            return [("正片", stream_url(it["id"]))]
        return [(f"第{i:02d}集", stream_url(f"{it['id']}_e{i}")) for i in range(1, 9)]

    Index.episodes = lambda self, i: _mock_eps(i)
    Index.ensure = lambda self: None


# ---------------------------------------------------------------------------
# CMS v10 输出
# ---------------------------------------------------------------------------
def as_brief(int_id):
    it = IDX.items[int_id]
    remark = it["rating"] or (f"{it['score']}分" if it.get("score") else "")
    return {
        "vod_id": int_id,
        "vod_name": it["name"],
        "vod_pic": it["pic"],
        "vod_remarks": remark,
        "vod_year": it["year"],
        "type_id": it["type_id"],
    }


def as_detail(int_id):
    it = IDX.items[int_id]
    eps = IDX.episodes(int_id)
    play_url = "#".join(f"{n}${u}" for n, u in eps)
    type_name = next(
        (l["type_name"] for l in IDX.libraries if l["type_id"] == it["type_id"]), "其他"
    )
    return {
        "vod_id": int_id,
        "vod_name": it["name"],
        "vod_sub": it.get("series_name") or "",
        "type_id": it["type_id"],
        "type_name": type_name,
        "vod_pic": it["pic"],
        "vod_year": it["year"],
        "vod_area": "",
        "vod_lang": "",
        "vod_remarks": it["rating"] or "",
        "vod_actor": "",
        "vod_director": "",
        "vod_content": re.sub(r"<[^>]+>", "", it["overview"]),
        "vod_play_from": PLAY_FROM,
        "vod_play_url": play_url,
        "vod_play_server": "",
        "vod_play_note": "",
        "vod_score": str(it.get("score") or ""),
    }


def resp(data, total=0, page=1):
    pc = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE) if total else 1
    body = {"code": 1, "msg": "数据列表", "page": page, "pagecount": pc,
            "limit": str(PAGE_SIZE), "total": total}
    body.update(data)
    return body


def handle_vod(qs):
    ac = (qs.get("ac") or ["list"])[0]
    pg = int((qs.get("pg") or ["1"])[0] or 1)
    tid = (qs.get("t") or [""])[0]
    wd = (qs.get("wd") or [""])[0].strip()

    IDX.ensure()

    if ac == "detail":
        ids = (qs.get("ids") or [""])[0]
        out = []
        for s in ids.split(","):
            if s.strip().isdigit() and int(s) in IDX.items:
                out.append(as_detail(int(s)))
        return resp({"list": out}, len(out), 1)

    # ac=list
    if wd:
        ids, total = IDX.search(wd, pg)
    elif tid.isdigit():
        ids, total = IDX.page(int(tid), pg)
    else:
        # 不带 t：返回分类骨架
        classes = [{"type_id": l["type_id"], "type_name": l["type_name"]} for l in IDX.libraries]
        return resp({"class": classes}, len(classes), 1)

    return resp({"list": [as_brief(i) for i in ids]}, total, pg)


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    server_version = "emby2cms/1.0"

    def log_message(self, fmt, *args):  # 安静一点
        if os.environ.get("VERBOSE"):
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _send(self, code, payload, ctype="application/json; charset=utf-8"):
        raw = payload.encode("utf-8") if isinstance(payload, str) else payload
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        path, qs = parsed.path, urllib.parse.parse_qs(parsed.query)

        try:
            if path in ("/", "/health"):
                return self._send(200, json.dumps({
                    "ok": True,
                    "service": "emby2cms",
                    "server": BASE,
                    "libraries": [{"type_id": l["type_id"], "name": l["type_name"]}
                                  for l in IDX.libraries] or "（首次请求时加载）",
                    "endpoint": "/api.php/provide/vod/",
                }, ensure_ascii=False, indent=2))

            if path.rstrip("/").endswith("/api.php/provide/vod") or path.endswith("/vod"):
                return self._send(200, json.dumps(handle_vod(qs), ensure_ascii=False))

            return self._send(404, json.dumps({"code": 0, "msg": "not found"}, ensure_ascii=False))
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            return self._send(500, json.dumps(
                {"code": 0, "msg": f"server error: {e}"}, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser(description="Emby/Jellyfin → 苹果CMS v10 接口代理")
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--mock", action="store_true", help="用假数据自检，不连接 Emby")
    args = ap.parse_args()

    if args.mock:
        install_mock()
        print("· Mock 模式：使用假数据")
    else:
        if not API_KEY:
            sys.exit("缺少 EMBY_API_KEY，请先到 Emby 后台「设置 → 高级 → API 密钥」创建")
        print(f"· Emby 服务器：{BASE}")

    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"· 监听 http://{args.host}:{args.port}")
    print(f"· TVBox 站点地址填：http://<本机IP>:{args.port}/api.php/provide/vod/")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n· 已停止")


if __name__ == "__main__":
    main()
