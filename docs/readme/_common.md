## 电视上怎么填

TVBox → **设置 → 配置地址**，粘上面表格里的地址 → 确定 → 重启 App。

首页出现「直播」就是通了。影视源也已经配好，搜索框直接搜片名就行。

---

## 直播源（看电视）

已经能用，不用管。想改频道才需要动 `config/sources.yaml`。里面按优先级排了 4 个上游：移动CDN央视 → Guovin测速源 → iptv-org → myiptv 补充。

**加自己找到的直播清单**（m3u 或「频道名,url」的 txt 都行），追加一条，加 `trust: true` 就会跳过所有筛选原样收录：

```yaml
    - name: my-list
      url: "https://raw.githubusercontent.com/你/xxx/main/live.m3u"
      trust: true
```

每个上游可以单独设 `groups`（分组白名单）、`include`（台名白名单）、`exclude`、`only_mapped`、`max_lines`（每台的线路上限）。文件里都有注释示例。

改完跑一次 `./scripts/refresh.sh`。

### 为什么只有 38 个台 / 广告是怎么清掉的

原来那份有 52 个台，其中十几个点开是广告。查下来不是「源没维护好」，是撞上了**广告农场**：

- 一批境外主机（`74.91.26.218`、`63.141.230.178`、`38.75.136.137`、`107.150.60.122` 等）把几十个台名全指向同一个跳转池 `:88/applive/…`（`mkt.m3u8` = 广告位，`yss/` = 一条共用流）。
- **同一个 URL 两次请求会分别拿到真流和广告流**，所以「测一次能播就留下」根本拦不住。

现在的处理分三层，都写死在 `build.py` / `sources.yaml` 里：

1. **按主机名整批拉黑**已确认的农场 IP（排除规则同时匹配台名和 URL）。
2. **探活时跟随 302**，只要落到 `/applive/`、`mkt.m3u8` 这类路径就判死。
3. **假台同源检测**：给每路流算分片路径指纹，同一个指纹被 ≥2 个台名共用就整批剔除。

代价是数字从 52 掉到 30~40（免费流每次探活会抖，实测在 34~38 之间浮动），但剩下的没有一个是广告。**央视 3/5/7/10/11/12/13/16/17 这几个台是客观缺口**：能播的线路全在农场里，干净线路在你家（陕西联通）宽带下不可达，换任何公开源都绕不开。

> 顺带核实过几个知名维护源：fanmingming/live 的央视走移动CDN，在联通宽带下 302→403；YueChan/Live 是 rtp:// 组播，家用网络用不了；vbskycn 主攻地方台。所以正确做法不是换源，是清洗。

---

## 影视源（搜电影剧集）

已经配好了。`config/sources.yaml` 的 `vod.sites` 里放了 6 个苹果CMS V10 采集接口，实测片库 7.4 万 ~ 17.1 万条，电影 / 剧集 / 综艺 / 动漫都能搜。

和「肥猫」那类配置的区别值得说清楚：

| | 肥猫 / 多仓配置 | 这份配置 |
|---|---|---|
| 数据源 | 一堆 `spider` jar、drpy js，运行时从远端下载代码 | 只有 `type: 1` 的纯 JSON 接口，`spider` 为空 |
| 风险 | 远端 jar 随时可换内容，等于把电视交给别人 | 电视只拉 JSON 和 m3u8，没有可执行代码 |
| 维护 | 别人停更就全废 | 每次 `refresh.sh` 逐个实测，挂了自动剔除 |

**搜索是聚合的**：`quickSearch: 1` 的站点会一起参与首页全局搜索，一个源没有的片别的源可能搜到。魔都资源实测要 8 秒以上，单独关掉了快捷搜索，免得拖慢聚合。

### 为什么接口地址末尾有 `/from/xxx/`

苹果CMS 默认会把「网页解析线路」和「m3u8 直链」一起返回。网页线路形如 `https://…/share/xxxx`，要跳转、常插广告，还经常排在列表第一条。`/from/<播放源名>/` 让接口只返回指定那一种线路 —— 实测六个站加了之后全部只给纯 m3u8 直链，`parses` 因此可以保持为空。

### 自动维护：接口死了不用你管

`vod.sites` 是**候选池**，不是最终清单。每次构建逐个做三项实测：

1. `?ac=list&pg=1` 返回非空列表（顺带记录片库总量、分类数）
2. `?ac=detail&ids=…` 拿得到 `vod_play_url`，且是 m3u8 直链
3. `?ac=list&wd=流浪地球` 搜得到结果

三项全过才写进 `index.json`；挂掉的自动从电视配置里剔除，下次构建恢复了会自动回来。免费站抖动大，失败会重测一次再判死。报告在 `config/vod-health.json`，体检会打印每个源的片库量和响应耗时。

### 想加自己的接口

照抄 `sources.yaml` 里的注释段落，改 `api` 就行。几个要点：

- **`type` 必须是 1**（JSON 接口）。`type: 0` 是老式 XML 接口，api 得带 `/at/xml/`；`type: 3` 需要 jar，别碰。实测公开配置里 231 个 `provide/vod` 站点用 `type: 1`。
- 判断接口能不能用：浏览器打开 `api + "?ac=list"`，返回里要有 `"class"` 和 `"list"`。
- 下划线开头的字段（比如 `_note`）只是备注，不会写进电视配置。
- 想换搜索测试词，改 `vod.probe.keyword`。

### 证书这点不用太担心

电视是 Android 6，系统证书库里没有 Let's Encrypt 的 ISRG 根，**配置地址**因此必须走它认得的证书链（所以才用 Gitee raw）。反编译电视上那个 APK 能看到 `checkServerTrusted`、`sslSocketFactory`、`makeSSLSocketFactory` 这类自定义 SSL 工厂，说明 App 拉接口和播放流走的是另一套网络栈，未必受系统证书库限制 —— 但这是推断，不保证每个源都通（这台电视当时不在线，没能直接实测）。

所以排在最前的两个源特意选了「http 接口 + Certum 播放域名」组合，完全不吃证书兼容性。万一某个源点开报网络错误，切成前两个即可；`vod-health.json` 里也记着每个源的播放域名，方便对照排查。

### 风险提示

这些是公开网络上的第三方采集站。仓库**不预置任何 `spider` jar**，但内容由对方提供，可能随时换域名、下线，也可能夹带推广位（实测六个站的首页片名和分类都没发现）。接口格式是标准的，仓库只做「验证 + 剔除」，不缓存也不转存任何影片。请按所在地法规使用。

想彻底不碰第三方的正规做法：拿台常开的电脑装 Jellyfin/Emby，`nas/emby2cms.py` 能把它包成同样的苹果CMS接口（限内网用），实测过格式可用 —— 你没有 NAS，所以现在用的是公开接口方案。

---

## 刷新

改完 `sources.yaml` 后：

```bash
./scripts/refresh.sh
```

它会：生成两份 README → 抓清单 → 逐条探活（用你家网络，不是服务器）→ 剔除死链和失效影视接口 → 校验 → 提交 → **同时推送 GitHub 和 Gitee**。直播探活要拉真实视频分片，约 2 分钟。

- `--no-probe` 跳过探活，3 秒出结果（但死链不会被剔除）
- `--dry` 只生成不推送，先看看结果

> 国内网络下 `git push` 有时会报 `LibreSSL SSL_connect: SSL_ERROR_SYSCALL`，那是 TLS 握手被重置，不是仓库问题。`refresh.sh` 检测到就会自动改用 GitHub API 推送（`scripts/push-api.py`，走 api.github.com，通常能通）。

> 为什么探活不在 CI 服务器上跑：它在境外机房，判定「能用」的流你国内可能拉不动。实测过一次，它给 22 个台，其中 4 个（北京卫视、广东卫视、CCTV-5+、CCTV-6）在你这儿是死的。

---

## 目录

```
config/
├── sources.yaml   ← 唯一要编辑的文件
├── index.json     ← 生成物：直播+影视（接口框）
├── live.json      ← 生成物：纯直播 JSON
├── live.txt       ← 生成物：纯直播 TXT（直播源框）
├── live.m3u       ← 生成物：纯直播 M3U（直播源框）
├── vod.json       ← 生成物：纯影视
├── health.json    ← 生成物：直播探活报告，看哪个台死了
└── vod-health.json← 生成物：影视站探活报告，看哪个接口挂了
docs/readme/       ← README 源文件（公共正文 + 两个平台头部）
├── _common.md
├── github.md
└── gitee.md
scripts/
├── refresh.sh     ← 改完配置跑这个（自动双推）
├── gen-readme.sh  ← 拼装两份 README
├── build.py       ← 抓清单 / 探活 / 生成
├── check.py       ← 配置体检
├── push-gitee.sh  ← Gitee 镜像推送 + raw 自检
├── push-api.py    ← github.com 被阻断时用 API 推送兜底
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
先用手机浏览器打开那个地址，能下到 JSON 就说明地址没问题，是电视网络的事。如果地址是 `gitee.com/.../raw/...`，还要确认仓库是**公开**的（私有仓库匿名访问会 403）。

**直播能看但点播搜不到**
先看 `config/vod-health.json`：多半是接口全被判死了，跑一次 `./scripts/refresh.sh` 重测（恢复了会自动回来）；还是不行就按上面「想加自己的接口」换一个。TVBox 有缓存，先在设置里清空缓存再试。

**某个台点开黑屏**
它死了。跑 `./scripts/refresh.sh` 会剔掉，或者看 `config/health.json` 里记的失败原因。

**改了配置电视没变化**
TVBox 有缓存。设置里「清空缓存」或杀掉 App 重开。
如果用的是 jsDelivr `@main` 地址，它还有最长 12 小时的分支解析缓存（purge 清不掉）——换成 Gitee raw 地址就没这问题，或用 commit 固定的 jsDelivr 地址立刻生效。

---

## 为什么地址挑来挑去

不是随便挑的，是查出来的。

你这台小米电视4 是 **Android 6.0.1**，系统信任库只有 158 个根证书。查过：

```
ISRG Root X1（Let's Encrypt）        ✗ 不在   ← github.io 失败的原因
DigiCert Global Root CA              ✓ 在
Baltimore CyberTrust Root            ✓ 在
GlobalSign Root CA - R3              ✓ 在   ← jsDelivr 能通
Certum Trusted Network CA            ✓ 在   ← Gitee 能通
```

| 地址 | 证书链 | 电视 | 缓存 |
|---|---|---|---|
| `zlu1123.github.io` | → ISRG Root X1 | ✗ 加载失败 | — |
| `cdn.jsdelivr.net/gh/…@main` | → GlobalSign Root R3 | ✓ | ✗ 最长 12 小时，purge 清不掉 |
| `cdn.jsdelivr.net/gh/…@<sha>` | → GlobalSign Root R3 | ✓ | ✓ 无，但要手改 SHA |
| **`gitee.com/…/raw/main`** | → Certum Trusted Network CA | ✓ | ✓ **无** |

其他同一问题下的废案，实测都走 ISRG 链，一样不通：`raw.githubusercontent.com`。`statically.io` 在你家网络直接连不上。
