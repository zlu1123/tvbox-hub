#!/usr/bin/env bash
# =============================================================================
#  refresh.sh —— 在本地刷新配置并推送到 GitHub
#
#  为什么要在本地跑：探活结果和你家宽带强相关。GitHub Actions 跑在境外机房，
#  它判定"活着"的流，你在国内可能拉不动；反之亦然。所以探活这一步放在你
#  自己的网络里做，CI 只负责把结果发布出去。
#
#  用法：
#    ./scripts/refresh.sh              # 探活 + 提交 + 推送
#    ./scripts/refresh.sh --no-probe   # 不探活，只重新抓清单（很快）
#    ./scripts/refresh.sh --dry        # 只看结果，不提交不推送
# =============================================================================
set -uo pipefail

cd "$(dirname "$0")/.." || exit 1
RED=$'\033[31m'; GRN=$'\033[32m'; YEL=$'\033[33m'; DIM=$'\033[2m'; RST=$'\033[0m'
ok()   { printf '%s✓%s %s\n' "$GRN" "$RST" "$*"; }
warn() { printf '%s!%s %s\n' "$YEL" "$RST" "$*"; }
die()  { printf '%s✗%s %s\n' "$RED" "$RST" "$*" >&2; exit 1; }
step() { printf '\n%s▸ %s%s\n' "$DIM" "$*" "$RST"; }

NO_PROBE=""; DRY=0
for a in "$@"; do
  case "$a" in
    --no-probe) NO_PROBE="--no-probe" ;;
    --dry)      DRY=1 ;;
    -h|--help)  sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *)          die "未知参数：$a" ;;
  esac
done

command -v python3 >/dev/null || die "没装 python3"
python3 -c "import yaml" 2>/dev/null || {
  warn "缺少 pyyaml，正在安装…"
  pip3 install -q pyyaml || die "pyyaml 安装失败：pip3 install pyyaml"
}

# ---------------------------------------------------------------------------
step "1/4 同步远端"

# 上次可能用 API 推的，本地 SHA 和远端不一致，先对齐再动手。
# 拉不动不影响后续（离线也能生成配置），只是推送时可能被拒。
if git fetch origin main -q 2>/dev/null; then
  if [ "$(git rev-parse HEAD)" != "$(git rev-parse origin/main)" ]; then
    git pull --rebase -q origin main 2>/dev/null && ok "已同步远端更新" \
      || warn "同步失败，继续用本地版本"
  else
    ok "已是最新"
  fi
else
  warn "连不上 origin，跳过同步（生成不受影响，推送时再处理）"
fi

# ---------------------------------------------------------------------------
step "2/4 构建配置"
python3 scripts/build.py $NO_PROBE || die "构建失败"

step "3/4 配置体检"
python3 scripts/check.py
CHECK=$?
if [ "$CHECK" -ne 0 ]; then
  die "体检未通过，已中止。修好再跑一次（配置没有被改动）"
fi

if [ "$DRY" -eq 1 ]; then
  printf '\n%s--dry 模式，不提交%s\n' "$DIM" "$RST"
  exit 0
fi

# ---------------------------------------------------------------------------
step "4/4 提交并推送"

if [ -z "$(git status --porcelain config/)" ]; then
  ok "配置无变化，无需推送"
  exit 0
fi

git add config/
git -c user.name="$(git config user.name || echo tvbox)" \
    -c user.email="$(git config user.email || echo tvbox@local)" \
    commit -q -m "chore: 本地探活刷新 $(date '+%Y-%m-%d %H:%M')"

LOG=$(mktemp)
PUSHED=0
if git push origin main >"$LOG" 2>&1; then
  tail -2 "$LOG"
  PUSHED=1
else
  warn "git push 失败（$(grep -o 'fatal:.*' "$LOG" | head -1 | cut -c1-70)）"
  warn "改用 GitHub API 推送…"
  if python3 scripts/push-api.py >"$LOG" 2>&1; then
    tail -3 "$LOG"
    PUSHED=1
  else
    tail -6 "$LOG"
  fi
fi
rm -f "$LOG"

if [ "$PUSHED" -eq 1 ]; then
  SLUG=$(git remote get-url origin | sed -E 's#.*github\.com[:/]([^/]+/[^/.]+)(\.git)?#\1#')
  ok "已推送"

  # jsDelivr 对 @main 分支的「分支→commit」解析缓存最长 12 小时，
  # purge 接口只清文件缓存、清不掉这个解析缓存（实测）。
  # 所以电视端的新配置最多延迟 12 小时生效。想立刻生效，见 README「缓存」一节。
  ok "已推送（电视端 jsDelivr 地址将在 12 小时内更新，急用见 README）"

  printf '\n电视上填这个地址：\n  %shttps://cdn.jsdelivr.net/gh/%s@main/config/index.json%s\n' \
    "$GRN" "$SLUG" "$RST"
  printf '%s（纯直播用 …/live.json，纯影视用 …/vod.json）%s\n' "$DIM" "$RST"
else
  die "推送失败。git 和 API 都没通，检查网络后重试"
fi
