#!/usr/bin/env bash
# =============================================================================
#  refresh.sh —— 在本地刷新配置并推送到 GitHub
#
#  为什么要在本地跑：探活结果和你家宽带强相关。GitHub Actions 跑在境外机房，
#  它判定"活着"的流，你在国内可能拉不动；反之亦然。所以探活这一步放在你
#  自己的网络里做，CI 只负责把结果发布出去。
#
#  一次跑完做五件事：同步远端 → 拼装两份 README → 构建配置 → 体检 →
#  整体提交并双推（GitHub 主仓库 + Gitee 镜像，后者自动注入 Gitee 版 README）。
#  改 docs/readme/ 下的 README 源文件后，同样跑这个命令即可两边同步。
#
#  用法：
#    ./scripts/refresh.sh              # 探活 + 整体提交 + 双推
#    ./scripts/refresh.sh --no-probe   # 不探活，只重新抓清单（很快）
#    ./scripts/refresh.sh --dry        # 只看结果，不提交不推送
#    ./scripts/refresh.sh -m "说明"    # 自定义提交信息（默认按时间生成）
# =============================================================================
set -uo pipefail

cd "$(dirname "$0")/.." || exit 1
RED=$'\033[31m'; GRN=$'\033[32m'; YEL=$'\033[33m'; DIM=$'\033[2m'; RST=$'\033[0m'
ok()   { printf '%s✓%s %s\n' "$GRN" "$RST" "$*"; }
warn() { printf '%s!%s %s\n' "$YEL" "$RST" "$*"; }
die()  { printf '%s✗%s %s\n' "$RED" "$RST" "$*" >&2; exit 1; }
step() { printf '\n%s▸ %s%s\n' "$DIM" "$*" "$RST"; }

NO_PROBE=""; DRY=0; MSG=""
while [ $# -gt 0 ]; do
  case "$1" in
    --no-probe) NO_PROBE="--no-probe"; shift ;;
    --dry)      DRY=1; shift ;;
    -m|--message)
      MSG="${2:-}"
      [ -n "$MSG" ] || die "-m 后面要跟提交信息"
      shift 2 ;;
    -h|--help)  sed -n '2,19p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *)          die "未知参数：$1" ;;
  esac
done

command -v python3 >/dev/null || die "没装 python3"
python3 -c "import yaml" 2>/dev/null || {
  warn "缺少 pyyaml，正在安装…"
  pip3 install -q pyyaml || die "pyyaml 安装失败：pip3 install pyyaml"
}

# ---------------------------------------------------------------------------
step "1/5 同步远端"

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
step "2/5 生成两份 README"
# 必须在 pull 之后：远端可能刚更新过 docs/readme/ 源文件
./scripts/gen-readme.sh || die "README 生成失败"

step "3/5 构建配置"
python3 scripts/build.py $NO_PROBE || die "构建失败"

step "4/5 配置体检"
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
step "5/5 整体提交并双推"

# 整体提交：配置、README 源文件、脚本改动一起进同一个 commit
if [ -z "$(git status --porcelain)" ]; then
  ok "无变化，无需推送"
  exit 0
fi

git add -A
[ -n "$MSG" ] || MSG="chore: 本地探活刷新 $(date '+%Y-%m-%d %H:%M')"
git -c user.name="$(git config user.name || echo tvbox)" \
    -c user.email="$(git config user.email || echo tvbox@local)" \
    commit -q -m "$MSG"

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
    # API 推送创建的 commit 与本地内容相同但 SHA 不同。对齐一下，
    # 否则下次开头的 pull --rebase 会把等价提交重放一遍甚至起冲突。
    if git fetch origin main -q 2>/dev/null; then
      git reset --hard origin/main -q 2>/dev/null \
        && ok "已对齐远端引用（API 推送产生的等价分叉）"
    fi
  else
    tail -6 "$LOG"
  fi
fi
rm -f "$LOG"

if [ "$PUSHED" -eq 1 ]; then
  SLUG=$(git remote get-url origin | sed -E 's#.*github\.com[:/]([^/]+/[^/.]+)(\.git)?#\1#')
  ok "已推送 GitHub"

  # Gitee 镜像：push-gitee.sh 会把 Gitee 版 README 注入提交树
  # （两边 README 不同，main 必然分叉，脚本自动保持 fast-forward）。
  # 失败只警告，不影响 GitHub 这条主线。
  if git remote get-url gitee >/dev/null 2>&1; then
    if ./scripts/push-gitee.sh >/dev/null 2>&1; then
      ok "已同步 Gitee 镜像（含 Gitee 版 README，推完立即生效）"
    else
      warn "Gitee 镜像没推上去，不影响 GitHub"
      warn "诊断：./scripts/push-gitee.sh --test / --check"
    fi
  fi

  printf '\n%s推荐（Gitee，推完立即生效）：%s\n' "$DIM" "$RST"
  printf '  %shttps://gitee.com/zlu1123/tvbox-hub/raw/main/config/index.json%s\n' "$GRN" "$RST"
  printf '  直播源框用 …/live.txt 或 …/live.m3u\n'
  printf '\n%s备用（jsDelivr，@main 有最长 12 小时解析缓存）：%s\n' "$DIM" "$RST"
  printf '  https://cdn.jsdelivr.net/gh/%s@main/config/index.json\n' "$SLUG"
  printf '%s（纯直播用 …/live.json，纯影视用 …/vod.json）%s\n' "$DIM" "$RST"
else
  die "推送失败。git 和 API 都没通，检查网络后重试"
fi
