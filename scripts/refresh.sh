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
step "1/3 构建配置"
python3 scripts/build.py $NO_PROBE || die "构建失败"

step "2/3 配置体检"
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
step "3/3 提交并推送"

if [ -z "$(git status --porcelain config/)" ]; then
  ok "配置无变化，无需推送"
  exit 0
fi

git add config/
git -c user.name="$(git config user.name || echo tvbox)" \
    -c user.email="$(git config user.email || echo tvbox@local)" \
    commit -q -m "chore: 本地探活刷新 $(date '+%Y-%m-%d %H:%M')"

LOG=$(mktemp)
if git push origin main >"$LOG" 2>&1; then
  tail -2 "$LOG"
  ok "已推送，等 1 分钟 Actions 发布完成"
  CONFIG_URL=$(git remote get-url origin \
    | sed -E 's#.*github\.com[:/]([^/]+)/([^/.]+)(\.git)?#https://\1.github.io/\2/index.json#')
  printf '\n配置地址：%s%s%s\n' "$GRN" "$CONFIG_URL" "$RST"
else
  tail -5 "$LOG"
  rm -f "$LOG"
  die "推送失败。检查网络，或执行 gh auth login 重新授权"
fi
rm -f "$LOG"
