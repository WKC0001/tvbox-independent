# WKC 自有聚合源

为 FM 影视 TV / 手机端维护的独立配置项目。恢复动态海报首页、电视剧 / 电影 / 综艺 / 动漫等分类、多站搜索、详情、选集和切源。日常构建只读取本仓库登记表，不再下载其他作者的聚合配置。

项目：`WKC0001/tvbox-independent`；npm：`wkc0001-tvbox-independent`。旧 `source-monitor` 和 `wkc0001-tvbox` 不作为发布目标。

## 导入与发布

公开分发入口（给任何人用）：

`https://cdn.jsdelivr.net/npm/wkc0001-tvbox-independent@latest/dc.json`

多仓入口，地址恒定，使用者不必在每次更新后重新导入。说明页与二维码在
`https://wkc0001.github.io/tvbox-independent/`。

固定版本地址同样可用，而且是排查问题的首选 —— 它逐字节冻结，不受 `latest` 移动影响：

`https://cdn.jsdelivr.net/npm/wkc0001-tvbox-independent@版本号/api.json`

插件、直播列表和配置都绑定同一个版本。npm 的 `next` 是候选；`latest` 由 `scripts/auto_acceptance.py`
产生的三项机器验收证据决定（`cdn_verified` / `config_protocol` / `playback_probe`），
任一项不通过 `latest` 就不会动。原先要求"双端 APK 人工验收"，实测从未被满足过，
`latest` 因此长期停在 `0.3.0`，该门槛已由机器验收取代。

GitHub Actions 的 `publish.yml` 构建真实 Android DEX、执行回归检查、发布 `next`，再逐文件对比 npm tarball 和 jsDelivr 内容。CDN 检查失败时不得宣称地址可用。重新生成候选：

```sh
# 本机 Python 固定使用用户提供的环境
/Users/ckw/.workbuddy/binaries/python/envs/default/bin/python scripts/admin_release.py candidate
```

验收记录由 `publish.yml` 在 CDN 字节校验通过后自动产生（`reports/acceptance/版本号.json`），
随版本一起冻结提交，不需要人工保存。`policy/operations.json` 的 `automatic_latest` 为真时，
发布流水线会在验收通过后自行申请提升 `latest`。人工通道保持不变：

```sh
/Users/ckw/.workbuddy/binaries/python/envs/default/bin/python scripts/admin_release.py promote 版本号
# 回滚到已有验收记录的固定版本
/Users/ckw/.workbuddy/binaries/python/envs/default/bin/python scripts/admin_release.py rollback 旧版本号
```

以上命令只调度 Actions，不在本地直接发布 npm。`scripts/api_push.py` 根据 `.push-plan.json` 的明确文件及删除清单更新本仓库，检查预期 HEAD，禁止强制覆盖远端。`.commit-msg` 存放提交说明，`.commit-expected-head` 存放已检查的远端提交。

## 维护入口

| 文件 | 职责 |
| --- | --- |
| `registry/sites.json` | 站点地址、稳定排序、原始配置、首次准入与隔离状态 |
| `registry/channels.json` | 电视身份、别名、分组、真实 EPG 映射、关联线路 |
| `registry/routes.json` | 媒体地址、请求头、来源记录与隔离状态 |
| `policy/operations.json` | 首选探测网络、线路上限、证据时效、EPG 来源与有效期、候选自动化开关 |
| `checker/content.py` | Python 与 Java 共用的分类及元数据内容规则 |
| `state/provider-audit.json` | 各网络完整功能检查和最近一次成功证据 |
| `state/multisite-health.json` | 按线路或站点 × 网络持久化的健康状态 |
| `state/native-audit.json` | 原生适配器在实际 Android 运行时的准入证据 |
| `state/live-measured.json` | 每条直播线路的实测下载速度比，构建时挂到线路排序权重上 |
| `output/` | 本版本实际发布资源；只有干净的 `npmstage/` 被打包 |
| `reports/` | 迁移台账、线路缺口、EPG 匹配与缺口、候补站点、解码和验收证据 |
| `docs/` | GitHub Pages 说明页与主入口二维码；页面上每个数字都读自构建产物 |
| `scripts/auto_acceptance.py` | 产生三项机器验收证据（CDN 自洽、配置结构、播放链探测） |
| `scripts/build_landing.py` | 由构建产物生成说明页与二维码，不手写任何数字 |
| `scripts/ingest_live_measurements.py` | 把直播测速结果并进 `state/live-measured.json` |

一次性迁移保留旧清单 1024 条记录的去向。保留真实电视身份，不按知名度删除地方台；同台多线路合并到一个身份，最多输出配置指定的优先线路。移除平台轮播、景区摄像头、宣传文件、节目单片循环。只有音频的错误电视线路被移除，电视身份留在缺口清单等待补线。

电视线路还必须证明它真的在播这个频道。`scripts/verify_live_identity.py` 跟随每条线路的跳转链，把最终播放列表上的频道标识与请求的频道比对：路径里的 `dfwshd` 和查询参数里的 `id=cctv8k` 都算频道名，对上一个即算同一条频道。判定不靠名字的前缀相似，而是统计"同一个标识被多少个互不相干的频道请求收到"——一个标识答复了几十个不同频道，它就不是频道而是广告或占位（实测 `mkt`、`byt`、`107`、`102`、`yss`、`aad` 与返回错误页的标识都属此类）；服务端只是把某个频道换个长名字不会被误判（`cwjd` 收到 `CBN_XP_cwjdHD`、`jjsh` 收到 `jingjishenghuo` 都算命中）。可达性是必要条件但不充分：广告流的字节是完全合法的 HLS，探测和延迟排序都分辨不出来，因此只按延迟排序就会把最快的广告源排在官方源前面——这正是"打开东方卫视却在播购物广告"的成因。流程是先抽查一遍、出现不一致的线路再用 8 次独立请求复核、其中过半数落在填充标识上才隔离；被隔离的线路写入 `review=quarantined` 与 `quarantine_reason`，同时按内容污染标记健康状态，播放列表不再输出，缺线的频道如实进入缺口清单。

新增视频站必须先登记、通过完整探测并记录首次准入；自动探测不能自动批准新站。CMS 使用自有适配器，动态刷新分类和内容；首页/分类/搜索/详情/播放入口均执行策略。原生旧适配器通过自有包装层接入，解密桥由冻结基线重建，只有通过实际 Android 功能检查的适配器进入输出。

首页的「点我切源」是跨上游聚合：搜索并发问全部上游（8 秒总预算，超时的上游不影响其他上游），按标题归一化分组，同名结果合成一行并标注 `[N源]`，详情页把各上游的线路合并到一起。旧实现是优先级失败切换（`if (list.length() > 0) return list;`），而采集站的模糊搜索永远返回非空，因此永远轮不到第二个上游——这才是"点进去只有一个源"真正的成因，不是缺一个聚合服务。

详情页同样要把所有上游的线路给全，而凭证里未必带着全部上游：首页和分类至今仍是"先答者优先"（每页只看一个上游的内容才不会翻到重复条目），从这两处点进去的凭证只有一个上游。所以详情页在收到单源凭证时，会先取这一条详情、再用片名回问其余上游（5 秒预算，结果按片名缓存 5 分钟），把同一部剧在别处的凭证补回来后一起合并。补不到就退回单源，不报错——实测《假面良人》6 个上游全部精确命中，也就是说只显示一个源等于只给了用户 1/6。代价是详情页首次打开会比原来慢 1~3 秒。

分组前会剥掉「版本 / 季数 / 集数」这类修饰后缀（`第二季` `完结` `网飞版` `卫视版` `(2024)` …），但不剥「之XXX」：前者是同一部剧的不同版本，应并成一行；后者是另一部剧。这个区分是实测出来的——不剥后缀时同一部剧的各个版本会各占一行、各带一部分源，看起来"源很多"其实每行只有一个；宽松档再不加长度约束的话，搜「狂飙」会被「狂飙之浴血玫瑰」这类衍生剧填满。实测 6 个上游搜 8 个常见剧名共返回 377 条：按完整标题分组是 104 行，按上面的规则是 20 行。

每条播放线路的显示名都带「⚠勿信广告」，站点名同样带。这不是装饰：聚合里的上游会在播放过程中插广告，其中一部分是博彩类，客户端拦不住，只能提示。线路对外显示名可改，但插件仍用上游原始 `flag` 重新核对一次播放路线，未经批准的路线会被拒绝。

线路名的格式是「来源名 ⚠勿信广告 · 上游原始线路」。必须保留上游原始线路：只写来源名的话，同一个上游的蓝光/标清两条线会塌成同一个名字，客户端去重后变成「飘零·2」「飘零·3」，用户看不出区别（实测截图里就是这样）。`$$$` `#` `$` 会破坏分行，长度超过 16 字会截断。

线路的顺序就是播放器的默认选择，排序规则是「先无广告，再快的」：构建端把每个上游的 `ad_scan`（clean = 抽帧 OCR 扫过且没发现博彩广告 / flagged = 扫到了 / pending = 没扫过）和 `latency_ms`（接口实测延迟）写进 `ext`，插件按 `(ad_scan, latency_ms, 上游序号)` 排，第一条就是最干净最快的那条。没有实测延迟的排最后，而不是当成 0 插到最前。注意 `pending` 不等于 `clean`：没扫过就是没扫过，不能当作"干净"排到确认干净的前面——那等于伪造结论。

电视节目单只输出被节目表接口当场证实的映射。`scripts/epg_match.py` 逐频道查询 51zmt 的 diyp 接口，只有返回真实节目、且返回的频道名仍指向同一频道时才登记 `epg_id`、来源和核验时间；名字相近不算命中，按命名规则拼出来的 ID 一律不写入。构建时再按 `epg_evidence_max_age_days` 过滤一遍：来源不在 `epg_sources` 内、核验时间缺失、来自未来、或已过有效期的映射降级为"没有节目单"，而不是给出错误节目单。`api.json` 的直播条目带 `epg` 模板，播放器把 `{id}` 换成该频道的 `tvg-id`、`{date}` 换成所查看的日期；没有节目单的频道记入 `reports/epg-gaps.json`。`scripts/verify_multisite.py` 会按播放器的取用方式重算一遍每个 `tvg-id`，与登记表或策略不符即构建失败。

节目表接口对批量查询不友好：它会对密集请求直接断开连接，也会对刚刚正常返回过的频道回"未提供"。因此匹配器按"宁可不改也不改错"设计——只有**整次探测零传输错误、且两次独立拒绝**才撤销既有映射，其余情况（连不上、答复自相矛盾）一律保留原值，绝不凭空补一个；注册表内容没有实际变化就不写文件，所以被限流的一次运行不会变成一次无意义的发版。单个运行用 `--window` 只走登记表的一个分片并从 `state/epg-cursor.json` 续上，避免整表批量查询；有效期 35 天覆盖每周一轮、约三周走完全部频道，并留一次漏跑的余量。真正废弃的映射由这个有效期自然停用，而不是靠一次可疑的否定删除。

重新确认一个映射只改它的核验时间，用户收到的字节一个都没变。维护任务仍会提交这份续期证据（它是有效期得以延续的依据），但不因此开新版本：`scripts/guide_signature.py` 只按映射本身算摘要，摘要没变且健康证据也没变时就判定 `changed=false`。否则每周分片轮转都会推出一个内容完全相同的新版本号。

## 检查与故障处置

```sh
/Users/ckw/.workbuddy/binaries/python/envs/default/bin/python -m checker.audit --network local-direct --mode full --workers 20
/Users/ckw/.workbuddy/binaries/python/envs/default/bin/python scripts/build_release.py
```

构建需要 JDK17、D8(build-tools 34.0.0)、smali 3.0.9、org.json20240303；路径可用 `JAVA_HOME / D8_JAR / SMALI_JAR / JSON_JAR` 指定。`SMALI_JAR` 不再指向 apktool：apktool 3.x 的发行包不含 baksmali/smali 入口，2.x 的捆绑版本无法按字节复现。改为 `scripts/prepare_tools.py` 按 `policy/build-tools.json` 从 Google Maven（smali 4 件）和 Maven Central（guava/antlr/jcommander 等 9 件）逐件下载并校验 sha256，再确定性地装配成 `.build-tools/smali-tools.jar`；装配结果的 sha256 锁在同一个文件里，构建时复查。编译桩和测试类不进入插件。

自动维护每两小时轮换轻量探测，其中北京时间 06:00 与 18:00 两轮升级为全量检查（含线路身份核验），周末再额外全量一次；周末那次同时重跑节目单核验刷新 `epg_checked_at`。健康按网络保存；单次失败降级，连续失败移出当前输出，恢复要求间隔至少十分钟的两次成功。超过七天的证据失效。大面积异常阻止普通候选发布，上一版保持有效。`local-direct` 表示本机直连，`github` 表示 Actions，均不等于已验证所有国内运营商。

发现内容污染时立即隔离，不等待可用率阈值：

```sh
/Users/ckw/.workbuddy/binaries/python/envs/default/bin/python scripts/admin_release.py quarantine site 站点ID --reason '具体原因'
/Users/ckw/.workbuddy/binaries/python/envs/default/bin/python scripts/admin_release.py quarantine route 线路ID --reason '具体原因'
```

检查本地登记表和状态变更后 API 推送，生成新候选并验收。主入口用 `@latest`，所以换版本不需要使用者做任何事；已分发出去的固定版本链接无法撤回。普通探测成功不会解除内容隔离。

验收不依赖人工装包：`publish.yml` 在 CDN 字节校验通过后运行 `scripts/auto_acceptance.py`，从 CDN 上真实取回这一版的 `manifest.json` 并逐个下载声明的文件重算哈希（不拿本地构建产物比对——提升的可能是历史版本，那样会把没问题的发布误判成有问题），核对聚合首页唯一、插件指针与已发布 `cfg.jpg` 的 md5 一致、每个上游都有媒体域名白名单和广告提示、站点名不含成人分类词、直播与 EPG 模板完整，再从发布配置里取真实上游走完 分类 → 条目 → 详情 → 取到媒体字节。`device_tested` 如实记为 `false`：这一版没有在真机上点过，记录不许把它说成点过了。

## 能力边界

本项目自主管理配置、登记表、CMS 适配器、过滤、检测和发版；影视与电视流仍来自登记的外部服务，不是自建内容服务器。旧站二进制与原生库被固定保留，部分原生适配器尚未具备完整源码维护能力。失败站留在候补清单，不以数量代替可用性。

元数据过滤和视频抽样不能保证第三方内容以后永远合规、无广告或可播放。页面返回 200、M3U8 有效、样本成功解码与实际 APK 播放分开记录。地区、运营商、设备硬解和 CDN 状态仍可能不同。未经真实节目表匹配的 EPG ID 不输出；节目单缺失时不伪造。

线路身份校验只能剔除**已被证实**在替别的频道作答的来源，不能保证保留下来的线路永远干净。实测同一家上游同时运营着正常入口和广告网关：被隔离的入口在抽查中约八成请求返回购物广告，保留下来的那条也有约一成概率被塞进广告。要彻底消除只能引入新的、可长期验证的干净来源，而新增线路必须走登记与完整探测，不能就地改写地址。

隔离是**留痕且不自动解除**的：每次校验会把已隔离的线路重新探一遍，把「本次新判定」和「此前判定仍然成立」分开记在 `reports/live-identity.json`（`newly_quarantined` / `carried_forward` / `reverified_still_mismatching`）。上游可能某一小时恢复正常，但同一条线路时说好话、时塞广告，正是它不可用的原因，因此重新探到正常也不会自动放回，只有人工复核才能解除。任一频道的最后一条可用线路永远不隔离，只降级为 `watch` 并留在报告里，避免「删掉广告的同时把频道也删掉」。

迁移参考资料与许可说明见 `docs/`，详细原始方案见 `docs/MIGRATION-PLAN.md`。新增来源还应保留出处和适用的使用许可。
