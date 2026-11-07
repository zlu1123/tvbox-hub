# tvbox-hub

自建的 TVBox 源仓库。每天自动抓取、探活、剔除死链、发布到 GitHub Pages，电视端只填一个固定地址，长期不用管。

```
电视端配置地址 → https://<用户名>.github.io/tvbox-hub/config/index.json
```

点播内容来自你自己的 NAS（Emby / Jellyfin），不走第三方聚合站；直播来自公开 M3U 清单 + 你自己维护的源。

---

## 它解决什么问题

网上大部分 TVBox 源的问题是不受你控制：今天能用明天挂，接口带广告，站点主跑路就全废。

这个仓库把「源」变成你自己的一份代码：

| 痛点 | 这里的做法 |
|---|---|
| 源站跑路 / 换域名 | 上游在 `config/sources.yaml` 里，一行改掉 |
| 直播链接三天两头失效 | 每天 04:17 自动探活，死链自动剔除，配置版本号自增 |
| 点播站带广告、有风险 | 只用你自己 NAS 的媒体库 |
| 手改 JSON 容易写错导致电视白屏 | `check.py` 做结构校验，写错 CI 直接拦下 |
| 想加自己的频道 | `trust: true` 的上游可以绕过白名单 |

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
│   └── install_tv.sh    # adb 一键装到电视
├── nas/
│   ├── emby2cms.py      # Emby/Jellyfin → 苹果CMS 接口转换
│   └── docker-compose.yml
├── docs/
│   ├── install.md       # 电视端安装四条路
│   └── tvbox-format.md  # 配置字段速查
└── .github/workflows/refresh.yml
```

---

## 快速开始

### 1. 部署 NAS 转换代理

Emby 后台拿 API Key（设置 → 高级 → API 密钥），然后：

```bash
cd nas
# 编辑 docker-compose.yml，填 EMBY_BASE 和 EMBY_API_KEY
docker compose up -d
curl http://<NAS的IP>:8000/          # 看到 {"ok": true, ...} 就通了
```

### 2. 填进源配置

编辑 `config/sources.yaml`，把 `vod.sites[0].api` 里的 IP 换成你 NAS 的：

```yaml
api: "http://192.168.1.10:8000/api.php/provide/vod/"
```

### 3. 本地生成 + 校验

```bash
pip install -r requirements.txt
python3 scripts/build.py      # 约 20 秒，含探活
python3 scripts/check.py      # 全绿再往下走
```

### 4. 推到 GitHub

```bash
git add -A && git commit -m "init: tvbox 源"
git branch -M main
git remote add origin git@github.com:<用户名>/tvbox-hub.git
git push -u origin main
```

然后到仓库 **Settings → Pages**，把 Source 设成 **GitHub Actions**。

### 5. 装上电视

```bash
./scripts/install_tv.sh download
./scripts/install_tv.sh install 192.168.1.23
```

细化步骤和报错处理见 [docs/install.md](docs/install.md)。

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

---

## 声明

仓库里只放**框架和公开清单的加工逻辑**，不内置任何影视资源。

- 点播走你自己的 NAS 媒体库，内容是你自己的
- 直播用的是公开发布的频道清单，各条流的版权与可用性由来源方负责
- 请不要用这个仓库分发没有授权的影视内容
