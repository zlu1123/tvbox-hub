#!/usr/bin/env bash
# =============================================================================
#  gen-readme.sh —— 拼装两个平台各自的 README
#
#  公共正文只维护一份，平台头部各自维护：
#    docs/readme/_common.md  → 两个平台共用的正文
#    docs/readme/github.md   → GitHub 头部（地址表 + 镜像授权章节）
#    docs/readme/gitee.md    → Gitee 头部（镜像说明 + Gitee 地址表）
#
#  产物：
#    README.md                  → 提交进仓库，GitHub 展示
#    .build/README.gitee.md     → 推送时由 push-gitee.sh 注入 Gitee 的 README.md
#
#  refresh.sh 会在每次刷新开头自动调用，一般不用手动跑。
# =============================================================================
set -euo pipefail
cd "$(dirname "$0")/.." || exit 1

SRC=docs/readme
OUT=.build

for f in _common.md github.md gitee.md; do
  [ -f "$SRC/$f" ] || { echo "缺少 $SRC/$f" >&2; exit 1; }
done

mkdir -p "$OUT"
cat "$SRC/github.md" "$SRC/_common.md" > README.md
cat "$SRC/gitee.md"  "$SRC/_common.md" > "$OUT/README.gitee.md"

printf 'README.md              %s 行（GitHub 版）\n' "$(wc -l < README.md | tr -d ' ')"
printf '%s/README.gitee.md %s 行（Gitee 版）\n' "$OUT" "$(wc -l < "$OUT/README.gitee.md" | tr -d ' ')"
