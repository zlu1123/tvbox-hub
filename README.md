# tvbox-hub

自建的 TVBox 源仓库，托管在 GitHub Pages 上。每天自动抓取、探活、剔除死链，电视端只填一个固定地址，长期不用管。

```
电视端配置地址 → https://<用户名>.github.io/tvbox-hub/index.json
```

**先说清楚一件事**：GitHub 上托管的是「配置」，不是「片子」。这个仓库里只有台名、频道地址、站点接口地址，加起来几百 KB。视频流本身不可能放 GitHub（单文件 100MB 上限，也违反其服务条款）。

所以默认形态是**纯直播源**：19 个 CCTV / 卫视台，开箱即用。点播要另找内容来源，见 [没有 NAS，点播怎么办](#没有-nas点播怎么办)。

---

## 它解决什么问题

网上大部分 TVBox 源的问题是不受你控制：今天能用明天挂，接口带广告，站点主跑路就全废。

这个仓库把「源」变成你自己的一份代码：

| 痛点 | 这里的做法 |
|---|---|
| 源站跑路 / 换域名 | 上游在 `config/sources.yaml` 里，一行改掉 |
| 直播链接三天两头失效 | 每天 04:17 自动探活，死链自动剔除，配置版本号自增 |
| 手改 JSON 容易写错导致电视白屏 | `check.py` 做结构校验，写错 CI 直接拦下 |
| 想加自己的频道 | `trust: true` 的上游可以绕过白名单 |
| 换设备不用重配 | 地址固定，电视、盒子、手机装同一个 App 填同一个地址 |

---

## 目录

```
tvbox-hub/
├── config/
│   ├── sources.yaml     ← 你唯一需要编辑的文件
│   ├── index.json       ← 自动生成，TVBox 填这个地址
│   ├── live.json        ← 自动生成，直播部分
│   └── health.json      ← 自动生成，探活报告
├── scripts/
│   ├── build.py         # 抓取 + 探活 + 生成
│   ├── check.py         # 结构校验 + 连通性检测
│   ├── publish.sh       # 一键建仓库 + 推送 + 开 Pages
│   └── install_tv.sh    # adb 一键装到电视
├── nas/                 # 可选：以后有媒体库了再用，现在不影响
│   ├── emby2cms.py      # Emby/Jellyfin → 苹果CMS 接口转换
│   └── docker-compose.yml
├── docs/
│   ├── install.md       # 电视端安装四条路
│   └── tvbox-format.md  # 配置字段速查
└── .github/workflows/refresh.yml
```

---

## 快速开始

全程只需要一台电脑，不需要 NAS。

### 1. 本地生成 + 校验

```bash
pip install -r requirements.txt
python3 scripts/build.py      # 约 20 秒，含探活
python3 scripts/check.py      # 有 ✗ 就先别往下走
```

生成结果是 `config/index.json`，这就是电视要读的那份配置。

### 2. 一条命令发布到 GitHub

```bash
./scripts/publish.sh
```

它会把建仓库、推代码、开 Pages 全干完，最后直接打印你的配置地址。

第一次运行会：
- 如果没有 `gh`（GitHub CLI）自动用 brew 装
- 让你在浏览器里授权一次（选 GitHub.com → HTTPS → 浏览器登录）
- 自动补 `workflow` 权限，否则 Actions 推不了 Pages

跑完输出长这样：

```
────────────────────────────────────────────
配置地址（填到电视上）：
  https://<用户名>.github.io/tvbox-hub/index.json
────────────────────────────────────────────
```

<details>
<summary>不想用脚本，手动推也行</summary>

先在 GitHub 网页上建一个空仓库（**不要**勾 README / gitignore），然后：

```bash
git remote add origin git@github.com:<用户名>/tvbox-hub.git
git push -u origin main
```

再去 **Settings → Pages → Source** 选 **GitHub Actions**。

注意手动推需要你的 SSH key 已经加到 GitHub 账号里，否则会 `Permission denied (publickey)`。

</details>

### 3. 等 Actions 跑完

仓库 **Actions** 标签页里看「刷新源并发布」，绿色勾出现就说明发布了（约 1 分钟）。

访问下面地址能返回一坨 JSON 就成功了：

```
https://<用户名>.github.io/tvbox-hub/index.json
```

### 4. 装上电视

```bash
./scripts/install_tv.sh scan                  # 找电视 IP
./scripts/install_tv.sh download              # 下 APK
./scripts/install_tv.sh install 192.168.1.23  # 装 + 启动
```

细化步骤和报错处理见 [docs/install.md](docs/install.md)。

### 5. 电视上填地址

TVBox → 设置 → 配置地址 → 填 `https://<用户名>.github.io/tvbox-hub/index.json` → 确定 → 重启 App。

首页出现「直播」入口就成功了。

### 想先本地验一遍再推

在仓库根目录起个静态服务：

```bash
python3 -m http.server 8000
```

电视上配置地址填 `http://<电脑内网IP>:8000/config/index.json`（注意本地服务时多一层 `config/`）。

---

## 没有 NAS，点播怎么办

TVBox 的「直播」和「点播」是两条独立的路。直播这个仓库已经包圆了；点播需要一个能吐片源的地方。按投入排序：

### 方案 A：只要直播（零成本，现在就能用）

`config/sources.yaml` 里 `vod.sites` 保持 `[]`，电视上就只有直播板块，19 个台正常看。**这是当前仓库的默认状态。**

很够用——央视 15 个台、几个卫视，日常看新闻球赛电视剧直播已经覆盖了。

### 方案 B：拿一台常开的电脑当片库（有点折腾，但要什么有什么）

不需要买 NAS。家里有任意一台常年开机的电脑（台式机、旧笔记本、甚至树莓派）就行：

1. 装上 **Jellyfin**（免费开源）或 Emby，把硬盘上的电影剧集加进媒体库
2. 在电脑上跑本仓库的转换代理：

   ```bash
   cd nas
   # 编辑 docker-compose.yml 填 EMBY_BASE / EMBY_API_KEY
   docker compose up -d
   ```

3. `config/sources.yaml` 里放开 `vod.sites` 的示例条目，把 IP 换成那台电脑的内网 IP
4. 重新 `build.py` → push → 电视端刷新配置

代价：只能在家里看（内网地址），出门要另外做内网穿透。

### 方案 C：接一个现成的苹果CMS 接口

如果手上有自己信任的 `api.php/provide/vod/` 接口，按 `sources.yaml` 里方案 B 的格式加一条 `type: 4` 就能用。

> 我不会在仓库里预置第三方影视聚合接口。那类接口今天能看明天就挂、夹带广告、来源不明，把它写进你已经验证过的配置里，等于把整个源的稳定性押在一个随时会消失的东西上。要接什么由你决定，接口地址填在 `sources.yaml`，那是你自己的选择。

---

## 日常维护

**只做一件事：改 `config/sources.yaml`，推上去。** 剩下的 CI 会做。

| 我想… | 怎么做 |
|---|---|
| 加一个直播源 | `live.upstreams` 追加一条 URL |
| 加自己的私源（不过滤） | 同上，加 `trust: true` |
| 加地方台 | `include` 加关键词，`name_map` 加中英映射 |
| 加片源站 | `vod.sites` 追加一个 `type: 4` 条目 |
| 只想本地快速看效果 | `python3 scripts/build.py --no-probe` |
| 立刻刷新一次线上 | GitHub 仓库 → Actions → 刷新源并发布 → Run workflow |

### 加一个直播频道的完整例子

假设上游清单里有 `Zhejiang Children's Channel`，你想收进来：

```yaml
include:
  - "^CCTV-\\d+"
  - "卫视"
  - "浙江少儿"          # ← 加这行

name_map:
  "Zhejiang Children's Channel": "浙江少儿"   # ← 和这行
```

`name_map` 是必须的：上游用英文台名，不映射的话中文关键词永远匹配不上。

---

## 可用率是多少

免费公开源本来就不稳定。实测（2026-11-07，中国大陆家宽）：

- 抓到 156 条 → 白名单命中 44 条 → 探活存活 **19 条**（约 45%）
- CCTV 系 15 个台基本稳定，卫视波动大

这就是为什么要有每日探活——**单次成功率不重要，长期有 19 个能看的才重要**。如果嫌卫视太少，最实际的办法是接自己运营商的 IPTV 清单（`trust: true`）。

> **一个要知道的偏差**：GitHub Actions 跑在境外机房，探活视角和你家宽带不一样。有些只对大陆开放的流，CI 会判死并剔除，所以线上配置可能比你本地跑出来的少几个台。
> 想让结果贴合你家网络：本地跑 `python3 scripts/build.py` 后手动 push，或在 Actions 里先禁用定时任务（`refresh.yml` 注释掉 `schedule`）。

---

## 已验证环境

| 项目 | 实测结果 |
|---|---|
| 电视 | 小米电视4（MiTV4-ANSM0），Android 6.0.1，armeabi-v7a |
| APK | `TVBox_q215613905_20260914-1520-java.apk`（32 MB，通用包） |
| 安装 | `adb install -r -g` 一次通过，无 USER_RESTRICTED |
| 包名 | `com.github.tvbox.osc.jun` |
| 运行 | HomeActivity 正常前台，未崩溃 |

> 小米电视上有个坑：系统自带 `com.duokan.airkan.tvbox`（投屏应用），名字里带 tvbox。
> 启动脚本靠装机前后比对包列表来定位真实包名，不会误启动它。

---

## 声明

仓库里只放**框架和公开清单的加工逻辑**，不内置任何影视资源。

- 默认不包含任何点播站点，只有直播
- 直播用的是公开发布的频道清单，各条流的版权与可用性由来源方负责
- 加什么点播接口由你自己决定并自行承担相应责任
- 请不要用这个仓库分发没有授权的影视内容
