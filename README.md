# WKC 自有聚合源

为 FM 影视 TV / 手机端维护的独立配置项目。恢复动态海报首页、电视剧 / 电影 / 综艺 / 动漫等分类、多站搜索、详情、选集和切源。日常构建只读取本仓库登记表，不再下载其他作者的聚合配置。

项目：`WKC0001/tvbox-independent`；npm：`wkc0001-tvbox-independent`。旧 `source-monitor` 和 `wkc0001-tvbox` 不作为发布目标。

## 导入与发布

优先向使用者提供经过验收的**固定版本**地址：

`https://cdn.jsdelivr.net/npm/wkc0001-tvbox-independent@版本号/api.json`

所有插件、直播列表和配置依赖绑定同一个版本。`dc.json` 是单仓入口。版本内资源不会随着 `latest` 改变；需要替换时生成新版本、验收，再通知使用者重新导入。npm 的 `next` 是候选，`latest` 只允许指向具有双 APK 验收记录的版本。

GitHub Actions 的 `publish.yml` 构建真实 Android DEX、执行回归检查、发布 `next`，再逐文件对比 npm tarball 和 jsDelivr 内容。CDN 检查失败时不得宣称地址可用。重新生成候选：

```sh
# 本机 Python 固定使用用户提供的环境
/Users/ckw/.workbuddy/binaries/python/envs/default/bin/python scripts/admin_release.py candidate
```

测试通过后，将真实验收记录保存为 `reports/acceptance/版本号.json` 并通过 API 推送；`files` 必须与已发布 manifest 完全一致，再执行：

```sh
/Users/ckw/.workbuddy/binaries/python/envs/default/bin/python scripts/admin_release.py promote 版本号
# 回滚到已有双端验收记录的固定版本
/Users/ckw/.workbuddy/binaries/python/envs/default/bin/python scripts/admin_release.py rollback 旧版本号
```

以上命令只调度 Actions，不在本地直接发布 npm。`scripts/api_push.py` 根据 `.push-plan.json` 的明确文件及删除清单更新本仓库，检查预期 HEAD，禁止强制覆盖远端。`.commit-msg` 存放提交说明，`.commit-expected-head` 存放已检查的远端提交。

## 维护入口

| 文件 | 职责 |
| --- | --- |
| `registry/sites.json` | 站点地址、稳定排序、原始配置、首次准入与隔离状态 |
| `registry/channels.json` | 电视身份、别名、分组、真实 EPG 映射、关联线路 |
| `registry/routes.json` | 媒体地址、请求头、来源记录与隔离状态 |
| `policy/operations.json` | 首选探测网络、线路上限、证据时效、候选自动化开关 |
| `checker/content.py` | Python 与 Java 共用的分类及元数据内容规则 |
| `state/provider-audit.json` | 各网络完整功能检查和最近一次成功证据 |
| `state/multisite-health.json` | 按线路或站点 × 网络持久化的健康状态 |
| `state/native-audit.json` | 原生适配器在实际 Android 运行时的准入证据 |
| `output/` | 本版本实际发布资源；只有干净的 `npmstage/` 被打包 |
| `reports/` | 迁移台账、线路缺口、候补站点、解码和验收证据 |

一次性迁移保留旧清单 1024 条记录的去向。保留真实电视身份，不按知名度删除地方台；同台多线路合并到一个身份，最多输出配置指定的优先线路。移除平台轮播、景区摄像头、宣传文件、节目单片循环。只有音频的错误电视线路被移除，电视身份留在缺口清单等待补线。

新增视频站必须先登记、通过完整探测并记录首次准入；自动探测不能自动批准新站。CMS 使用自有适配器，动态刷新分类和内容；首页/分类/搜索/详情/播放入口均执行策略。原生旧适配器通过自有包装层接入，解密桥由冻结基线重建，只有通过实际 Android 功能检查的适配器进入输出。

## 检查与故障处置

```sh
/Users/ckw/.workbuddy/binaries/python/envs/default/bin/python -m checker.audit --network local-direct --mode full --workers 20
/Users/ckw/.workbuddy/binaries/python/envs/default/bin/python scripts/build_release.py
```

构建需要 JDK17、D8、apktool3.0.3、org.json20240303；CI 下载并核对固定依赖，路径可用 `JAVA_HOME / D8_JAR / SMALI_JAR / JSON_JAR` 指定。编译桩和测试类不进入插件。

自动维护每两小时轮换轻量探测，每天北京时间 07:00 全量检查，周末再全量检查。健康按网络保存；单次失败降级，连续失败移出当前输出，恢复要求间隔至少十分钟的两次成功。超过七天的证据失效。大面积异常阻止普通候选发布，上一版保持有效。`local-direct` 表示本机直连，`github` 表示 Actions，均不等于已验证所有国内运营商。

发现内容污染时立即隔离，不等待可用率阈值：

```sh
/Users/ckw/.workbuddy/binaries/python/envs/default/bin/python scripts/admin_release.py quarantine site 站点ID --reason '具体原因'
/Users/ckw/.workbuddy/binaries/python/envs/default/bin/python scripts/admin_release.py quarantine route 线路ID --reason '具体原因'
```

检查本地登记表和状态变更后 API 推送，生成新候选并验收。历史固定链接不可撤回，必须另行告知使用者替换链接。普通探测成功不会解除内容隔离。

## 能力边界

本项目自主管理配置、登记表、CMS 适配器、过滤、检测和发版；影视与电视流仍来自登记的外部服务，不是自建内容服务器。旧站二进制与原生库被固定保留，部分原生适配器尚未具备完整源码维护能力。失败站留在候补清单，不以数量代替可用性。

元数据过滤和视频抽样不能保证第三方内容以后永远合规、无广告或可播放。页面返回 200、M3U8 有效、样本成功解码与实际 APK 播放分开记录。地区、运营商、设备硬解和 CDN 状态仍可能不同。未经真实节目表匹配的 EPG ID 不输出；节目单缺失时不伪造。

迁移参考资料与许可说明见 `docs/`，详细原始方案见 `docs/MIGRATION-PLAN.md`。新增来源还应保留出处和适用的使用许可。
