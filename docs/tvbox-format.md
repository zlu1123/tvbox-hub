# TVBox 配置格式速查

改源的时候对着这张表看，比翻源码快。

## 顶层结构

```json
{
  "name": "源的名字",
  "version": "1.0.0",
  "spider": "",          // jar 包地址，格式："https://x/spider.jar;md5;abc123"
  "wallpaper": "",       // 首页背景图
  "sites": [ ... ],      // 点播站点
  "lives": [ ... ],      // 直播频道
  "parses": [ ... ],     // 网页解析器
  "flags": [ ... ],
  "ijk": [ ... ],        // 播放器解码参数
  "doh": [ ... ]         // DNS over HTTPS
}
```

## sites（点播站点）

```json
{
  "key": "唯一ID",
  "name": "显示名",
  "type": 1,
  "api": "http://.../api.php/provide/vod/from/ffm3u8/",
  "searchable": 1,
  "quickSearch": 1,
  "filterable": 1,
  "ext": ""
}
```

`type` 的取值决定 `api` 填什么：

| type | 含义 | api 填什么 |
|---|---|---|
| 0 | XML 源 | 苹果CMS 的 `api.php/provide/vod/at/xml/` 地址 |
| 1 | **JSON 源（苹果CMS v10）** | `api.php/provide/vod/`，**不带** `at/xml` |
| 3 | jar 扩展（CSP） | `csp_XXX` + `ext` 传参，依赖顶层 `spider` 指向的 jar |
| 4 | 部分分支的扩展类型 | 本项目不用 |

> 本项目只用 **`type: 1`**。查过公开 TVBox 配置里 231 个 `provide/vod` 站点用 `type: 1`、12 个用 `type: 0`（都带 `at/xml`），`type: 4` 在 TVBox 语境下查无实据 —— 早期文档这里写错过，已修正。
>
> 不碰 `type: 3`：它要在电视上从远端下载 jar 并执行，jar 一旦停更整站全废，而且等于把设备交给别人。纯 JSON 接口只依赖对方服务器返回数据，`spider` 可以一直留空。

`api` 末尾建议加 `/from/<播放源名>/`（播放源名从 `?ac=detail` 返回的 `vod_play_from` 里取 m3u8 那个）。不加的话接口会把网页解析线路（`/share/…`，要跳转、常插广告）和 m3u8 直链一起返回，电视上第一条往往打不开；加了以后只返回指定线路，实测六个采集站全部给纯 m3u8 直链。

三个开关：
- `searchable` — 是否允许搜索
- `quickSearch` — 是否参与首页快捷搜索（站点多的话关掉能快很多）
- `filterable` — 是否启用分类筛选

## 苹果CMS v10 接口约定（本项目的转换目标）

TVBox 会调这几个 URL：

```
?ac=list                 → 返回分类
?ac=list&t=1&pg=1        → 某分类第 1 页
?ac=list&wd=关键词       → 搜索
?ac=detail&ids=1,2,3     → 详情 + 播放列表
```

`ac=list` 的返回：

```json
{"code":1,"page":1,"pagecount":10,"limit":"20","total":97,
 "list":[{"vod_id":1,"vod_name":"片名","vod_pic":"...","vod_remarks":"HD"}]}
```

`ac=list` 不带 `t` 时返回分类：

```json
{"code":1,"class":[{"type_id":1,"type_name":"电影"}]}
```

`ac=detail` 的返回，关键在 `vod_play_url`：

```json
{"code":1,"list":[{
  "vod_id":1,"vod_name":"片名","type_id":1,"type_name":"电影",
  "vod_play_from":"emby",
  "vod_play_url":"第01集$http://...#第02集$http://..."
}]}
```

`vod_play_url` 的格式是 `集名$地址`，多集用 `#` 分隔。这个字段写错，TVBox 就会显示「暂无播放源」。

## lives（直播）

两种写法，本项目用第一种（内嵌，少一次请求）：

```json
// 1. 内嵌分组
{"group": "央视", "channels": [
  {"name": "CCTV-1", "urls": ["http://a.m3u8", "http://b.m3u8"], "logo": ""}
]}

// 2. 外链 m3u/txt
{"group": "央视", "url": "https://x.com/live.m3u"}
```

`urls` 是**多线路**：第一个拉不动时播放器会自动换下一个，所以同一频道多塞几条更稳。

## flags

决定播放器面对某个播放地址时用哪套解析逻辑。常用值：

```
youku qq iqiyi qiyi letv sohu tudou pptv mgtv wasu bilibili
```

## doh

运营商 DNS 污染会让部分源打不开，配一组 DoH 能绕过：

```json
{"name": "AliDNS", "url": "https://dns.alidns.com/dns-query", "ips": ["223.5.5.5"]}
```
