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
#  一次性准备（只需做一次，见 README「Gitee 镜像」）：
#    1) 在 Gitee 添加本机 SSH 公钥：https://gitee.com/profile/sshkeys
#    2) 在 Gitee 新建一个**空的公开**仓库 tvbox-hub（不要勾初始化文件）
#    3) 本脚本会自动配上 gitee remote，之后 `./scripts/refresh.sh` 会双推
#
#  用法：
#    ./scripts/push-gitee.sh          # 推送 main
#    ./scripts/push-gitee.sh --test   # 只测 SSH 连通性
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

if [ "${1:-}" = "--test" ]; then
  echo "测试 Gitee SSH 认证…"
  OUT=$(ssh -T -o StrictHostKeyChecking=no -o ConnectTimeout=12 git@gitee.com 2>&1) || true
  echo "$OUT" | head -4
  if echo "$OUT" | grep -qi "successfully authenticated\|Hi ${OWNER}"; then
    ok "SSH 已授权，可以推送"
  else
    warn "SSH 还没授权。把下面这把公钥加到 https://gitee.com/profile/sshkeys ："
    echo
    cat ~/.ssh/id_ed25519.pub 2>/dev/null || cat ~/.ssh/id_rsa.pub 2>/dev/null
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

LOG=$(mktemp)
if git -c http.lowSpeedLimit=1000 -c http.lowSpeedTime=15 push gitee main >"$LOG" 2>&1; then
  tail -3 "$LOG"
  ok "已推送到 Gitee"
else
  tail -8 "$LOG"
  echo
  if grep -qi "Permission denied (publickey)\|Could not read Username" "$LOG"; then
    rm -f "$LOG"
    die "认证失败。先执行 ./scripts/push-gitee.sh --test 看授权指引"
  fi
  rm -f "$LOG"
  die "推送失败。确认 Gitee 上已建好空的公开仓库 ${OWNER}/${REPO}"
fi
rm -f "$LOG"

BASE="https://gitee.com/${OWNER}/${REPO}/raw/main/config"
printf '\n电视上填这些地址（推完立刻生效，不用等缓存）：\n'
printf '  %s%s/index.json%s   （接口框：直播+影视）\n' "$GRN" "$BASE" "$RST"
printf '  %s%s/live.txt%s     （直播源框：txt）\n' "$GRN" "$BASE" "$RST"
printf '  %s%s/live.m3u%s     （直播源框：m3u）\n' "$GRN" "$BASE" "$RST"
printf '  %s%s/vod.json%s     （纯影视）\n' "$GRN" "$BASE" "$RST"
