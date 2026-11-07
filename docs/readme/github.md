# tvbox-hub

> 这是 **GitHub 主仓库**。Gitee 上有一份自动同步的镜像：<https://gitee.com/zlu1123/tvbox-hub>。
> 两个平台各自维护一份 README（见 [README 维护](#readme-维护)），但配置由一条命令统一生成、提交、双推。

两个源，各管一件事。**电视上优先用 Gitee raw 地址**（推完立刻生效），jsDelivr 作备用。

| 填在哪 | 用哪个地址 | 说明 |
|---|---|---|
| **接口 / 配置地址**（要 JSON 的框） | `https://gitee.com/zlu1123/tvbox-hub/raw/main/config/index.json` | 首选，直播+影视合一 |
| **直播源**（提示「支持 txt、m3u」的框） | `https://gitee.com/zlu1123/tvbox-hub/raw/main/config/live.txt` | 30~40 个台 |
| 同上，m3u 格式 | `https://gitee.com/zlu1123/tvbox-hub/raw/main/config/live.m3u` | 二选一 |
| 纯影视（可选） | `https://gitee.com/zlu1123/tvbox-hub/raw/main/config/vod.json` | 6 个接口，能搜片 |

> ⚠️ 别把 `index.json` 填进「直播源」框——那个框只认 txt / m3u，填 JSON 会提示「支持 txt、支持 m3u」并加载失败。反过来，`live.txt` 也别填进「接口」框。

直播源是 **30~40 个实测可播、零广告**的频道（央视 + 卫视 + 地方台；免费流每次探活会抖，以 `health.json` 为准）。影视源已经配好 6 个苹果CMS 接口，搜索框直接搜片名 —— 见 [影视源](#影视源搜电影剧集)。

GitHub 备用地址：把域名路径换成 `https://cdn.jsdelivr.net/gh/zlu1123/tvbox-hub@main/config/…` 即可。但 jsDelivr 对 `@main` 有最长 **12 小时**解析缓存，改完配置不会立刻生效；想立刻生效用 `@<commit-sha>` 固定版本。

> 原始地址 `https://zlu1123.github.io/tvbox-hub/index.json` 也能用，但**只在 Android 7.1 以上的设备**。你这台小米电视是 Android 6.0.1，认不出 github.io 现在用的证书，会直接报「加载失败」。

---

## Gitee 镜像

**为什么要它**：jsDelivr 会把 `@main` 的「分支 → commit」解析缓存最长 12 小时，`purge.jsdelivr.net` 只能清文件缓存、清不掉这层（实测过，三个节点都不变）。Gitee raw 没有这层缓存，推完立刻生效，国内也快。

**证书也兼容**：`gitee.com` → `raw.giteeusercontent.com` 的链是
`TrustAsia DV TLS RSA CA 2024 → TrustAsia TLS RSA Root CA → Certum Trusted Network CA`，
最后一个根在你电视的 158 个证书里是有的（`ISRG Root X1` 没有，这才是 github.io 失败的原因）。raw 地址匿名可访问，会自动 302 到带签名的 CDN，不需要电视登录。

### 一次性授权（维护者做，网页上操作）

1. <https://gitee.com/profile/sshkeys> 添加本机公钥：

   ```
   ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIB171zlISrS+dxVRdncRAbKwV9YbLro7hBEfZtKP+Qor lukelzhang@lukedeMacBook-Pro.local
   ```

2. 在 Gitee 新建仓库 `tvbox-hub`，**不要**勾选「使用 Readme 文件初始化这个仓库」，并且**必须设为公开**——私有仓库的 raw 匿名访问会 403，电视上就是「加载失败」。设置页：<https://gitee.com/zlu1123/tvbox-hub/settings>。新账号可能要先实名认证，公开后可能有审核时间。

3. 验证：

   ```bash
   ./scripts/push-gitee.sh --test    # 应显示 "Hi zlu1123! You've successfully authenticated"
   ./scripts/push-gitee.sh --check  # 模拟电视匿名拉 index.json，返回 200 才算通
   ```

`--check` 是判断能不能用的唯一标准：**SSH 推送成功 ≠ 电视能读**，两者权限是分开的。

> 本机 `~/.ssh/config` 的 `Host *` 写死了 `IdentityFile ~/.ssh/id_rsa`，会把 Gitee 上登记的 `id_ed25519` 挤掉（默认连接报 Permission denied）。脚本已显式 `ssh -i ~/.ssh/id_ed25519`，不改全局配置。

### Gitee 还没公开时的临时地址

用 commit 固定的 jsDelivr 地址（分支解析缓存对 `@<commit-sha>` 无效，推完立刻生效）：

```bash
SHA=$(git rev-parse HEAD)
echo "https://cdn.jsdelivr.net/gh/zlu1123/tvbox-hub@${SHA}/config/live.txt"
echo "https://cdn.jsdelivr.net/gh/zlu1123/tvbox-hub@${SHA}/config/index.json"
```

缺点是每次更新都得换一串 SHA，所以 Gitee 配好之后就别用这个了。

---

## README 维护

两个平台看到的 README **不一样**，但公共正文只维护一处：

```
docs/readme/
├── _common.md   ← 公共正文（电视怎么填 / 频道 / 影视源 / 刷新 / 排错 / 证书原理）
├── github.md    ← GitHub 头部：主仓库说明 + 地址表 + 镜像授权章节
└── gitee.md     ← Gitee 头部：镜像说明 + Gitee 地址表
```

`./scripts/gen-readme.sh` 把 `头部 + _common.md` 拼成两份：

| 产物 | 去向 |
|---|---|
| `README.md`（仓库根目录） | 随常规提交推到 **GitHub** |
| `.build/README.gitee.md` | 推送时由 `push-gitee.sh` 注入 **Gitee** 的 `README.md` |

因为两边 `README.md` 内容不同，Gitee 的 `main` 与 GitHub 的 `main` 必然分叉，`push-gitee.sh` 每次会基于 Gitee 远端 HEAD 构造一个只替换 README 的提交（保持 fast-forward）。**不要手动 `git push gitee main`**，统一走 `./scripts/refresh.sh` 或 `./scripts/push-gitee.sh`。

改公共内容只动 `_common.md`；改平台专属内容动对应的 `github.md` / `gitee.md`。改完跑一次 `./scripts/refresh.sh` 即可两边同步。

---
