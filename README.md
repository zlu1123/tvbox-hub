# tvbox-hub

两个源，各管一件事，都托管在 GitHub Pages 上：

| 用途 | 地址 | 填在哪 |
|---|---|---|
| 直播（看电视） | `https://zlu1123.github.io/tvbox-hub/live.json` | TVBox 的「直播源」 |
| 影视（搜电影剧集） | `https://zlu1123.github.io/tvbox-hub/vod.json` | TVBox / 影视仓 的「接口」 |
| 两个都要 | `https://zlu1123.github.io/tvbox-hub/index.json` | 只有一个配置框时填这个 |

直播源已经在跑，19 个台（CCTV 系 + 卫视）实测可播。影视源现在是空的，需要你填一个接口地址 —— 见 [影视源](#影视源搜电影剧集)。

---

## 电视上怎么填

TVBox → **设置 → 配置地址**，粘上面表格里的地址 → 确定 → 重启 App。

首页出现「直播」就是通了。想搜片还得先配好影视源。

---

## 直播源（看电视）

已经能用，不用管。想改频道才需要动 `config/sources.yaml`：

```yaml
live:
  upstreams:
    - name: iptv-org-cn
      url: "https://iptv-org.github.io/iptv/countries/cn.m3u"
```

**加自己找到的直播清单**（m3u 或「频道名,url」的 txt 都行），追加一条，加 `trust: true` 就会跳过白名单原样收录：

```yaml
    - name: my-list
      url: "https://raw.githubusercontent.com/你/xxx/main/live.m3u"
      trust: true
```

**只想多收几个台**，改 `include` 正则 + `name_map` 中英映射（文件里都有注释示例）。

改完跑一次 `./scripts/refresh.sh`。

---

## 影视源（搜电影剧集）

`config/sources.yaml` 里 `vod.sites` 现在是空的。填一个接口就行：

```yaml
vod:
  sites:
    - key: "my_vod"
      name: "影视"
      type: 4
      api: "https://你找的接口/api.php/provide/vod/"
      searchable: 1
      quickSearch: 1
      filterable: 1
      ext: ""
```

判断一个地址能不能用，最快的方法——浏览器直接打开它加 `?ac=list`：

```
https://xxx.com/api.php/provide/vod/?ac=list
```

返回里有 `"class":[{"type_id":1,"type_name":"电影"}...]` 就说明是苹果CMS接口，能直接用。返回网页、报错、或者一堆别的东西就是不行。

**我没有在仓库里预置任何影视接口**，包括肥猫那类。原因很实际，不是唱高调：

- 这类聚合接口平均寿命几个月，站点换域名、跑路、被投诉都很常见，写进配置里就是给自己埋雷
- 多数带强制广告、跳转、甚至挂马
- 电视上装的 App 会长期读这份配置，往里面塞来源不明的东西，吃亏的是你家设备

所以这一格留给你自己填，填什么由你决定。

想彻底不碰第三方的正规做法只有一个：拿台常开的电脑装 Jellyfin/Emby，把片子放进去，仓库里 `nas/emby2cms.py` 能把它包成上面这种接口（限内网用）。这方案我实测过接口格式，能用。

---

## 刷新

改完 `sources.yaml` 后：

```bash
./scripts/refresh.sh
```

它会：抓清单 → 逐条探活（用你家网络，不是服务器）→ 剔除死链 → 校验 → 提交 → 推送。约 40 秒。

- `--no-probe` 跳过探活，3 秒出结果（但死链不会被剔除）
- `--dry` 只生成不推送，先看看结果

推上去后 GitHub Actions 自动发布，1 分钟内生效。

> 国内网络下 `git push` 有时会报 `LibreSSL SSL_connect: SSL_ERROR_SYSCALL`，那是 TLS 握手被重置，不是仓库问题。`refresh.sh` 检测到就会自动改用 GitHub API 推送（`scripts/push-api.py`，走 api.github.com，通常能通）。

> 为什么探活不在 GitHub 服务器上跑：它在美国机房，判定「能用」的流你国内可能拉不动。实测过一次，它给 22 个台，其中 4 个（北京卫视、广东卫视、CCTV-5+、CCTV-6）在你这儿是死的。

---

## 目录

```
config/
├── sources.yaml   ← 唯一要编辑的文件
├── index.json     ← 生成物：直播+影视
├── live.json      ← 生成物：纯直播
├── vod.json       ← 生成物：纯影视
└── health.json    ← 生成物：探活报告，看哪个台死了
scripts/
├── refresh.sh     ← 改完配置跑这个
└── install_tv.sh  ← 装 App / 重装 / 启动电视
nas/               ← 可选，接自己媒体库时才用
docs/              ← 安装细节、配置字段
```

---

## 电视上装 App

```bash
./scripts/install_tv.sh scan                    # 找电视 IP
./scripts/install_tv.sh download                # 下最新 APK
./scripts/install_tv.sh install 192.168.31.178  # 装 + 启动
```

已经装好了（小米电视4，包名 `com.github.tvbox.osc.jun`），升级时重跑后两条即可。

报错处理见 [docs/install.md](docs/install.md)。

---

## 常常出问题的地方

**电视提示配置获取失败**
先用手机浏览器打开那个地址，能下到 JSON 就说明地址没问题，是电视网络的事。
GitHub Pages 在国内偶尔抽风，等一会儿重试，或在地址前加 `https://ghproxy.net/` 前缀。

**直播能看但点播搜不到**
`vod.sites` 是空的。填接口，见上面。

**某个台点开黑屏**
它死了。跑 `./scripts/refresh.sh` 会剔掉，或者看 `config/health.json` 里记的失败原因。

**改了配置电视没变化**
TVBox 有缓存。设置里「清空缓存」或杀掉 App 重开。
