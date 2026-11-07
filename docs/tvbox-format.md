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
  "type": 4,
  "api": "http://.../api.php/provide/vod/",
  "searchable": 1,
  "quickSearch": 1,
  "filterable": 1,
  "ext": ""
}
```

`type` 的取值决定 `api` 填什么：

| type | 含义 | api 填什么 |
|---|---|---|
| 0 | 纯 jar 扩展 | 通常是 `csp_XXX`，依赖顶层 `spider` 指向的 jar |
| 1 | XML 源 | 一个 xml 地址 |
| 3 | 带自定义类的 jar | `csp_XXX` + `ext` 传参 |
| 4 | **标准接口** | 苹果CMS v10 的 `api.php/provide/vod/` 地址 |

> 本项目只用 `type: 4`，因为它是唯一不依赖第三方 jar 的类型——jar 一旦停更，整站全废；接口地址只依赖对方服务器。

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
