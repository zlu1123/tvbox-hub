#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build.py —— 把 sources.yaml 编译成 TVBox 能直接吃的配置

流程：
  1. 抓取 sources.yaml 里所有上游 M3U/TXT 清单
  2. 按 include / exclude 正则筛频道
  3. 并发探活，死链剔除（可选 --no-probe 跳过）
  4. 生成 config/index.json（主配置，TVBox 里填这个地址）与 config/live.json
  5. 生成 config/health.json 记录每个频道的检测结果

用法：
  python3 scripts/build.py                 # 完整构建（含探活）
  python3 scripts/build.py --no-probe      # 只筛选不探活，秒出
"""

import argparse
import json
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from urllib.parse import urlencode

try:
    import yaml
except ImportError:
    sys.exit("缺少依赖：pip install pyyaml")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG_PATH = os.path.join(ROOT, "config", "sources.yaml")
OUT_DIR = os.path.join(ROOT, "config")

UA = "okhttp/3.12.0"
ANSI = {"g": "\033[32m", "y": "\033[33m", "r": "\033[31m", "d": "\033[2m", "0": "\033[0m"}

# 强制直连：探活要模拟的是「电视所在的网络」，如果走系统代理（比如本机
# 挂着 HTTP_PROXY），测出来的可用性就不是电视的真实情况。
# 实测教训：走代理时 44 条全通，直连只剩 6 条能播。
DIRECT_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
urllib.request.install_opener(DIRECT_OPENER)


def color(s, c):
    return f"{ANSI[c]}{s}{ANSI['0']}" if sys.stdout.isatty() else str(s)


# --------------------------------------------------------------------------
# 抓取 & 解析
# --------------------------------------------------------------------------
def http_get(url, timeout=20, retries=2):
    last = None
    for i in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
            for enc in ("utf-8", "gbk", "gb18030"):
                try:
                    return raw.decode(enc)
                except UnicodeDecodeError:
                    continue
            return raw.decode("utf-8", "ignore")
        except Exception as e:  # noqa: BLE001
            last = e
            if i < retries:
                time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"抓取失败 {url}: {last}")


EXTINF_RE = re.compile(r'#EXTINF:\s*(-?\d+(?:\.\d+)?)\s*(.*?),(.*)$', re.S)  # 保留兼容，解析已改用 _split_outside_quotes


def _attrs(s):
    return dict(re.findall(r'([\w-]+)="([^"]*)"', s))


def _split_outside_quotes(s):
    """按逗号切分，但忽略引号里的逗号。
    EXTINF 的属性值里经常有逗号（比如解析器把 UA 字符串塞进 tvg-name），
    天真地 split(',') 会把台名截断成半截。"""
    parts, buf, q = [], [], None
    for ch in s:
        if q:
            buf.append(ch)
            if ch == q:
                q = None
        elif ch in ('"', "'"):
            q = ch
            buf.append(ch)
        elif ch == ",":
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    return parts


def parse_playlist(text, base=""):
    """同时兼容 M3U 和 纯文本(TXT) 两种格式"""
    items = []
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if any(l.upper().startswith("#EXTM3U") for l in lines[:3]) or any(
        l.upper().startswith("#EXTINF") for l in lines
    ):
        cur = None
        for line in lines:
            if line.upper().startswith("#EXTINF"):
                body = line[len("#EXTINF:"):].strip()
                parts = _split_outside_quotes(body)
                attrs_part = parts[0] if parts else ""
                title = ",".join(parts[1:]).strip() if len(parts) > 1 else ""
                a = _attrs(attrs_part)
                cur = {
                    "name": title,
                    "group": a.get("group-title", ""),
                    "logo": a.get("tvg-logo", ""),
                    "raw_attr": attrs_part,
                }
            elif line.startswith("#"):
                continue
            elif cur is not None:
                url = line
                if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", url) and base:
                    url = base.rstrip("/") + "/" + url.lstrip("/")
                cur["url"] = url
                items.append(cur)
                cur = None
        return items

    # TXT 格式： 频道名,url  或  频道名,#genre# 分组
    group = "未分组"
    for line in lines:
        if line.startswith("#"):
            continue
        if ",#genre#" in line:
            group = line.split(",", 1)[0].strip()
            continue
        if "," not in line:
            continue
        name, url = line.split(",", 1)
        name, url = name.strip(), url.strip()
        if not url.lower().startswith(("http", "rtmp", "rtsp", "p3p", "mitv")):
            continue
        items.append({"name": name, "group": group, "logo": "", "url": url})
    return items


NOISE = re.compile(
    r"\s*[\(\[]\s*(?:\d{3,4}[pi]|HD|SD|FHD|UHD|Not 24/7|Geo-blocked|"
    r"[^\)\]]*?)\s*[\)\]]\s*$",
    re.I,
)
MULTI_SPACE = re.compile(r"\s+")


QUALITY_TAIL = re.compile(
    r"\s+(?:\d+\s*FPS|HD|SD|FHD|UHD|4K|8K|H\.?265|HEVC|AVC|Multi|Audio)$", re.I
)


def clean_name(name):
    n = name.strip()
    for _ in range(3):  # 可能连着好几层括号
        new = NOISE.sub("", n).strip()
        if new == n:
            break
        n = new
    for _ in range(2):  # 去掉结尾的 HD / SD 之类的画质标记，让同台多清晰度合并
        new = QUALITY_TAIL.sub("", n).strip()
        if new == n:
            break
        n = new
    n = MULTI_SPACE.sub(" ", n)
    # 统一 CCTV 写法：CCTV 1 / CCTV1 -> CCTV-1
    n = re.sub(r"\bCCTV[\s\-]?(\d+)\s*\+", r"CCTV-\1+", n, flags=re.I)
    n = re.sub(r"\bCCTV[\s\-]?(\d+)\b", lambda m: f"CCTV-{m.group(1)}", n, flags=re.I)
    n = re.sub(r"\bCCTV\s*-\s*", "CCTV-", n, flags=re.I)
    return n.strip(" -")


def channel_group(name):
    if re.search(r"CCTV", name, re.I):
        return "央视"
    if "卫视" in name:
        return "卫视"
    return "其他"


def cctv_sort_key(name):
    m = re.match(r"CCTV-(\d+)(\+)?", name)
    if m:
        return (0, int(m.group(1)), 1 if m.group(2) else 0, name)
    return (1, 0, 0, name)


# --------------------------------------------------------------------------
# 探活
# --------------------------------------------------------------------------
# 广告农场特征：这批 IP 把「央视频道」全指到同一个 applive/mkt.m3u8
# （mkt = marketing），打开就是广告页或者根本播不出台。
AD_TOKENS = re.compile(r"/applive/|mkt\.m3u8|/ad[sx]?/|advert|promo", re.I)


def _fingerprint(seg, final_url):
    """给一路流算指纹：保留目录名，只把分片文件名里的序号抹掉。
    同一条 ts 流被挂上十个台名时（免费源常见的「假台」套路），
    指纹会完全一样，据此可以把整批假台剔掉。
    注意只能抹文件名里的数字 —— 目录名带台号（cctv2md / cctv6md），
    一起抹掉会让所有央视线路撞成同一个指纹，反而全被误杀。
    故意不把主机算进去：这种农场往往在多个 IP 上铺同一路流。"""
    from urllib.parse import urljoin, urlparse
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", seg):
        seg = urljoin(final_url, seg)
    path = urlparse(seg).path.strip("/")
    d, _, f = path.rpartition("/")
    f = re.sub(r"\d+", "", f)
    return f"{d}/{f}" if d else f


def _probe_once(url, timeout=8):
    """单次深度探活：验清单 + 拉真实视频分片 + 算流指纹"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            final_url = r.geturl()
            head = r.read(16384).decode("utf-8", "ignore")

        if AD_TOKENS.search(final_url):
            return {"ok": False, "err": "广告跳转", "fp": "", "url": final_url}

        lower = final_url.split("?")[0].lower()
        if not lower.endswith((".m3u8", ".m3u")):
            return {"ok": True, "err": "", "fp": "", "url": final_url}

        if "#EXTM3U" not in head.upper():
            return {"ok": False, "err": "非有效 m3u8", "fp": "", "url": final_url}

        # 取清单里第一条真实地址（可能是分片，也可能是子清单）
        seg = next((l.strip() for l in head.splitlines()
                    if l.strip() and not l.strip().startswith("#")), "")
        if not seg:
            return {"ok": False, "err": "清单里没有分片", "fp": "", "url": final_url}

        from urllib.parse import urljoin
        seg_url = seg if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", seg) \
            else urljoin(final_url, seg)

        req2 = urllib.request.Request(
            seg_url, headers={"User-Agent": UA, "Range": "bytes=0-131071"})
        with urllib.request.urlopen(req2, timeout=timeout) as r2:
            if len(r2.read()) == 0:
                return {"ok": False, "err": "分片为空", "fp": "", "url": final_url}
        return {"ok": True, "err": "", "fp": _fingerprint(seg, final_url),
                "url": final_url}
    except urllib.error.HTTPError as e:
        return {"ok": False, "err": f"HTTP {e.code}", "fp": "", "url": url}
    except (socket.timeout, TimeoutError):
        return {"ok": False, "err": "超时", "fp": "", "url": url}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "err": type(e).__name__, "fp": "", "url": url}


def probe_one(url, timeout=8, attempts=2):
    """共识探活：连测 attempts 次，失败后再给一次机会。
    这些免费流很不稳定，单次通过率抖动很大（实测同一服务器这分钟通下分钟断），
    但测太多次又会被对方当成攻击直接 reset，2 次是最划算的折中。"""
    attempts = max(1, int(attempts))
    need = 1
    ok_count, last = 0, None
    for _ in range(attempts):
        r = _probe_once(url, timeout)
        if r["ok"]:
            ok_count += 1
            if last is None or not last["ok"]:
                last = r
            if ok_count >= need:
                return r
        else:
            last = r
            time.sleep(0.4)
    return last or {"ok": False, "err": "未知", "fp": "", "url": url}


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------
def collect_live(cfg, do_probe=True, verbose=True):
    lc = cfg.get("live", {})
    if not lc.get("enabled", True):
        return [], []

    inc = [re.compile(p, re.I) for p in lc.get("include", [])]
    exc = [re.compile(p, re.I) for p in lc.get("exclude", [])]
    exc_groups = {str(g).strip().lower() for g in lc.get("exclude_groups", [])}
    name_map = {clean_name(k): v for k, v in (lc.get("name_map") or {}).items()}
    max_lines = int(lc.get("max_lines_per_channel", 3))

    buckets = {}   # 清洗名 -> {name, urls[], logo, group}
    raw_count = 0
    for up in lc.get("upstreams", []):
        try:
            text = http_get(up["url"])
        except RuntimeError as e:
            print(color(f"  ! 跳过上游 {up['name']}: {e}", "y"))
            continue
        items = parse_playlist(text, up.get("base", ""))
        raw_count += len(items)
        trust = bool(up.get("trust"))
        # 上游可以再加一层自己的排除/白名单，用来处理这个源特有的情况
        # （比如 iptv-org 的 CCTV 全指向同一个广告跳转站；fanmingming 里
        #   混了 NewTV/iHOT 这类点播品牌频道）
        up_exc = [re.compile(p, re.I) for p in up.get("exclude", [])]
        up_groups = {str(g).strip().lower() for g in up.get("groups", [])}
        # 上游自己的白名单：设了的话，只收命中它的台（myiptv 这种几千条的大源
        # 全靠这个精准挑选，否则会把电影轮播、外语台全塞进来）
        up_inc = [re.compile(p, re.I) for p in up.get("include", [])]
        # 只收 name_map 里给了中文名的台。iptv-org 那种英文清单里塞了几十个
        # 县市级小台，全收进来电视上就是一屏英文，不如只留精选过的。
        only_mapped = bool(up.get("only_mapped"))
        # 这个上游每个台最多取几条线路（Guovin 这种一条台给十几条备用线的，
        # 不设上限会白白增加探活时间）
        up_cap = int(up.get("max_lines", 0) or 0)

        local = {}   # 本轮上游内部先聚合，方便按上游单独截断
        for it in items:
            raw = it["name"]
            base = clean_name(raw)
            if not base:
                continue
            # 优先用映射表里的中文名，没有就用清洗后的原名
            name = name_map.get(base, base)
            if only_mapped and base not in name_map:
                continue
            if not trust:
                if it.get("group", "").strip().lower() in exc_groups:
                    continue
                if up_groups and it.get("group", "").strip().lower() not in up_groups:
                    continue
                # 上游自己的白名单优先，其次才是全局 include
                if up_inc and not any(p.search(name) or p.search(raw)
                                      for p in up_inc):
                    continue
                if inc and not any(p.search(name) or p.search(raw) for p in inc):
                    continue
                # 排除规则同时匹配台名和 URL —— 广告农场要按主机名拉黑，
                # 光看台名它们也叫 "CCTV-1"，根本区分不出来。
                if any(p.search(raw) or p.search(name) or p.search(it["url"])
                       for p in exc):
                    continue
                if up_exc and any(p.search(raw) or p.search(name) or p.search(it["url"])
                                  for p in up_exc):
                    continue
            d = local.setdefault(name, {"urls": [], "logo": it.get("logo", "")})
            if it["url"] not in d["urls"]:
                d["urls"].append(it["url"])
            if not d["logo"] and it.get("logo"):
                d["logo"] = it["logo"]

        # 合并进总池：上游顺序 = 线路优先级，先来的排在 urls 前面，
        # 所以 live.txt / live.m3u 里写出的永远是排最前的那个上游。
        for name, d in local.items():
            b = buckets.setdefault(
                name,
                {"name": name, "urls": [], "logo": d["logo"],
                 "group": channel_group(name)},
            )
            if not b.get("logo") and d["logo"]:
                b["logo"] = d["logo"]
            for u in (d["urls"][:up_cap] if up_cap else d["urls"]):
                if u not in b["urls"]:
                    b["urls"].append(u)
        if verbose:
            print(f"  · {up['name']}: 抓到 {len(items)} 条，命中 {len(local)} 个台")

    # ---- 探活 ----
    all_urls = {n: list(b["urls"]) for n, b in buckets.items()}
    line_result = {}   # (channel, url) -> (ok, err)
    total_lines = sum(len(v) for v in all_urls.values())

    if do_probe and total_lines:
        probe_cfg = lc.get("probe", {})
        timeout = probe_cfg.get("timeout", 8)
        workers = probe_cfg.get("workers", 24)
        retries = probe_cfg.get("retries", 2)
        jobs = [(n, u) for n, us in all_urls.items() for u in us]
        if verbose:
            print(color(f"  探活中… 共 {len(jobs)} 条线路，并发 {workers}", "d"))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = {pool.submit(probe_one, u, timeout, retries): (n, u) for n, u in jobs}
            for done, f in enumerate(as_completed(futs), 1):
                n, u = futs[f]
                line_result[(n, u)] = f.result()
                if verbose and (done % 20 == 0 or done == len(jobs)):
                    print(f"\r  探活进度 {done}/{len(jobs)}", end="", flush=True)
        if verbose:
            print()

        # ---- 假台检测 ----
        # 免费源里最常见的套路：一路 ts 流挂上十几个台名，点进去发现
        # CCTV-1、CCTV-3、北京卫视全是同一段画面。按流指纹归组，
        # 一个指纹如果被 2 个以上不同台名共用，就把这批线路全判成假台。
        fp_owner = {}
        for (n, u), r in line_result.items():
            if r.get("ok") and r.get("fp"):
                fp_owner.setdefault(r["fp"], set()).add(n)
        fake_fps = {fp for fp, owners in fp_owner.items() if len(owners) >= 2}
        if fake_fps and verbose:
            sample = sorted(next(iter(fp_owner[fp])) for fp in fake_fps)[:3]
            print(color(f"  剔除假台线路 {len(fake_fps)} 组"
                        f"（同一路流被多个台名共用，例如 {'、'.join(sample)}）", "y"))
        for (n, u), r in list(line_result.items()):
            if r.get("ok") and r.get("fp") in fake_fps:
                line_result[(n, u)] = dict(r, ok=False, err="假台(与其他台同源)")
    else:
        for n, us in all_urls.items():
            for u in us:
                line_result[(n, u)] = {"ok": True, "err": "", "fp": "", "url": u}

    def _ok(n, u):
        return line_result.get((n, u), {"ok": True})["ok"]

    # ---- 组装 ----
    groups = {"央视": [], "卫视": [], "其他": []}
    channels_health = []
    alive_lines = 0
    for name, b in buckets.items():
        us = all_urls[name]
        ok_urls = [u for u in us if _ok(name, u)]
        alive_lines += len(ok_urls)
        errs = sorted({line_result[(name, u)]["err"] for u in us
                       if (name, u) in line_result and not line_result[(name, u)]["ok"]})

        if not ok_urls:
            status = "dead"
        elif len(ok_urls) < len(us):
            status = "partial"
        else:
            status = "ok"

        keep = ok_urls[:max_lines]
        channels_health.append({
            "name": name,
            "group": b["group"],
            "status": status,
            "lines_total": len(us),
            "lines_alive": len(ok_urls),
            "errors": errs,
        })
        if keep:
            groups.setdefault(b["group"], []).append(
                {"name": name, "urls": keep, "logo": b.get("logo", "")}
            )

    for k in groups:
        groups[k].sort(key=lambda c: cctv_sort_key(c["name"]))

    lives = [{"group": g, "channels": chs} for g, chs in groups.items() if chs]

    health = {
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "probed": bool(do_probe),
        "summary": {
            "channels_total": len(channels_health),
            "channels_alive": sum(1 for c in channels_health if c["status"] != "dead"),
            "lines_total": total_lines,
            "lines_alive": alive_lines,
        },
        "channels": sorted(channels_health, key=lambda c: (c["group"], cctv_sort_key(c["name"]))),
    }

    if verbose:
        s = health["summary"]
        print(
            color(f"  直播：{s['channels_alive']}/{s['channels_total']} 个频道可用", "g")
            + color(f"（线路 {s['lines_alive']}/{s['lines_total']} 存活）",
                    "y" if s["lines_alive"] < s["lines_total"] else "d")
        )
    return lives, health


# --------------------------------------------------------------------------
# 影视源探活
#
# 免费采集站的寿命比直播流还短，光「接口能打开」完全不够：
# 有些站首页能返回 JSON，但详情没有播放地址，或者搜索永远空。
# 所以三项全过才写进电视配置：列片 → 详情有 m3u8 → 搜索有结果。
# --------------------------------------------------------------------------
def _cms_url(api, params):
    sep = "&" if "?" in api else "?"
    return api + sep + urlencode(params)


def _cms_json(url, timeout):
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Accept": "application/json,*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read(4_000_000)
    text = raw.decode("utf-8", "ignore").lstrip("\ufeff").strip()
    return json.loads(text)


def probe_vod_one(site, timeout=12, keyword="流浪地球", require_search=True):
    api = str(site.get("api", ""))
    r = {
        "key": site.get("key"), "name": site.get("name"), "api": api,
        "status": "dead", "error": "",
        "total": 0, "classes": 0, "search_hits": 0, "list_ms": 0,
        "play_host": "", "play_is_m3u8": False,
    }
    try:
        # 1) 列片（个别站只认老参数 ac=videolist，给一次回退）
        t0 = time.time()
        try:
            d = _cms_json(_cms_url(api, {"ac": "list", "pg": 1}), timeout)
        except Exception:  # noqa: BLE001
            d = _cms_json(_cms_url(api, {"ac": "videolist", "pg": 1}), timeout)
        r["list_ms"] = int((time.time() - t0) * 1000)
        lst = d.get("list") or []
        if not isinstance(lst, list) or not lst:
            r["error"] = f"列表为空（code={d.get('code')} msg={str(d.get('msg'))[:40]}）"
            return r
        r["total"] = int(d.get("total") or 0)
        r["classes"] = len(d.get("class") or [])

        # 2) 详情必须给得出 m3u8 直链，避免配一个只能看不能播的空壳
        vid = lst[0].get("vod_id")
        if not vid:
            r["error"] = "列表里没有 vod_id"
            return r
        dd = _cms_json(_cms_url(api, {"ac": "detail", "ids": vid}), timeout)
        dl = dd.get("list") or []
        pu = str((dl[0] if dl else {}).get("vod_play_url", ""))
        if not pu:
            r["error"] = "详情里没有播放地址"
            return r
        r["play_is_m3u8"] = ".m3u8" in pu.lower()
        hosts = re.findall(r"https?://([^/:$\s#]+)", pu)
        r["play_host"] = hosts[0] if hosts else ""
        if not r["play_is_m3u8"]:
            r["error"] = "播放地址不是 m3u8 直链"
            return r

        # 3) 搜索（用户要的就是能搜片，这步不能省）
        if require_search:
            s = _cms_json(_cms_url(api, {"ac": "list", "wd": keyword}), timeout)
            r["search_hits"] = len(s.get("list") or [])
            if r["search_hits"] == 0:
                r["error"] = f"搜索「{keyword}」无结果"
                return r

        r["status"] = "ok"
    except urllib.error.HTTPError as e:
        r["error"] = f"HTTP {e.code}"
    except urllib.error.URLError as e:
        r["error"] = f"连不上（{str(e.reason)[:40]}）"
    except (socket.timeout, TimeoutError):
        r["error"] = "超时"
    except ValueError:
        r["error"] = "返回非 JSON"
    except Exception as e:  # noqa: BLE001
        r["error"] = type(e).__name__
    return r


def collect_vod(cfg, do_probe=True, verbose=True):
    """按候选池逐个实测，只返回活着的站点。
    下划线开头的字段（_note 等）只是给人看的备注，不写进电视配置。
    """
    vod = cfg.get("vod", {})
    candidates = vod.get("sites", []) or []
    pc = vod.get("probe", {})
    timeout = int(pc.get("timeout", 12))
    workers = max(1, int(pc.get("workers", 6)))
    keyword = str(pc.get("keyword", "流浪地球"))
    require_search = bool(pc.get("require_search", True))
    do_probe = do_probe and bool(pc.get("enabled", True))

    if not do_probe or not candidates:
        results = [{"key": x.get("key"), "name": x.get("name"),
                    "api": x.get("api"), "status": "unprobed", "error": "未探活"}
                   for x in candidates]
    else:
        if verbose:
            print(color(f"  影视站探活中… 共 {len(candidates)} 个", "d"))

        def run_batch(idxs):
            out = {}
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futs = {
                    pool.submit(probe_vod_one, candidates[i], timeout,
                                keyword, require_search): i
                    for i in idxs
                }
                for f in as_completed(futs):
                    out[futs[f]] = f.result()
            return out

        first = run_batch(range(len(candidates)))
        # 免费采集站抖动很大，单次 RemoteDisconnected 多半是偶发。
        # 失败的重测一次，过了就恢复，别让接口列表在两次构建之间来回跳。
        retry = [i for i, r in first.items() if r.get("status") != "ok"]
        if retry:
            time.sleep(0.6)
            for i, r in run_batch(retry).items():
                if r.get("status") == "ok":
                    first[i] = r
        results = [first[i] for i in range(len(candidates))]

        if verbose:
            for rr in results:
                mark = "OK" if rr["status"] == "ok" else "NO"
                detail = (f"{rr['total']} 条 / 搜索 {rr['search_hits']} "
                          f"/ {rr['list_ms']}ms / {rr['play_host']}")
                print(f"  · [{mark}] {rr['name']}: {rr['error'] or detail}")

    sites = []
    for s, r in zip(candidates, results):
        if r.get("status") in ("ok", "unprobed"):
            sites.append({k: v for k, v in s.items() if not k.startswith("_")})

    health = {
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "probed": bool(do_probe),
        "keyword": keyword,
        "summary": {
            "sites_total": len(candidates),
            "sites_alive": len(sites),
        },
        "sites": results,
    }
    if verbose:
        print(color(f"  影视：{len(sites)}/{len(candidates)} 个接口可用", "g"))
    return sites, health


def build_index(cfg, lives, version, sites=None):
    player = cfg.get("player", {})
    idx = {
        "name": cfg.get("meta", {}).get("name", "TVBox 源"),
        "version": version,
        "wallpaper": "",
        "spider": "",
        "sites": sites if sites is not None else cfg.get("vod", {}).get("sites", []),
        "lives": lives,
        "parses": player.get("parses", []),
        "flags": player.get("flags", []),
        "ijk": player.get("ijk", []),
        "doh": player.get("doh", []),
    }
    return idx


def bump_version(old):
    try:
        parts = [int(x) for x in str(old).split(".")]
        while len(parts) < 3:
            parts.append(0)
        parts[-1] += 1
        return ".".join(str(x) for x in parts)
    except Exception:  # noqa: BLE001
        return "1.0.1"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-probe", action="store_true", help="跳过探活，快速构建（死链不会剔除）")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    verbose = not args.quiet

    with open(CFG_PATH, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    # 版本号：读旧 index.json 自增
    idx_path = os.path.join(OUT_DIR, "index.json")
    old_version = "1.0.0"
    if os.path.exists(idx_path):
        try:
            with open(idx_path, encoding="utf-8") as f:
                old_version = json.load(f).get("version", "1.0.0")
        except Exception:  # noqa: BLE001
            pass
    version = bump_version(old_version)

    if verbose:
        print(color(f"▶ 构建 {cfg.get('meta', {}).get('name')}  v{version}", "g"))

    if verbose:
        print(color("· 抓取上游清单", "d"))
    lives, health = collect_live(cfg, do_probe=not args.no_probe, verbose=verbose)
    sites, vod_health = collect_vod(cfg, do_probe=not args.no_probe, verbose=verbose)

    index = build_index(cfg, lives, version, sites)

    os.makedirs(OUT_DIR, exist_ok=True)

    # index.json —— 直播 + 影视合在一起，大多数 TVBox 填这一个就够
    with open(idx_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)

    # live.json —— 纯直播源，单独填「直播源 / EPG 地址」用
    live_only = dict(index, name=index["name"] + " - 直播", sites=[], lives=lives)
    with open(os.path.join(OUT_DIR, "live.json"), "w", encoding="utf-8") as f:
        json.dump(live_only, f, ensure_ascii=False, indent=2)

    # vod.json —— 纯影视源，单独填「影视仓 / 点播接口」用
    vod_only = dict(index, name=index["name"] + " - 影视", lives=[])
    with open(os.path.join(OUT_DIR, "vod.json"), "w", encoding="utf-8") as f:
        json.dump(vod_only, f, ensure_ascii=False, indent=2)

    with open(os.path.join(OUT_DIR, "health.json"), "w", encoding="utf-8") as f:
        json.dump(health, f, ensure_ascii=False, indent=2)

    with open(os.path.join(OUT_DIR, "vod-health.json"), "w", encoding="utf-8") as f:
        json.dump(vod_health, f, ensure_ascii=False, indent=2)

    # 纯文本 / m3u 直播清单 —— 给「直播源」输入框那种只认 txt / m3u 的地方用。
    # 每个频道只写第一条验证过的线路，避免同名多行在电视上显示成两个台。
    txt_lines, m3u_lines = [], ["#EXTM3U"]
    for g in lives:
        txt_lines.append(f"{g['group']},#genre#")
        for c in g["channels"]:
            url = c["urls"][0]
            txt_lines.append(f"{c['name']},{url}")
            m3u_lines.append(
                f'#EXTINF:-1 tvg-name="{c["name"]}" group-title="{g["group"]}",{c["name"]}'
            )
            m3u_lines.append(url)
    with open(os.path.join(OUT_DIR, "live.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(txt_lines) + "\n")
    with open(os.path.join(OUT_DIR, "live.m3u"), "w", encoding="utf-8") as f:
        f.write("\n".join(m3u_lines) + "\n")

    if verbose:
        n_sites = len(index["sites"])
        n_live = sum(len(g["channels"]) for g in lives)
        print(color(f"✔ 完成：{n_sites} 个影视站 / {n_live} 个直播频道", "g"))
        print("  → config/index.json   （接口框：直播+影视）")
        print("  → config/live.txt     （直播源框：txt 格式）")
        print("  → config/live.m3u     （直播源框：m3u 格式）")
        print("  → config/vod.json     （接口框：纯影视）")
        print("  → config/vod-health.json（影视站探活报告）")


if __name__ == "__main__":
    main()
