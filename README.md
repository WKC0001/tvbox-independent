# WKC 独立影视聚合源

本次源码修复版本为 0.4.1。须通过 Actions 发布并验证后才能导入；源码版本号不代表 npm/CDN 已发布。

## 修复内容

0.4.0 的配置包含23部作品，home.jpg却仍绑定0.3.0的旧片单，APP初始化因此拒绝加载。现在由 scripts/build_release.py 统一生成片单、编译Java、转换DEX、打包home.jpg、重建配置与manifest，并验证实际下发DEX的校验常量。仅测试Java源码不足以证明插件可用。

本次保留交接包已有23部作品、43个直播频道和44条线路，没有新增来源，也不将旧 source-monitor 配置整体恢复。

## 构建与发布

准备 Java17、org.json 20240303、Android Build Tools34.0.0；设置 JAVA_HOME、JSON_JAR、D8_JAR，使用交接要求的项目 Python：

```bash
"$PYTHON" scripts/build_release.py
npm pack --ignore-scripts
```

唯一完整发布实现是 .github/workflows/publish.yml（publish-independent-npm）；publish-release.yml保留为兼容入口，调用同一实现。Actions会重新构建实际Android插件，再发布固定版本候选到 next，并核对registry和CDN字节。原0.4.0不能原版本覆盖，须使用尚未发布的新版本。

正式推荐固定版本api.json。latest只是别名；仅在其实际响应匹配时推荐。先验证国内网络与FM手机/TV端，不能把源码测试通过等同于设备或媒体全部可播。

## 内容与维护边界

首页、分类、搜索、详情只使用批准目录，未知ID/播放地址与片单篡改会被拒绝。既有审核是抽样证据，媒体仍由第三方提供，本次未重新核实所有剧集和直播画面。已有内容封禁保持。

维护工作流按中国时间每日07:17全量检查，每两小时轻检查；每周六03:17做检查，不自动调用候选合并来批准内容。隔离线路在构建时剔除；旧固定版本不能远程撤回，需重新发布并通知用户换地址。

原WKC0001/source-monitor仓库和wkc0001-tvbox npm包保持不变。
