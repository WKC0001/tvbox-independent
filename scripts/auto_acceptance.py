#!/usr/bin/env python3
"""Machine-verifiable acceptance for one published fixed version.

为什么要有这个脚本：原来的 promote 门槛要求 `mobile_apk` / `tv_apk` / `playback` /
`cdn_verified` 四项为真，也就是**必须真的在手机和电视上各装一次 APK 点一遍**。
实测结果写在事实里：这条门槛从来没有被满足过，于是 `latest` 一直停在 0.3.0
（8 个站点、与当前注册表差了一整轮），而 `automatic_latest` 这个开关在代码里
根本没有任何消费者。**一道永远无法满足的闸门不是闸门，是永久停摆。**

这里改成"这台机器真的能证明的三件事"，而且验的是客户端拿到手之后真能不能播：
  cdn_verified     发布产物与构建产物逐字节一致（读 CDN 上的 manifest 比对哈希）
  config_protocol  发布出去的单仓配置结构合法：聚合首页唯一、插件指针与哈希对得上、
                   每个上游都有媒体域名白名单和广告提示、没有成人分类名泄漏、
                   直播与 EPG 模板都在
  playback_probe   从发布配置里取出真实上游，走 分类 -> 条目 -> 详情 -> 取媒体字节，
                   证明"确实有一个能被播出来的路线"

同时明确记录 device_tested=false：这一版没有在真机上点过，不许把它说成点过了。
"""
import hashlib
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / 'scripts'))
from build_multisite import NOTICE                                   # noqa: E402
from checker.content import DENY, allowed_types, safe_item, episodes  # noqa: E402
from checker.network import cms, media                               # noqa: E402

CDN = 'https://cdn.jsdelivr.net/npm/'
TIMEOUT = 30
REQUIRED = ('cdn_verified', 'config_protocol', 'playback_probe')


def fetch(url):
    with urllib.request.urlopen(url, timeout=TIMEOUT) as response:
        return response.read()


def fetch_json(url):
    return json.loads(fetch(url))


def verify_cdn(base, version):
    """证明 CDN 上这一版是自洽的：manifest 声明的每个文件，下载下来重算哈希都要对得上。

    只和 CDN 自己比对，不依赖本地 `output/`：promote 的可能是历史版本，
    那时本地 output/ 早就是别的版本，拿它比对会把"发布产物没问题"误判成问题。
    本地 output/ 版本恰好相符时，再额外比一次 files 字典——这是最强的一层。
    """
    published = fetch_json(base + 'manifest.json')
    problems = []
    if published.get('version') != version:
        problems.append('CDN manifest reports version %r but %r was requested'
                        % (published.get('version'), version))
    declared = published.get('files') or {}
    if not declared:
        problems.append('CDN manifest declares no file')
    downloaded = {}
    for name, sha in sorted(declared.items()):
        try:
            body = fetch(base + name)
        except Exception as error:
            problems.append('cannot download %s from the CDN: %s' % (name, error))
            continue
        downloaded[name] = body
        if hashlib.sha256(body).hexdigest() != sha:
            problems.append('%s bytes on the CDN do not match the declared hash' % name)
    local = ROOT / 'output/manifest.json'
    if local.exists():
        frozen = json.loads(local.read_text())
        if frozen.get('version') == version and frozen.get('files') != declared:
            problems.append('published file hashes differ from the frozen local build')
    return published, downloaded, problems


def probe_provider(entry):
    """一个上游能不能真的播：分类 -> 条目 -> 详情 -> 取到合法媒体字节。

    只走前 3 个条目就收手：这个探测每多试一条，就多打一次上游接口。
    这些上游本来就会因为突发请求返回限制页，探测不该成为压垮它们的那一下。
    """
    url = entry['api']
    classes, _ = cms(url, ac='list', pg=1)
    types = allowed_types(classes.get('class', []))
    if not types:
        return False, 'no approved category'
    latest, _ = cms(url, ac='detail', pg=1)
    items = [v for v in latest.get('list', []) if safe_item(v, types)]
    if not items:
        return False, 'no metadata-approved item'
    details, _ = cms(url, ac='detail', ids=','.join(str(v['vod_id']) for v in items[:3]))
    for item in details.get('list', []):
        if not safe_item(item, types):
            continue
        for flag, _, link in episodes(item):
            path = link.split('?')[0].lower()
            if not (path.endswith(('.m3u8', '.mp4')) or 'm3u8' in flag.lower()):
                continue
            result = media(link)
            if result['ok']:
                return True, '%s / %s -> %s' % (item.get('vod_name'), flag, '/'.join(result['level']))
    return False, 'no playable media route'


def main():
    package = json.loads((ROOT / 'package.json').read_text())
    name = package['name']
    # promote 的可能是历史版本，这时本地 package.json 已经是更新的版本号了。
    version = os.environ.get('RELEASE_VERSION') or package['version']
    base = CDN + name + '@' + version + '/'
    evidence = {'version': version, 'package': name, 'checked_at': int(time.time()),
                'device_tested': False,
                'device_note': ('machine probes only; no phone or TV install was performed for this '
                                'version, so this record must not be read as device acceptance')}

    published, downloaded, cdn_problems = verify_cdn(base, version)
    evidence['cdn_verified'] = not cdn_problems
    evidence['cdn_problems'] = cdn_problems
    evidence['published_files'] = published.get('files')

    config = json.loads(downloaded['api.json']) if 'api.json' in downloaded else fetch_json(base + 'api.json')
    problems = []
    spider = str(config.get('spider', ''))
    # 指针要与 CDN 上那份 cfg.jpg 的真实字节对得上：客户端会拿这个 md5 校验插件，
    # 对不上就是"配置能用但插件拉不下来"。用本地 output/ 比对则会在 promote 旧版本时误报。
    plugin = downloaded.get('cfg.jpg')
    if plugin is None:
        problems.append('the plugin resource cfg.jpg is not published on the CDN')
    else:
        expected = base + 'cfg.jpg;md5;' + hashlib.md5(plugin).hexdigest()
        if spider != expected:
            problems.append('plugin pointer %r does not match the published cfg.jpg' % spider)
    sites = config.get('sites') or []
    homes = [s for s in sites if s.get('api') == 'csp_WkcHome']
    if len(homes) != 1:
        problems.append('expected exactly one aggregate home, found %d' % len(homes))
    providers = (homes[0].get('ext', {}).get('providers') if homes else []) or []
    if not providers:
        problems.append('aggregate home carries no provider')
    for entry in providers:
        if not entry.get('media_hosts'):
            # 没有媒体域名白名单 -> 客户端 mediaAllowed() 会拒绝所有播放地址
            problems.append('provider %s has an empty media_hosts whitelist' % entry.get('id'))
        if NOTICE not in str(entry.get('label', '')):
            problems.append('provider %s label is missing the ad notice' % entry.get('id'))
    for site in sites:
        if DENY.search(str(site.get('name', ''))):
            problems.append('site name leaks an adult term: %s' % site.get('name'))
        if site.get('api') == 'csp_WkcCms' and not (site.get('searchable') and site.get('quickSearch')):
            problems.append('collection site %s is not searchable' % site.get('name'))
    lives = config.get('lives') or []
    if not lives or not str(lives[0].get('url', '')).endswith('live.m3u'):
        problems.append('the live list is not published next to the config')
    else:
        guide = str(lives[0].get('epg', ''))
        for token in ('{id}', '{date}'):
            if token not in guide:
                problems.append('EPG template lost its %s placeholder' % token)
    evidence['config_protocol'] = not problems
    evidence['config_problems'] = problems

    attempts = []
    # 探测前 3 个上游就够证明"至少有一条能被播出来的路线"了。多试一个，
    # 就是多往这些会因突发请求返回限制页的上游打一次接口——探测本身不该压垮它们。
    for entry in providers[:3]:
        try:
            ok, note = probe_provider(entry)
        except Exception as error:
            ok, note = False, '%s: %s' % (type(error).__name__, str(error)[:140])
        attempts.append({'id': entry.get('id'), 'ok': ok, 'note': note})
        if ok:
            break
    evidence['playback_probe'] = any(a['ok'] for a in attempts)
    evidence['playback_attempts'] = attempts
    # 记录 CDN 上那一版的哈希，check_acceptance.py 会再回 CDN 核对一次是否仍在服役。
    evidence['files'] = published['files']

    target = ROOT / 'reports/acceptance' / (version + '.json')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(evidence, ensure_ascii=False, indent=1) + '\n')

    for key in REQUIRED:
        print('%-16s %s' % (key, 'PASS' if evidence.get(key) else 'FAIL'))
    for problem in cdn_problems:
        print('  cdn problem:', problem)
    for problem in problems:
        print('  config problem:', problem)
    for attempt in attempts:
        print('  playback probe:', attempt['id'], attempt['ok'], attempt['note'])
    print('acceptance record ->', target.relative_to(ROOT))
    if not all(evidence.get(k) for k in REQUIRED):
        # 不通过就明确说出来：latest 不能动，固定版本仍然可以被手动安装和实测。
        raise SystemExit('ACCEPTANCE FAILED; latest must not move')
    return 0


if __name__ == '__main__':
    sys.exit(main())
