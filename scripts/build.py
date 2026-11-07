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

try:
    import yaml
except ImportError:
    sys.exit("缺少依赖：pip install pyyaml")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG_PATH = os.path.join(ROOT, "config", "sources.yaml")
OUT_DIR = os.path.join(ROOT, "config")

UA = "okhttp/3.12.0"
ANSI = {"g": "\033[32m", "y": "\033[33m", "r": "\033[31m", "d": "\033[2m", "0": "\033[0m"}


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


EXTINF_RE = re.compile(r'#EXTINF:\s*(-?\d+(?:\.\d+)?)\s*(.*?),(.*)$')


def _attrs(s):
    return dict(re.findall(r'([\w-]+)="([^"]*)"', s))


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
                m = EXTINF_RE.match(line)
                if not m:
                    cur = None
                    continue
                attr_str, title = m.group(2), m.group(3).strip()
                a = _attrs(attr_str)
                cur = {
                    "name": title,
                    "group": a.get("group-title", ""),
                    "logo": a.get("tvg-logo", ""),
                    "raw_attr": attr_str,
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
    r"\s+(HD|SD|FHD|UHD|4K|8K|H265|HEVC|Multi|Audio)$", re.I
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
def probe_one(url, timeout=8, retries=2):
    """拉取 .m3u8 校验内容；非 m3u8 只校验 HTTP 状态"""
    last_err = ""
    for _ in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                if r.status >= 400:
                    last_err = f"HTTP {r.status}"
                    continue
                head = r.read(4096)
            if url.split("?")[0].lower().endswith((".m3u8", ".m3u")):
                if b"#EXTM3U" not in head:
                    last_err = "非有效 m3u8"
                    continue
            return True, ""
        except urllib.error.HTTPError as e:
            last_err = f"HTTP {e.code}"
        except (socket.timeout, TimeoutError):
            last_err = "超时"
        except Exception as e:  # noqa: BLE001
            last_err = type(e).__name__
        time.sleep(0.5)
    return False, last_err


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------
def collect_live(cfg, do_probe=True, verbose=True):
    lc = cfg.get("live", {})
    if not lc.get("enabled", True):
        return [], []

    inc = [re.compile(p, re.I) for p in lc.get("include", [])]
    exc = [re.compile(p, re.I) for p in lc.get("exclude", [])]
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
        kept = 0
        for it in items:
            raw = it["name"]
            base = clean_name(raw)
            if not base:
                continue
            # 优先用映射表里的中文名，没有就用清洗后的原名
            name = name_map.get(base, base)
            if not trust:
                if inc and not any(p.search(name) or p.search(raw) for p in inc):
                    continue
                if any(p.search(raw) or p.search(name) for p in exc):
                    continue
            b = buckets.setdefault(
                name,
                {"name": name, "urls": [], "logo": it.get("logo", ""),
                 "group": channel_group(name)},
            )
            if it["url"] not in b["urls"]:
                b["urls"].append(it["url"])
            kept += 1
        if verbose:
            print(f"  · {up['name']}: 抓到 {len(items)} 条，命中 {kept} 条")

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
    else:
        for n, us in all_urls.items():
            for u in us:
                line_result[(n, u)] = (True, "未探活")

    def _ok(n, u):
        return line_result.get((n, u), (True, ""))[0]

    # ---- 组装 ----
    groups = {"央视": [], "卫视": [], "其他": []}
    channels_health = []
    alive_lines = 0
    for name, b in buckets.items():
        us = all_urls[name]
        ok_urls = [u for u in us if _ok(name, u)]
        alive_lines += len(ok_urls)
        errs = sorted({line_result[(name, u)][1] for u in us
                       if (name, u) in line_result and not line_result[(name, u)][0]})

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


def build_index(cfg, lives, version):
    vod = cfg.get("vod", {})
    player = cfg.get("player", {})
    idx = {
        "name": cfg.get("meta", {}).get("name", "TVBox 源"),
        "version": version,
        "wallpaper": "",
        "spider": "",
        "sites": vod.get("sites", []),
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

    index = build_index(cfg, lives, version)

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(idx_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
    with open(os.path.join(OUT_DIR, "live.json"), "w", encoding="utf-8") as f:
        json.dump({"lives": lives}, f, ensure_ascii=False, indent=2)
    with open(os.path.join(OUT_DIR, "health.json"), "w", encoding="utf-8") as f:
        json.dump(health, f, ensure_ascii=False, indent=2)

    # 同步版本号回 sources.yaml，避免下次重算
    if verbose:
        n_sites = len(index["sites"])
        n_live = sum(len(g["channels"]) for g in lives)
        print(color(f"✔ 完成：{n_sites} 个点播站 / {n_live} 个直播频道", "g"))
        print(f"  → {os.path.relpath(idx_path, ROOT)}")


if __name__ == "__main__":
    main()
