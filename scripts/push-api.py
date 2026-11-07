#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
push-api.py —— 当 github.com:443 被阻断、git push 推不上去时的兜底方案

背景：国内网络下 `git push` 常常报
    fatal: unable to access ...: LibreSSL SSL_connect: SSL_ERROR_SYSCALL
这是 TLS 握手被重置，跟仓库配置无关。但 api.github.com 通常还能通，
所以改用 GitHub 的 Git Data API（blob → tree → commit → ref）把本地提交推上去。

用法：
    python3 scripts/push-api.py            # 推送 main 到 origin 指向的仓库
    python3 scripts/push-api.py --dry      # 只看要推什么，不真推

依赖：gh 已登录（gh auth login），用它的 token 调 API。
"""

import base64
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DRY = "--dry" in sys.argv


def git(*args):
    return subprocess.check_output(["git", "-C", ROOT, *args], text=True).strip()


def repo_info():
    url = git("remote", "get-url", "origin")
    m = re.search(r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?$", url)
    if not m:
        sys.exit(f"解析不了 origin 地址：{url}")
    return m.group(1), m.group(2)


OWNER, REPO = repo_info()
API = f"https://api.github.com/repos/{OWNER}/{REPO}"

try:
    TOK = subprocess.check_output(["gh", "auth", "token"], text=True).strip()
except Exception:
    sys.exit("拿不到 token，先执行：gh auth login")


def call(method, url, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {TOK}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "tvbox-hub-pusher")
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        sys.exit(f"{method} {url} 失败 {e.code}: {e.read().decode('utf-8', 'ignore')[:400]}")


def main():
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    raw = git("diff", "--name-status", f"origin/{branch}", "HEAD")
    if not raw:
        print("没有需要推送的变更")
        return
    files = [l.split("\t") for l in raw.splitlines()]
    msg = git("log", "-1", "--pretty=%B", "HEAD")

    ref = call("GET", f"{API}/git/ref/heads/{branch}")
    base_commit = ref["object"]["sha"]
    base_tree = call("GET", f"{API}/git/commits/{base_commit}")["tree"]["sha"]
    print(f"远端 {branch}: {base_commit[:8]}")

    entries = []
    for status, path in files:
        full = os.path.join(ROOT, path)
        if status == "D":
            entries.append({"path": path, "mode": "100644", "type": "blob", "sha": None})
            print(f"  D {path}")
        else:
            with open(full, "rb") as f:
                content = f.read()
            blob = call("POST", f"{API}/git/blobs", {
                "content": base64.b64encode(content).decode(), "encoding": "base64"})
            mode = "100755" if os.access(full, os.X_OK) else "100644"
            entries.append({"path": path, "mode": mode, "type": "blob", "sha": blob["sha"]})
            print(f"  {'A' if status == 'A' else 'M'} {path} ({len(content)}B)")

    if DRY:
        print("\n--dry 模式，未推送")
        return

    tree = call("POST", f"{API}/git/trees", {"base_tree": base_tree, "tree": entries})
    commit = call("POST", f"{API}/git/commits", {
        "message": msg, "tree": tree["sha"], "parents": [base_commit]})
    call("PATCH", f"{API}/git/refs/heads/{branch}", {"sha": commit["sha"], "force": False})
    print(f"\n✓ 已推送 https://github.com/{OWNER}/{REPO}/commit/{commit['sha']}")
    print("  本地 SHA 和远端会不一致（内容相同），下次推送前先 git fetch —— refresh.sh 已自动处理")


if __name__ == "__main__":
    main()
