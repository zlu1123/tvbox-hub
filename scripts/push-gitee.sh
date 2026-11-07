#!/usr/bin/env bash
# =============================================================================
#  push-gitee.sh —— 把当前配置镜像推到 Gitee，给电视用 Gitee raw 地址
#
#  为什么需要 Gitee：
#    · jsDelivr 的 @main 会把「分支→commit」缓存最长 12 小时，push 完电视
#      上看到的还是旧内容；Gitee raw 没有这层缓存，推完立刻生效。
#    · gitee.com / raw.giteeusercontent.com 的证书链终结在
#      Certum Trusted Network CA，电视（Android 6）证书库里有这个根，
#      而 github.io 用的 Let's Encrypt (ISRG Root X1) 它没有 → 加载失败。
#
#  双 README：两个平台的 README.md 内容不同（docs/readme/ 下各自维护），
#  所以 Gitee 的 main 与 GitHub 的 main 必然分叉。本脚本不直接 push HEAD，
#  而是基于 Gitee 远端 HEAD 构造一个「只把 README.md 换成 Gitee 版」的提交，
#  parent 指向远端当前 commit，保证 fast-forward。不要手动 git push gitee main。
#
#  用法：
#    ./scripts/push-gitee.sh          # 推送 main（推完自动自检 raw）
#    ./scripts/push-gitee.sh --test   # 只测 SSH 连通性
#    ./scripts/push-gitee.sh --check  # 只测电视端 raw 地址能否匿名访问
# =============================================================================
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

RED=$'\033[31m'; GRN=$'\033[32m'; YEL=$'\033[33m'; DIM=$'\033[2m'; RST=$'\033[0m'
ok()   { printf '%sOK%s %s\n' "$GRN" "$RST" "$*"; }
warn() { printf '%s!%s %s\n' "$YEL" "$RST" "$*"; }
die()  { printf '%sX%s %s\n' "$RED" "$RST" "$*" >&2; exit 1; }

OWNER="${GITEE_OWNER:-zlu1123}"
REPO="${GITEE_REPO:-tvbox-hub}"
REMOTE_URL="git@gitee.com:${OWNER}/${REPO}.git"
RAW_BASE="https://gitee.com/${OWNER}/${REPO}/raw/main/config"

check_raw() {
  local tmp; tmp=$(mktemp)
  local code
  code=$(curl -sL --http1.1 -m 20 -o "$tmp" -w '%{http_code}' "${RAW_BASE}/index.json")
  if [ "$code" = "200" ] && python3 -c "import json,sys; d=json.load(open('$tmp')); assert d['lives']" 2>/dev/null; then
    ok "raw 匿名可访问，电视能用（HTTP 200）"
  elif [ "$code" = "403" ] || [ "$code" = "404" ]; then
    warn "raw 返回 HTTP ${code}：电视上会加载失败"
    printf '  %s仓库还没公开。去 Gitee → 仓库「管理 / 设置」→ 把「是否公开」设为公开（新账号可能需要先实名认证）。%s\n' "$YEL" "$RST"
    printf '  地址：https://gitee.com/%s/%s/settings\n' "$OWNER" "$REPO"
    rm -f "$tmp"; return 1
  else
    warn "raw 返回 HTTP ${code}，稍后重试：./scripts/push-gitee.sh --check"
    rm -f "$tmp"; return 1
  fi
  rm -f "$tmp"
  return 0
}

if [ "${1:-}" = "--check" ]; then
  echo "自检电视端 raw 地址（匿名、模拟电视不登录）…"
  check_raw && printf '\n%s%s/index.json%s\n' "$GRN" "$RAW_BASE" "$RST"
  exit $?
fi

# 本机 ~/.ssh/config 的 `Host *` 写死了 IdentityFile ~/.ssh/id_rsa，
# 会把 Gitee 上登记的那把 ed25519 挤掉（实测默认连接 Permission denied，
# 指定 -i 后返回 "Hi zlu1123! You've successfully authenticated"）。
# 所以这里显式指定密钥，不改用户的全局配置。
KEY="${GITEE_SSH_KEY:-$HOME/.ssh/id_ed25519}"
SSH_CMD="ssh -i ${KEY} -o IdentitiesOnly=yes"

if [ "${1:-}" = "--test" ]; then
  echo "测试 Gitee SSH 认证（密钥 ${KEY}）…"
  OUT=$(${SSH_CMD} -o StrictHostKeyChecking=no -o ConnectTimeout=12 -T git@gitee.com 2>&1) || true
  echo "$OUT" | head -4
  if echo "$OUT" | grep -qi "successfully authenticated\|Hi .*(@${OWNER})"; then
    ok "SSH 已授权，可以推送"
  else
    warn "SSH 还没授权。把下面这把公钥加到 https://gitee.com/profile/sshkeys ："
    echo
    cat "${KEY}.pub" 2>/dev/null || echo "（找不到 ${KEY}.pub）"
    echo
    exit 1
  fi
  exit 0
fi

# 确保 gitee remote 存在且地址正确
if git remote get-url gitee >/dev/null 2>&1; then
  git remote set-url gitee "$REMOTE_URL"
else
  git remote add gitee "$REMOTE_URL"
fi
ok "gitee remote = $REMOTE_URL"

# ---- 生成 Gitee 版 README（若还没生成）----
GITEE_README=".build/README.gitee.md"
if [ ! -f "$GITEE_README" ]; then
  ./scripts/gen-readme.sh >/dev/null || die "生成 README 失败"
fi

# ---- 取 Gitee 远端当前 HEAD 作为 parent ----
LOG=$(mktemp)
if ! git -c "core.sshCommand=${SSH_CMD}" fetch gitee main -q >"$LOG" 2>&1; then
  tail -6 "$LOG"
  if grep -qi "Permission denied (publickey)" "$LOG" 2>/dev/null; then
    rm -f "$LOG"
    die "认证失败。先执行 ./scripts/push-gitee.sh --test 看授权指引"
  fi
  rm -f "$LOG"
  die "拉不到 Gitee 远端。确认仓库 ${OWNER}/${REPO} 已建好"
fi
PARENT=$(git rev-parse FETCH_HEAD 2>/dev/null || true)

# ---- 用临时 index 构造「HEAD 的树 + Gitee 版 README」----
IDX=$(mktemp); rm -f "$IDX"
(
  export GIT_INDEX_FILE="$IDX"
  git read-tree HEAD || exit 1
  BLOB=$(git hash-object -w "$GITEE_README") || exit 1
  git update-index --add --cacheinfo "100644,${BLOB},README.md" || exit 1
  git write-tree
) >"$LOG" 2>&1 || { tail -6 "$LOG"; rm -f "$LOG" "$IDX"; die "构造 Gitee 提交树失败"; }
TREE=$(tail -1 "$LOG")
rm -f "$IDX"

# 内容没变就别制造空提交
REMOTE_TREE=$(git rev-parse "${PARENT}^{tree}" 2>/dev/null || true)
if [ -n "$REMOTE_TREE" ] && [ "$REMOTE_TREE" = "$TREE" ]; then
  ok "Gitee 已是最新（含 Gitee 版 README），无需推送"
  rm -f "$LOG"
else
  MSG="$(git log -1 --pretty=%B HEAD)"
  if [ -n "$PARENT" ]; then
    COMMIT=$(printf '%s' "$MSG" | git commit-tree "$TREE" -p "$PARENT") || {
      rm -f "$LOG"; die "创建 Gitee 提交失败"; }
  else
    COMMIT=$(printf '%s' "$MSG" | git commit-tree "$TREE") || {
      rm -f "$LOG"; die "创建 Gitee 提交失败"; }
  fi
  if git -c "core.sshCommand=${SSH_CMD}" push gitee "${COMMIT}:refs/heads/main" >"$LOG" 2>&1; then
    tail -3 "$LOG"
    ok "已推送到 Gitee（README 为 Gitee 版）"
  else
    tail -8 "$LOG"
    rm -f "$LOG"
    die "推送失败。确认 Gitee 上已建好公开仓库 ${OWNER}/${REPO}"
  fi
fi
rm -f "$LOG"

printf '\n自检 raw 匿名访问…\n'
check_raw || true

printf '\n电视上填这些地址（推完立刻生效，不用等缓存）：\n'
printf '  %s%s/index.json%s   （接口框：直播+影视）\n' "$GRN" "$RAW_BASE" "$RST"
printf '  %s%s/live.txt%s     （直播源框：txt）\n' "$GRN" "$RAW_BASE" "$RST"
printf '  %s%s/live.m3u%s     （直播源框：m3u）\n' "$GRN" "$RAW_BASE" "$RST"
printf '  %s%s/vod.json%s     （纯影视）\n' "$GRN" "$RAW_BASE" "$RST"
