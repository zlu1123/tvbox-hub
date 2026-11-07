# tvbox-hub（Gitee 镜像）

> 本仓库是 <https://github.com/zlu1123/tvbox-hub> 的**自动同步镜像**，供国内电视直连读取配置。
> 内容与主仓库的 `config/` 完全一致，只是这份 README 面向 Gitee 访问者单独维护。

两个源，各管一件事。**电视上直接用下面的 Gitee raw 地址**，推完立刻生效，不用等 CDN 缓存。

| 填在哪 | 用哪个地址 | 说明 |
|---|---|---|
| **接口 / 配置地址**（要 JSON 的框） | `https://gitee.com/zlu1123/tvbox-hub/raw/main/config/index.json` | 直播+影视合一 |
| **直播源**（提示「支持 txt、m3u」的框） | `https://gitee.com/zlu1123/tvbox-hub/raw/main/config/live.txt` | 30~40 个台 |
| 同上，m3u 格式 | `https://gitee.com/zlu1123/tvbox-hub/raw/main/config/live.m3u` | 二选一 |
| 纯影视（可选） | `https://gitee.com/zlu1123/tvbox-hub/raw/main/config/vod.json` | 6 个接口，能搜片 |

> ⚠️ 别把 `index.json` 填进「直播源」框——那个框只认 txt / m3u，填 JSON 会提示「支持 txt、支持 m3u」并加载失败。反过来，`live.txt` 也别填进「接口」框。

直播源是 **30~40 个实测可播、零广告**的频道（免费流每次探活会抖，以 `health.json` 为准）。影视源已经配好 6 个苹果CMS 接口，搜索框直接搜片名 —— 见 [影视源](#影视源搜电影剧集)。

---

## 为什么电视用 Gitee 而不是 GitHub Pages

你这台小米电视4 是 **Android 6.0.1**，系统信任库只有 158 个根证书，其中**没有** `ISRG Root X1`（Let's Encrypt），所以 `*.github.io` 的证书握手必然失败，表现就是「加载失败」。

Gitee 这条链能通：`gitee.com` → `raw.giteeusercontent.com` →
`TrustAsia DV TLS RSA CA 2024 → TrustAsia TLS RSA Root CA → Certum Trusted Network CA`，
最后那个根在电视证书库里是有的。raw 地址匿名可访问（自动 302 到带签名的 CDN，**不需要登录**），而且**没有 jsDelivr 那种最长 12 小时的分支解析缓存**，改完配置推上来立刻生效。

> 前提是仓库必须**公开**。私有仓库的 raw 匿名访问会返回 403，电视上一样加载失败。
> 自检命令：`./scripts/push-gitee.sh --check`（模拟电视不登录拉取 `index.json`）。

---

## 这个镜像是怎么来的

维护者在本地跑一条 `./scripts/refresh.sh`，它会：

1. 用自家宽带探活（境外 CI 判定的「能播」在国内常常播不了）
2. 生成 `config/` 下所有配置
3. 拼装两份 README（GitHub 版 / Gitee 版）
4. 一次提交推到 GitHub，`push-gitee.sh` 再把 Gitee 版 README 注入镜像仓库

所以**不要直接在这个仓库里改文件**——下次同步会被覆盖。要改内容请去 GitHub 主仓库改 `config/sources.yaml` 或 `docs/readme/`。

两个平台的 README 源文件在 `docs/readme/`：`_common.md` 是公共正文，`github.md` / `gitee.md` 是各自的头部与地址表。公共内容只维护一份，平台差异各自维护。

---
