#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check.py —— 配置体检

做四件事：
  1. 结构校验：index.json 是否符合 TVBox 能解析的结构
  2. 影视站探活：读 vod-health.json（build.py 的实测结果，这里不重复联网）
  3. 直播可用率：读 health.json
  4. 产物一致性：index / vod / live / txt / m3u 之间的版本与内容是否对齐

退出码 0 = 通过，1 = 有致命错误（CI 里会拦住合并）
"""

import json
import os
import sys
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(ROOT, "config")
INDEX = os.path.join(CONFIG, "index.json")
HEALTH = os.path.join(CONFIG, "health.json")
VOD_HEALTH = os.path.join(CONFIG, "vod-health.json")

# TVBox 的 site.type：0=XML(at/xml) 1=JSON(苹果CMS) 3=spider(jar) 4=部分分支的扩展
VALID_SITE_TYPES = {0, 1, 3, 4}
REQUIRED_SITE_KEYS = ("key", "name", "type", "api")

errors = []
warns = []


def err(msg):
    errors.append(msg)
    print(f"  \033[31m✗\033[0m {msg}" if sys.stdout.isatty() else f"  x {msg}")


def warn(msg):
    warns.append(msg)
    print(f"  \033[33m!\033[0m {msg}" if sys.stdout.isatty() else f"  ! {msg}")


def ok(msg):
    print(f"  \033[32m✓\033[0m {msg}" if sys.stdout.isatty() else f"  + {msg}")


def is_private(host):
    if not host:
        return False
    if host in ("localhost", "127.0.0.1"):
        return True
    parts = host.split(".")
    if len(parts) == 4 and all(p.isdigit() for p in parts):
        a, b = int(parts[0]), int(parts[1])
        return a == 10 or (a == 172 and 16 <= b <= 31) or (a == 192 and b == 168)
    return False


def check_structure(idx):
    print("\n[1/4] 结构校验")
    for k in ("sites", "lives"):
        if k not in idx:
            err(f"缺少顶层字段 {k}")
    if not isinstance(idx.get("sites"), list):
        err("sites 必须是数组")
        return

    seen_keys = set()
    for i, s in enumerate(idx["sites"]):
        tag = f"sites[{i}]"
        for rk in REQUIRED_SITE_KEYS:
            if rk not in s:
                err(f"{tag} 缺少字段 {rk}")
        typ = s.get("type")
        if typ not in VALID_SITE_TYPES:
            err(f"{tag} type={typ} 非法（只允许 0/1/3/4）")
        if s.get("key") in seen_keys:
            err(f"{tag} key 重复：{s.get('key')}")
        seen_keys.add(s.get("key"))

        api = str(s.get("api", ""))
        if typ in (0, 1, 4) and api:
            if not api.startswith(("http://", "https://")):
                err(f"{tag} api 必须是 http(s) 地址")
            elif is_private(urlparse(api).hostname):
                warn(f"{tag} 「{s.get('name')}」指向内网地址 "
                     f"{urlparse(api).hostname}，只有同一局域网内可用")
        if typ == 1 and "at/xml" in api:
            err(f"{tag} type=1 是 JSON 接口，api 不能带 /at/xml/（那是 type=0 用的）")
        if typ == 3 and not idx.get("spider"):
            warn(f"{tag} type=3 需要顶层 spider 字段，当前为空")
        for k in s:
            if k.startswith("_"):
                warn(f"{tag} 内部备注字段 {k} 泄漏到了电视配置里")

    if idx["sites"]:
        ok(f"{len(idx['sites'])} 个影视站点字段完整")
    else:
        warn("index.json 里没有影视站点；若候选池有接口，看 vod-health.json 是不是全被判死了")

    lives = idx.get("lives") or []
    total_ch = 0
    for g in lives:
        if "group" not in g or "channels" not in g:
            err(f"lives 分组缺少 group/channels：{g.get('group', '?')}")
            continue
        for c in g["channels"]:
            total_ch += 1
            if not c.get("name") or not c.get("urls"):
                err(f"频道 {c.get('name', '?')} 缺少 name 或 urls")
            for u in c.get("urls", []):
                if not str(u).startswith(("http://", "https://", "rtmp://", "rtsp://")):
                    err(f"频道 {c['name']} 地址协议非法：{u}")
    ok(f"{len(lives)} 个直播分组 / {total_ch} 个频道")


def check_vod_health():
    print("\n[2/4] 影视站探活")
    if not os.path.exists(VOD_HEALTH):
        warn("没有 vod-health.json，先跑一次 build.py")
        return
    with open(VOD_HEALTH, encoding="utf-8") as f:
        h = json.load(f)
    s = h.get("summary", {})
    total, alive = s.get("sites_total", 0), s.get("sites_alive", 0)
    msg = f"{alive}/{total} 个接口可用（关键词「{h.get('keyword', '?')}」）"
    if not h.get("probed", True):
        warn(f"本次未探活（--no-probe）：{msg}")
        return
    if total == 0:
        warn("候选池是空的，电视上只有直播、搜不了片")
        return
    if alive == 0:
        err(f"所有影视接口都失效了：{msg}")
    elif alive < total:
        dead = [x["name"] for x in h.get("sites", []) if x.get("status") != "ok"]
        warn(f"{msg}，已自动剔除：{'、'.join(dead)}")
    else:
        ok(f"{msg}，列表 / 详情 / 搜索三项均实测通过")
    for x in h.get("sites", []):
        if x.get("status") == "ok":
            print(f"      {x['name']}: {x.get('total', 0)} 条 · "
                  f"{x.get('list_ms', 0)}ms · 播放 {x.get('play_host', '?')}")


def check_health():
    print("\n[3/4] 直播可用率")
    if not os.path.exists(HEALTH):
        warn("没有 health.json，先跑一次 build.py")
        return
    with open(HEALTH, encoding="utf-8") as f:
        h = json.load(f)
    s = h.get("summary", {})
    ct, ca = s.get("channels_total", 0), s.get("channels_alive", 0)
    lt, la = s.get("lines_total", 0), s.get("lines_alive", 0)
    rate = (ca / ct * 100) if ct else 0
    msg = (f"{ca}/{ct} 个频道可用（{rate:.0f}%），"
           f"线路 {la}/{lt} 存活 · {h.get('generated_at', '?')}")
    if not h.get("probed", True):
        warn(f"本次未探活（--no-probe）：{msg}")
    elif ct == 0:
        warn("配置里没有任何直播频道")
    elif rate < 40:
        err(f"可用率过低：{msg}")
    elif rate < 70:
        warn(f"可用率偏低（广告清洗后的预期结果）：{msg}")
    else:
        ok(msg)

    dead = [c for c in h.get("channels", []) if c.get("status") == "dead"]
    if dead:
        names = "、".join(c["name"] for c in dead[:10])
        more = f" 等 {len(dead)} 个" if len(dead) > 10 else ""
        print(f"      已剔除：{names}{more}")


def check_artifacts(idx):
    print("\n[4/4] 产物一致性")
    ver = idx.get("version")
    expect_ch = sum(len(g.get("channels", [])) for g in idx.get("lives", []))

    for fn, want_sites, want_lives in (("vod.json", True, False),
                                       ("live.json", False, True)):
        path = os.path.join(CONFIG, fn)
        if not os.path.exists(path):
            err(f"缺少 {fn}")
            continue
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        if d.get("version") != ver:
            err(f"{fn} 版本 {d.get('version')} 与 index.json 的 {ver} 不一致")
        if want_sites and d.get("sites") != idx.get("sites"):
            err(f"{fn} 的 sites 与 index.json 不一致")
        if want_lives and d.get("lives") != idx.get("lives"):
            err(f"{fn} 的 lives 与 index.json 不一致")
        if want_sites and d.get("lives"):
            err(f"{fn} 不该带 lives")
        if want_lives and d.get("sites"):
            err(f"{fn} 不该带 sites")

    txt = os.path.join(CONFIG, "live.txt")
    m3u = os.path.join(CONFIG, "live.m3u")
    if os.path.exists(txt):
        lines = [l for l in open(txt, encoding="utf-8").read().splitlines() if l.strip()]
        ch = [l for l in lines if "," in l and not l.endswith(",#genre#")]
        if len(ch) != expect_ch:
            err(f"live.txt 有 {len(ch)} 个频道，index.json 里是 {expect_ch} 个")
    else:
        err("缺少 live.txt")
    if os.path.exists(m3u):
        n = sum(1 for l in open(m3u, encoding="utf-8").read().splitlines()
                if l.startswith("#EXTINF"))
        if n != expect_ch:
            err(f"live.m3u 有 {n} 个频道，index.json 里是 {expect_ch} 个")
    else:
        err("缺少 live.m3u")
    ok(f"index / vod / live / txt / m3u 版本 {ver}、{expect_ch} 个频道对齐")


def main():
    print("=" * 56)
    print(" TVBox 源配置体检")
    print("=" * 56)
    if not os.path.exists(INDEX):
        print("找不到 config/index.json，先运行 python3 scripts/build.py")
        return 1
    with open(INDEX, encoding="utf-8") as f:
        idx = json.load(f)

    check_structure(idx)
    check_vod_health()
    check_health()
    check_artifacts(idx)

    print("\n" + "=" * 56)
    if errors:
        print(f" 结果：\033[31m{len(errors)} 个错误\033[0m，{len(warns)} 个警告"
              if sys.stdout.isatty() else f" 结果：{len(errors)} 个错误，{len(warns)} 个警告")
        return 1
    print(f" 结果：通过（{len(warns)} 个警告）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
