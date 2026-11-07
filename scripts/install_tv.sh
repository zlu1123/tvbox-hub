#!/usr/bin/env bash
# =============================================================================
#  install_tv.sh —— 把 TVBox 装到安卓电视上
#
#  用法：
#    ./scripts/install_tv.sh scan                  # 扫描局域网里开了调试的电视
#    ./scripts/install_tv.sh download              # 下载最新版 APK 到 apk/
#    ./scripts/install_tv.sh install 192.168.1.23  # 连接并安装
#    ./scripts/install_tv.sh launch  192.168.1.23  # 启动已装好的 App
#    ./scripts/install_tv.sh info    192.168.1.23  # 看设备型号/系统版本
#
#  前置条件（电视端，一次性）：
#    设置 → 关于本机 → 连点「版本号」7 次开启开发者模式
#    → 开发者选项 → 打开「USB 调试」和「网络调试 / ADB 调试」
#    （小米/Redmi 还要额外打开「USB 安装」，否则会报 USER_RESTRICTED）
# =============================================================================
set -uo pipefail

cd "$(dirname "$0")/.." || exit 1
APK_DIR="apk"
PKG_CACHE=".tvbox_pkg"   # 记录上次装进去的包名，避免误启动系统同名应用
REPO_API="https://api.github.com/repos/j4Uq/TVBoxOSC/releases/latest"
RED=$'\033[31m'; GRN=$'\033[32m'; YEL=$'\033[33m'; DIM=$'\033[2m'; RST=$'\033[0m'

say()  { printf '%s\n' "$*"; }
ok()   { printf '%s✓%s %s\n' "$GRN" "$RST" "$*"; }
warn() { printf '%s!%s %s\n' "$YEL" "$RST" "$*"; }
die()  { printf '%s✗%s %s\n' "$RED" "$RST" "$*" >&2; exit 1; }

need_adb() {
  command -v adb >/dev/null 2>&1 || die "没找到 adb。macOS 执行：brew install --cask android-platform-tools"
}

# ---------------------------------------------------------------------------
cmd_download() {
  need_adb >/dev/null 2>&1 || true
  mkdir -p "$APK_DIR"
  say "${DIM}查询最新版本…${RST}"
  local json tag url name
  json=$(curl -sSL --max-time 20 "$REPO_API") || die "访问 GitHub 失败，请检查网络"
  tag=$(printf '%s' "$json" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("tag_name",""))' 2>/dev/null)
  [ -n "$tag" ] || die "没解析到版本号，可能被限流，稍后再试"

  # 优先取通用 java 包（兼容性最好），没有就退回任意 apk
  url=$(printf '%s' "$json" | python3 -c '
import sys, json
d = json.load(sys.stdin)
assets = [a for a in d.get("assets", []) if a["name"].lower().endswith(".apk")]
def score(a):
    n = a["name"].lower()
    if n.endswith("-java.apk"):   return 0
    if "java64" in n:             return 1
    if "java32" in n:             return 2
    return 3
assets.sort(key=score)
print(assets[0]["browser_download_url"] + "\t" + assets[0]["name"] if assets else "")
')
  [ -n "$url" ] || die "该版本没有 APK 附件（只有源码），换个仓库或手动下载"
  name=$(printf '%s' "$url" | cut -f2)
  url=$(printf '%s' "$url" | cut -f1)

  say "下载 $name （${tag}）"
  curl -L --progress-bar --max-time 300 -o "$APK_DIR/$name" "$url" || die "下载失败"
  ok "已保存到 $APK_DIR/$name"
  say "${DIM}下一步：./scripts/install_tv.sh install <电视IP>${RST}"
}

# ---------------------------------------------------------------------------
cmd_scan() {
  need_adb
  say "扫描局域网内开放 5555 端口的设备（约 20 秒）…"
  local ips
  ips=$(arp -an 2>/dev/null | sed -n 's/.*(\([0-9.]*\)) at.*/\1/p' | sort -u)
  [ -n "$ips" ] || die "ARP 表为空，先确认和电视在同一 WiFi"

  local found=0
  for ip in $ips; do
    ( nc -z -G 1 -w 1 "$ip" 5555 >/dev/null 2>&1 && echo "$ip" ) &
  done > /tmp/.tvbox_scan.$$ 2>/dev/null
  wait

  while read -r ip; do
    [ -n "$ip" ] || continue
    found=1
    local model
    adb connect "$ip:5555" >/dev/null 2>&1
    model=$(adb -s "$ip:5555" shell getprop ro.product.model 2>/dev/null | tr -d '\r')
    ok "$ip:5555  ${model:-未知型号}"
  done < /tmp/.tvbox_scan.$$
  rm -f /tmp/.tvbox_scan.$$

  if [ "$found" -eq 0 ]; then
    warn "没扫到。请确认：① 电视和电脑连同一个 WiFi"
    warn "            ② 开发者选项里「网络调试/ADB调试」已打开"
    warn "            ③ 路由器没开「AP 隔离」（这个开关会阻断设备互访）"
    say  "${DIM}部分电视要先在设置里看到本机 IP，再用 install <IP> 手动连${RST}"
  fi
}

# ---------------------------------------------------------------------------
connect_dev() {
  local ip="$1"
  need_adb
  case "$ip" in *:*) ;; *) ip="$ip:5555" ;; esac
  adb connect "$ip" >/dev/null 2>&1
  sleep 1
  local state
  state=$(adb devices | awk -v d="$ip" '$1==d {print $2}')
  [ "$state" = "device" ] || die "连不上 ${ip}（状态：${state:-无}）。检查网络调试开关，或电视弹窗里点「允许」"
  echo "$ip"
}

cmd_info() {
  local dev; dev=$(connect_dev "$1") || exit 1
  printf '型号   : %s\n' "$(adb -s "$dev" shell getprop ro.product.model | tr -d '\r')"
  printf '品牌   : %s\n' "$(adb -s "$dev" shell getprop ro.product.brand | tr -d '\r')"
  printf 'Android: %s\n' "$(adb -s "$dev" shell getprop ro.build.version.release | tr -d '\r')"
  printf 'CPU    : %s\n' "$(adb -s "$dev" shell getprop ro.product.cpu.abi | tr -d '\r')"
  printf '已装TVBox: %s\n' "$(adb -s "$dev" shell pm list packages 2>/dev/null | tr -d '\r' | grep -iE 'tvbox|fengmi|影视' | tr '\n' ' ')"
}

cmd_install() {
  local ip="${1:-}" apk="${2:-}"
  [ -n "$ip" ] || die "用法：./scripts/install_tv.sh install <电视IP> [apk路径]"
  local dev; dev=$(connect_dev "$ip") || exit 1

  if [ -z "$apk" ]; then
    apk=$(ls -t "$APK_DIR"/*.apk 2>/dev/null | head -1)
    [ -n "$apk" ] || die "apk/ 里没有安装包，先跑：./scripts/install_tv.sh download"
  fi
  [ -f "$apk" ] || die "找不到文件：$apk"

  local abi
  abi=$(adb -s "$dev" shell getprop ro.product.cpu.abi | tr -d '\r')
  say "设备 ABI: $abi"

  # 装之前先记一份第三方包列表，装完比对出是哪个包
  local before after
  before=$(adb -s "$dev" shell pm list packages -3 2>/dev/null | tr -d '\r')

  say "安装 $(basename "$apk") …"
  if adb -s "$dev" install -r -g "$apk" 2>&1 | tee /tmp/.tvbox_install.$$ | grep -q Success; then
    ok "安装成功"
  else
    local msg; msg=$(cat /tmp/.tvbox_install.$$)
    rm -f /tmp/.tvbox_install.$$
    case "$msg" in
      *USER_RESTRICTED*|*INSTALL_FAILED_VERIFICATION*)
        die "电视拒绝安装。去 开发者选项 打开「USB 安装」，或在电视弹窗里点「允许」" ;;
      *INSUFFICIENT_STORAGE*)
        die "电视存储空间不足，清理后再装" ;;
      *SIGNATURE*|*UPDATE_INCOMPATIBLE*)
        die "签名冲突：先卸载旧版（adb uninstall 包名）再装" ;;
      *) die "安装失败：$msg" ;;
    esac
  fi
  rm -f /tmp/.tvbox_install.$$

  after=$(adb -s "$dev" shell pm list packages -3 2>/dev/null | tr -d '\r')
  local newpkg
  newpkg=$(comm -13 <(printf '%s\n' "$before" | sort) <(printf '%s\n' "$after" | sort) \
           | head -1 | sed 's/package://')
  if [ -n "$newpkg" ]; then
    echo "$newpkg" > "$PKG_CACHE"
    ok "新装的包名：$newpkg"
  else
    warn "没检测到新增包（可能是覆盖安装），沿用上次记录"
  fi

  cmd_launch "$dev"
}

cmd_launch() {
  local dev; dev=$(connect_dev "$1") || exit 1
  local pkg
  # 优先用装机时记录下来的包名，退而求其次按关键词找第三方应用
  if [ -f "$PKG_CACHE" ]; then
    pkg=$(cat "$PKG_CACHE")
  else
    pkg=$(adb -s "$dev" shell pm list packages -3 2>/dev/null | tr -d '\r' \
          | sed 's/package://' \
          | grep -iE 'tvbox|fongmi|\.osc' \
          | grep -viE 'duokan|airkan|xiaomi' | head -1)
  fi
  [ -n "$pkg" ] || die "没找到已安装的 TVBox，先执行 install"

  adb -s "$dev" shell monkey -p "$pkg" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1
  ok "已在电视上启动：$pkg"
  say ""
  say "${DIM}接下来在电视上操作：${RST}"
  say "  设置 → 配置地址 → 填入你的源地址（形如 https://zlu1123.github.io/tvbox-hub/index.json）"
}

# ---------------------------------------------------------------------------
case "${1:-}" in
  scan)     cmd_scan ;;
  download) cmd_download ;;
  install)  shift; cmd_install "$@" ;;
  launch)   shift; cmd_launch "$@" ;;
  info)     shift; cmd_info "$@" ;;
  *)
    sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'
    exit 1 ;;
esac
