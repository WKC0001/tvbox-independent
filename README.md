# WKC 独立聚合源 0.2.0：内容、排序与维护说明

本版独立于 source-monitor 和 wkc0001-tvbox 原包。仅发布到 WKC0001/tvbox-independent 与 wkc0001-tvbox-independent，原仓库、原包不修改。

## 导入

本次测试建议导入固定版：https://cdn.jsdelivr.net/npm/wkc0001-tvbox-independent@0.2.0/api.json

长期入口：https://cdn.jsdelivr.net/npm/wkc0001-tvbox-independent@latest/api.json

在 FM影视 TV/手机 5.6.8 的配置地址处导入，选择“首页｜精选片单”。配置的第一个站点是独立首页；已有设置记住其他站点时，手动切换一次。刷新配置后再测试，避免 APP 保留旧内容。

## 原地址实际存储内容

本次通过 GitHub Actions 读取原线上 latest/api.json，实际是 55 个站点、4 个直播入口。完整名称、类型和接口见文末及 original-source-audit.json。type=1 是原生 CMS；type=3 依赖采集适配器，包含网盘、动漫、音乐、教育、体育、工具等，不能将全部 55 项计算成独立影视提供方。

原直播入口为：每日聚合、虎牙一起看、斗鱼一起看、YY轮播。它们是配置或列表地址，不代表独立的电视台数量。

新包不引用原配置、原聚合播放列表、饭太硬 JAR、他人的 JS 配置作为运行时依赖。独立首页代码与直播快照由本包提供。影视内容接口、海报服务器、媒体服务器仍属于第三方，本项目没有自建影视内容库，不能保证它们永久在线。

## 点播与首页

18 个点播入口，17 个提供方，加 1 个“首页｜精选片单”。从上个独立测试版的 5 个点播入口扩充。相同电影天堂域名的两种 API 路径已合并；非凡另一个域名保留为备用，不计算成新的提供方。

首页展示海报及电视剧、电影、综艺、动漫、纪录片、短剧六类。海报来自内容 API；分类、页面布局由 FM APP 渲染，未修改 APK。内容取上游近期更新列表，并非豆瓣评分榜或编辑人工推荐榜。

首页每次最多并行访问 3 家接口，每页最多 48 项，按站点优先级交错展示，避免某家独占第一页。去重使用片名（Unicode规范化、空白和常见标点处理）+年份，不删除季数与续作数字。总分类优先映射上游父分类，不把电影总类和动作、喜剧等子类重复轮询。不同季、年份、翻译名与未知年份的片目仍可能存在语义重复，需要实际使用反馈完善，不能仅凭相似片名强制合并。

接口失败进入 60 秒冷却，先换可用接口；首批 3 家均失败时尝试后一批。正常列表缓存 2 分钟，全部请求失败时使用当前进程缓存。每项保留来源身份，详情回到原接口，播放只保留直链线路。没有擅自对 APP 增加“播放失败自动跨站替换影片”的承诺；用户仍可使用换源功能。

排序优先依据媒体样本检查结果，其次是分类覆盖，再考虑接口响应与常用站顺序；同家备用统一后置。媒体抽样通过不代表所有片目可播，未通过抽样但接口检查通过的入口明确标注“待实播”。响应时间来自 GitHub Actions，不代表国内每个用户的速度，后续应由国内设备测试修正。

| 顺序 | 点播源 | 本次检查 | 分类覆盖 |
| --- | --- | --- | --- |
| 1 | 光速 | 媒体样本通过 | 电视剧、电影、综艺、动漫、纪录片、短剧 |
| 2 | 暴風 | 媒体样本通过 | 电视剧、电影、综艺、动漫、纪录片、短剧 |
| 3 | 360 | 媒体样本通过 | 电视剧、电影、综艺、动漫、纪录片、短剧 |
| 4 | 滴滴 | 媒体样本通过 | 电影、动漫 |
| 5 | 玉兔 | 媒体样本通过 | 电影、动漫 |
| 6 | 乐播 | 媒体样本通过 | 动漫 |
| 7 | 辣椒 | 媒体样本通过 | 动漫 |
| 8 | 电影天堂 | 接口通过，待APP实播 | 电视剧、电影、综艺、动漫、纪录片、短剧 |
| 9 | 量子 | 接口通过，待APP实播 | 电视剧、电影、综艺、动漫、纪录片、短剧 |
| 10 | 非凡 | 接口通过，待APP实播 | 电视剧、电影、综艺、动漫、纪录片、短剧 |
| 11 | 新浪 | 接口通过，待APP实播 | 电视剧、电影、综艺、动漫、纪录片、短剧 |
| 12 | 无尽 | 接口通过，待APP实播 | 电视剧、电影、综艺、动漫、纪录片、短剧 |
| 13 | 红牛 | 接口通过，待APP实播 | 电视剧、电影、综艺、动漫、纪录片、短剧 |
| 14 | 极速 | 接口通过，待APP实播 | 电视剧、电影、综艺、动漫、纪录片、短剧 |
| 15 | 金鹰 | 接口通过，待APP实播 | 电视剧、电影、综艺、动漫、纪录片、短剧 |
| 16 | 百度 | 接口通过，待APP实播 | 电视剧、电影、综艺、动漫、纪录片、短剧 |
| 17 | 火速 | 接口通过，待APP实播 | 保留上游分类 |
| 18 | 非凡（备用） | 接口通过，待APP实播 | 电视剧、电影、综艺、动漫、纪录片、短剧 |

## 直播

最终 734 个频道、954 条线路。频道别名与同频道线路合并；标准 M3U 中多条同名记录由 FM 5.6.8 的 Group.find 合并成一个频道的多条线路（已核对 TV 与手机端解析器）。每个频道最多保留 3 条线路，先选择不同媒体域名，再补同域线路，不能将不同域名等同于不同实际供应商。

直播输入包含原直播快照、iptv-org 中文及中国/港澳台列表、Guovin、vbskycn、suxuang、Kimentanm 等公开列表。本版检查 2000 条去重候选；直播输入 4985 条。构建阶段读取这些项目，APP 运行阶段只读取本包的直播快照，不再拉取他们的配置或列表。

相同流 URL 不重复入库；同名频道跨组冲突统一，名称中的 4K/8K、CCTV-5+、海外版本等差异保留。CCTV 数字排序，CCTV-5+ 接在 CCTV-5 后；卫视按湖南、浙江、东方、江苏、北京、广东、深圳等常用顺序，再按固定省级表排序。其他组保持稳定名称排序。

| 直播组（显示顺序） | 频道数 |
| --- | ---: |
| 央视 | 34 |
| 卫视 | 41 |
| 地方 | 313 |
| 港澳台 | 32 |
| 影视轮播 | 152 |
| 体育 | 9 |
| 少儿与纪录 | 11 |
| 综艺轮播 | 40 |
| 音乐 | 3 |
| 游戏直播 | 17 |
| 风景慢直播 | 23 |
| 国际 | 59 |

央视 1–17 和 CCTV-5+ 均有通过本次样本检查的线路。宁夏卫视、兵团卫视未找到通过检查的线路，列入缺失报告，不填入不可播放的占位频道。港台电视、TVBS、凤凰、翡翠等部分别名已合并；“特种兵之火凤凰”“沙滩翡翠湾”不会误分到港澳台。春晚、游戏、景观流单独分组。上游错误的台名或多个年份的同名轮播，不能凭 HTTP 200 判断内容正确，需要实播核对。

## 检查与限制

全部入选点播接口通过列表、已知片名精确搜索、随机不存在片名负向搜索、详情、分类存在性、直链线路过滤检查。其中 7 个接口还通过 HLS 子列表或媒体片段抽样，其余标注待实播。

直播通过 HLS 主/子列表或片段字节检查；HTTP 200 的 HTML 响应不算可用。首页通过 JVM 模拟接口故障、跨源去重、季/年份区分、分类翻页、详情身份、负向搜索、直链线路测试，发行前另在 Actions 执行真实 CMS 首页/海报字段/分类/详情整合检查。

尚未连接真实 Android 设备，不能将这些检查称为 FM APP 首帧播放、画面内容正确或国内所有运营商访问验证。jsDelivr 链接采用你要求的 npm 形式，但 CDN 和媒体服务仍可能受地区、运营商与缓存影响。

## 独立维护与后续轮询

源清单在 input/cms-candidates.json；分类和排序在 scripts/assemble.py；主页源码在 java/src/；诊断报告在 reports/。原配置地址读取失败时使用已保存清单，继续检查独立候选。

现在没有启用定时任务。手动完整更新流程：运行 audit-and-enrich → 下载 enrichment-probes 到 probe-output/ → 提升 package.json 版本号 → 运行 assemble.py → 检查差异/缺失/退化 → 在独立仓库提交 → 运行 publish-independent-npm。Python 本机使用 /Users/ckw/.workbuddy/binaries/python/envs/default/bin/python。发行流程先做结构/分类/主页检查，再 npm 发布，最后等待 npm/CDN 同步并校验文件哈希；避免发布成功但传播未完成就误报失败。

后续自动轮询建议在你的国内网络进行 API 与直播媒体抽检，并用 Actions 负责构建和发行。采用连续失败隔离、恢复连续成功再入库、近期成功快照保留、来源失败单独降级、频道覆盖阈值与大幅减少阻断发布，避免单次网络抖动清空内容。用户反馈应记录频道/片名、时间、网络、错误及线路，形成排序依据。先完成本版 APP 测试，再确定频率和发布阈值。

发布新版本一般只需刷新 latest 地址；必须二次导入时可分发新固定版本地址。每版 API 中的 JAR 和直播快照固定到相同版本，避免资源混版；旧固定版本可用来回退。若 jsDelivr 域名整体无法访问，仅改版本号无效，需要另一个经过国内验证的分发域名。

## 原配置逐项清单

| 序号 | 名称 | 类型 | API / 适配器 |
| --- | --- | ---: | --- |
| 1 | 豆豆┃片单 | 3 | `csp_DouDouGuard` |
| 2 | 索尼 | 采集  | 1 | `https://suoniapi.com/api.php/provide/vod/` |
| 3 | 光速资源(切) | 1 | `https://api.guangsuapi.com/api.php/provide/vod/` |
| 4 | 玉兔 | 采集 | 1 | `https://apiyutu.com/api.php/provide/vod/` |
| 5 | 辣椒 | 采集 | 1 | `https://apilj.com/api.php/provide/vod/` |
| 6 | 天堂 | 采集 | 1 | `https://caiji.dyttzyapi.com/api.php/provide/vod/` |
| 7 | 无尽 | 采集 | 1 | `https://api.wujinapi.net/api.php/provide/vod/` |
| 8 | 影视 | 天涯 | 1 | `https://tyyszy.com/api.php/provide/vod` |
| 9 | 红牛资源(切) | 1 | `https://www.hongniuzy2.com/api.php/provide/vod/` |
| 10 | 量子 | 采集 | 1 | `https://cj.lziapi.com/api.php/provide/vod/` |
| 11 | 新浪资源(切) | 1 | `https://api.xinlangapi.com/xinlangapi.php/provide/vod/` |
| 12 | 金鹰 | 采集 | 1 | `https://jyzyapi.com/api.php/provide/vod/` |
| 13 | 火速 | 采集 | 1 | `https://api.huosuapi.cc/api.php/provide/vod/` |
| 14 | 影视 | 极速[直连] | 1 | `https://jszyapi.com/api.php/provide/vod/?ac=list` |
| 15 | 滴滴 | 采集 | 1 | `https://api.ddapi.cc/api.php/provide/vod/` |
| 16 | 闪电资源(切) | 1 | `https://sdzyapi.com/api.php/provide/vod/` |
| 17 | 非凡 | 采集 | 1 | `https://cj.ffzyapi.com/api.php/provide/vod/` |
| 18 | 360 | 采集 | 1 | `https://360zy.com/api.php/provide/vod/` |
| 19 | 🍓糯米┃秒播 | 3 | `csp_NmyswvGuard` |
| 20 | 💮文采┃秒播 | 3 | `csp_JpysGuard` |
| 21 | 🧀奶酪┃秒播 | 3 | `csp_T4Guard` |
| 22 | 👒原创┃不卡 | 3 | `csp_YCyzGuard` |
| 23 | 📔厂长┃不卡 | 3 | `csp_NewCzGuard` |
| 24 | 🌞光影┃不卡 | 3 | `csp_T4Guard` |
| 25 | 👀瓜子┃不卡 | 3 | `csp_AppgzGuard` |
| 26 | 🍄比特┃不卡 | 3 | `csp_BttwooGuard` |
| 27 | 📺热播┃多线 | 3 | `csp_AppTTGuard` |
| 28 | 🌸茉莉┃多线 | 3 | `csp_App99Guard` |
| 29 | 🐻剧圈┃多线 | 3 | `csp_AppSxGuard` |
| 30 | 🥝荐片┃多线 | 3 | `csp_JPJGuard` |
| 31 | 🏝奥特┃多线 | 3 | `csp_AueteGuard` |
| 32 | 🦉咕咕┃动漫 | 3 | `csp_AppSxGuard` |
| 33 | 🚌巴士┃动漫 | 3 | `csp_Dm84Guard` |
| 34 | 乐播 | 采集 | 1 | `https://lbapi9.com/api.php/provide/vod/` |
| 35 | 🧲新6V┃磁力 | 3 | `csp_SixVGuard` |
| 36 | 暴風 | 采集 | 1 | `https://bfzyapi.com/api.php/provide/vod/` |
| 37 | 茅台 | 采集 | 1 | `https://mtzy.me/api.php/provide/vod/` |
| 38 | 百度 | 1 | `https://api.apibdzy.com/api.php/provide/vod?ac=list` |
| 39 | 🐟斗鱼┃直播 | 3 | `https://git.yylx.win/https://raw.githubusercontent.com/fantaiying7/EXT/refs/heads/main/drpy2.min.js` |
| 40 | 📚儿童┃启蒙 | 3 | `https://git.yylx.win/https://raw.githubusercontent.com/fantaiying7/EXT/refs/heads/main/drpy2.min.js` |
| 41 | 🐯虎牙┃直播 | 3 | `https://git.yylx.win/https://raw.githubusercontent.com/fantaiying7/EXT/refs/heads/main/drpy2.min.js` |
| 42 | 🚀叨观荐影┃预告片 | 3 | `csp_YGPGuard` |
| 43 | 🎙️易听音乐┃带歌词 | 3 | `csp_MusicGuard` |
| 44 | ⚽八八┃看球 | 3 | `csp_KanqiuGuard` |
| 45 | 🏀多多┃回放 | 3 | `csp_DoubaoGuard` |
| 46 | 🏐吃瓜┃看球 | 3 | `csp_LiveGzGuard` |
| 47 | 🎮一直播┃直播 | 3 | `csp_AllliveGuard` |
| 48 | 🎶明星┃MV | 3 | `csp_BiliGuard` |
| 49 | 🎧有声┃小说 | 3 | `csp_Tingshu275Guard` |
| 50 | 🚑急救┃教学 | 3 | `csp_FirstAidGuard` |
| 51 | 🅱哔哔演唱会┃弹幕 | 3 | `csp_BiliGuard` |
| 52 | 📚少儿┃教育 | 3 | `csp_BiliGuard` |
| 53 | 📚小学┃课堂 | 3 | `csp_BiliGuard` |
| 54 | 📚初中┃课堂 | 3 | `csp_BiliGuard` |
| 55 | 📚高中┃课堂 | 3 | `csp_BiliGuard` |
