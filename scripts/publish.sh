#!/usr/bin/env bash
# =============================================================================
#  publish.sh —— 一条命令完成：建仓库 + 推代码 + 开 Pages
#
#  用法：
#    ./scripts/publish.sh            # 仓库名默认用当前目录名（tvbox-hub）
#    ./scripts/publish.sh my-tvbox   # 自定义仓库名
#
#  第一次运行会在终端里走一遍 GitHub 授权（浏览器点一下），之后免登录。
#  需要你自己在终端里跑，因为要交互输入。
# =============================================================================
set -uo pipefail

cd "$(dirname "$0")/.." || exit 1
REPO_NAME="${1:-$(basename "$PWD")}"
RED=$'\033[31m'; GRN=$'\033[32m'; YEL=$'\033[33m'; DIM=$'\033[2m'; RST=$'\033[0m'

say()  { printf '%s\n' "$*"; }
ok()   { printf '%s✓%s %s\n' "$GRN" "$RST" "$*"; }
warn() { printf '%s!%s %s\n' "$YEL" "$RST" "$*"; }
die()  { printf '%s✗%s %s\n' "$RED" "$RST" "$*" >&2; exit 1; }
step() { printf '\n%s▸ %s%s\n' "$DIM" "$*" "$RST"; }

# ---------------------------------------------------------------------------
step "1/5 检查环境"

if ! command -v git >/dev/null 2>&1; then
  die "没装 git"
fi

if ! command -v gh >/dev/null 2>&1; then
  warn "没装 GitHub CLI（gh），正在安装…"
  if command -v brew >/dev/null 2>&1; then
    brew install gh || die "brew 安装 gh 失败，手动装：https://cli.github.com"
  else
    die "没有 Homebrew。先装：https://cli.github.com 然后重新运行本脚本"
  fi
fi
ok "gh $(gh --version | head -1 | awk '{print $3}')"

# ---------------------------------------------------------------------------
step "2/5 GitHub 授权"

if gh auth status >/dev/null 2>&1; then
  ok "已登录：$(gh api user -q .login 2>/dev/null)"
else
  say "需要浏览器授权一次，跟着提示走（选 GitHub.com → HTTPS → 浏览器登录）"
  gh auth login || die "授权失败"
fi

OWNER=$(gh api user -q .login 2>/dev/null) || die "拿不到用户名，授权可能没成功"
[ -n "$OWNER" ] || die "拿不到用户名"
ok "账号：$OWNER"

# ---------------------------------------------------------------------------
step "3/5 本地提交"

# gh 需要 scope 才能改仓库设置
if ! gh auth status 2>&1 | grep -q 'workflow'; then
  warn "授权缺少 workflow 权限，正在补…"
  gh auth refresh -s workflow,repo || warn "补充权限失败，Pages 可能需要在网页上手动开"
fi

if ! git rev-parse --git-dir >/dev/null 2>&1; then
  git init -q
  ok "初始化 git 仓库"
fi

if [ -n "$(git status --porcelain)" ]; then
  git add -A
  git commit -q -m "chore: 发布前更新配置" && ok "已提交本地改动"
else
  ok "工作区干净"
fi

git branch -M main
ok "分支：main"

# ---------------------------------------------------------------------------
step "4/5 创建远程仓库并推送"

REMOTE_URL="https://github.com/$OWNER/$REPO_NAME.git"

# 先确保远程仓库存在（已经手动建过就跳过）
if gh repo view "$OWNER/$REPO_NAME" >/dev/null 2>&1; then
  ok "远程仓库已存在：$OWNER/$REPO_NAME"
else
  say "创建仓库 $OWNER/$REPO_NAME …"
  gh repo create "$REPO_NAME" --public \
    --description "自建 TVBox 源，每日自动探活刷新" >/dev/null || die "创建仓库失败"
  ok "已创建"
fi

# origin 统一指向这个仓库（已配过就改，不重复 add）
if git remote get-url origin >/dev/null 2>&1; then
  git remote set-url origin "$REMOTE_URL"
else
  git remote add origin "$REMOTE_URL"
fi
ok "origin → $REMOTE_URL"

git push -u origin main || die "推送失败。若是 non-fast-forward，执行：git pull --rebase origin main"
ok "已推送：https://github.com/$OWNER/$REPO_NAME"

# ---------------------------------------------------------------------------
step "5/5 开启 GitHub Pages"

# build_type=workflow 表示由 Actions 发布，而不是从分支根目录发布
if gh api "repos/$OWNER/$REPO_NAME/pages" >/dev/null 2>&1; then
  gh api -X PUT "repos/$OWNER/$REPO_NAME/pages" -f build_type=workflow >/dev/null 2>&1 \
    && ok "Pages 已开启（workflow 模式）" || warn "Pages 已存在，跳过"
else
  if gh api -X POST "repos/$OWNER/$REPO_NAME/pages" -f build_type=workflow >/dev/null 2>&1; then
    ok "Pages 已开启（workflow 模式）"
  else
    warn "API 开启 Pages 失败，请到网页手动开："
    say  "  Settings → Pages → Source 选 GitHub Actions"
  fi
fi

URL="https://cdn.jsdelivr.net/gh/$OWNER/$REPO_NAME@main/config/index.json"
printf '\n%s\n' "────────────────────────────────────────────"
say "配置地址（填到电视上）："
printf '  %s%s%s\n' "$GRN" "$URL" "$RST"
printf '%s\n' "────────────────────────────────────────────"
say ""
say "${DIM}Actions 里「刷新源并发布」跑完（约 1 分钟）地址才生效。${RST}"
say "${DIM}查看进度：gh run watch${RST}"
say ""
say "接下来在电视上：TVBox → 设置 → 配置地址 → 粘贴上面那行"
