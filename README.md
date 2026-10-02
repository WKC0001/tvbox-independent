# WKC independent FM configuration

独立制作的 FM影视 5.6.8 TV/手机测试版。5 个原生 CMS 接口，59 个直播频道。

聚合地址：https://cdn.jsdelivr.net/npm/wkc0001-tvbox-independent@latest/api.json

直播来源：https://github.com/iptv-org/iptv 。点播接口从用户提供的配置候选中筛选。
运行时不加载其他项目的配置、JAR、JS 或播放列表。内容 API 和媒体服务器仍为第三方。
点播列表、搜索、详情和 M3U8 线路过滤检查通过；点播媒体播放未验证。
直播 HLS/子播放列表或媒体片段响应检查通过，尚未进行真实 APP 首帧测试。
独立于 source-monitor 和 wkc0001-tvbox，不设置轮询或定时更新。
