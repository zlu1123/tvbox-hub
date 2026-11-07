#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check.py —— 配置体检

做三件事：
  1. 结构校验：index.json 是否符合 TVBox 能解析的结构
  2. 站点连通：每个点播站 api 是否返回合法 CMS JSON
  3. 直播统计：读取 health.json 给出可用率

退出码 0 = 通过，1 = 有致命错误（CI 里会拦住合并）
"""

import json
import os
import sys
import urllib.request
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX = os.path.join(ROOT, "config", "index.json")
HEALTH = os.path.join(ROOT, "config", "health.json")
UA = "okhttp/3.12.0"

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
    print("\n[1/3] 结构校验")
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
        if s.get("type") not in VALID_SITE_TYPES:
            err(f"{tag} type={s.get('type')} 非法（只允许 0/1/3/4）")
        if s.get("key") in seen_keys:
            err(f"{tag} key 重复：{s.get('key')}")
        seen_keys.add(s.get("key"))
        api = str(s.get("api", ""))
        if s.get("type") == 4:
            if not api.startswith(("http://", "https://")):
                err(f"{tag} type=4 的 api 必须是 http(s) 地址")
            elif is_private(urlparse(api).hostname):
                warn(f"{tag} 「{s.get('name')}」指向内网地址 {urlparse(api).hostname}，"
                     f"只有同一局域网内可用")
        if s.get("type") == 0 and not idx.get("spider"):
            warn(f"{tag} type=0 需要顶层 spider 字段，当前为空")
    if idx["sites"]:
        ok(f"{len(idx['sites'])} 个站点字段完整")
    else:
        ok("未配置点播站点，按纯直播模式运行（正常状态）")

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


def check_sites(idx):
    print("\n[2/3] 站点连通性")
    sites = [s for s in idx.get("sites", []) if s.get("type") == 4]
    if not sites:
        ok("无点播站点需要检测（纯直播模式）")
        return
    reachable = 0
    for s in sites:
        api = s.get("api", "")
        host = urlparse(api).hostname or ""
        if is_private(host):
            warn(f"「{s.get('name')}」内网地址，跳过连通检测（需在局域网内自测）")
            continue
        url = api + ("&" if "?" in api else "?") + "ac=list"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=10) as r:
                body = r.read(4096).decode("utf-8", "ignore")
            if '"class"' in body or '"list"' in body:
                ok(f"「{s.get('name')}」接口正常")
                reachable += 1
            else:
                warn(f"「{s.get('name')}」返回内容不像 CMS JSON，请确认接口类型")
        except Exception as e:  # noqa: BLE001
            warn(f"「{s.get('name')}」不可达（{type(e).__name__}），"
                 f"若站点已下线请删除或更新 api")
    if reachable == 0:
        warn("没有任何可访问的公网点播站")


def check_health():
    print("\n[3/3] 直播可用率")
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
        warn(f"可用率偏低：{msg}")
    else:
        ok(msg)

    dead = [c for c in h.get("channels", []) if c.get("status") == "dead"]
    if dead:
        names = "、".join(c["name"] for c in dead[:10])
        more = f" 等 {len(dead)} 个" if len(dead) > 10 else ""
        print(f"      已剔除：{names}{more}")


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
    check_sites(idx)
    check_health()

    print("\n" + "=" * 56)
    if errors:
        print(f" 结果：\033[31m{len(errors)} 个错误\033[0m，{len(warns)} 个警告"
              if sys.stdout.isatty() else f" 结果：{len(errors)} 个错误，{len(warns)} 个警告")
        return 1
    print(f" 结果：通过（{len(warns)} 个警告）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
