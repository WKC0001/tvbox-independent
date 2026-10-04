"""构建自有 XMLTV 节目单：去水印、频道 id 对齐本仓库的 tvg-id。

为什么要自己生成一份
--------------------
51zmt 的 diyp JSON 接口在每个节目名后面都拼了「 --免费使用」（服务端行为，
参数关不掉，实测 `?ch=CCTV4` 逐字返回 `新闻联播 --免费使用`）。播放器拿到什么
就显示什么，客户端拦不住。

同一家的 XMLTV（cc.xml）**没有**这个水印，而且标题更详细。播放器（FM影视TV
5.6.8，反编译确认 `bq0` 类）支持 XMLTV（含 gzip），并且用 `tvg-id` 精确匹配
`<channel id>`。但它的 id 是 `1..101` 这种无意义序号，跟我们的 `CCTV4` 对不上。

所以：下载上游 XMLTV → 按显示名对回本仓库已核验的 `epg_id` → 重写 `<channel id>`
与 `channel=` → gzip 成 `guide.xml.gz`，`epg` 直接指向它。
只输出能对上的频道；对不上的如实进报告，不编一个 id 出来。

上游 XMLTV 只覆盖约 101 个频道（央视与省级卫视），所以这会比 diyp 少覆盖一批
地方/港澳台频道——这是为了去掉水印付出的真实代价，缺口在报告里可见。
"""
import argparse
import gzip
import json
import re
import sys
import time
import urllib.request
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
from verify_live_identity import normalize, same_channel  # noqa: E402
from checker.television import epg_identity  # noqa: E402

# 上游 diyp JSON 里拼的是「 --免费使用」；XMLTV 目前没有，但这里仍然剥一次，
# 防止哪天上游把水印加进 XMLTV 而没人发现。
WATERMARK = re.compile(r'\s*-{1,2}\s*免费使用\s*$')
CHANNEL_BLOCK = re.compile(r'<channel id="([^"]*)"[^>]*>(.*?)</channel>', re.S)
DISPLAY = re.compile(r'<display-name[^>]*>([^<]*)</display-name>')
PROGRAMME = re.compile(r'<programme\s.*?channel="([^"]*)"')


# 上游 epg.51zmt.top 是单台小机，实测会 RemoteDisconnected / 502。
# 构建是每天两次的定时任务，不该被上游一次抖动打断：先重试，再退回上一份缓存。
CACHE = ROOT / '.build-cache/cc.xml'
ATTEMPTS = 4
ORIGIN = ['upstream']


def fetch(url, timeout=60):
    request = urllib.request.Request(url, headers={'User-Agent': 'okhttp/4.12.0'})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def load_upstream(path, url):
    if path:
        ORIGIN[0] = 'local:%s' % path
        return Path(path).read_text(encoding='utf-8')
    last = None
    for attempt in range(ATTEMPTS):
        try:
            body = fetch(url)
            if body[:2] == b'\x1f\x8b':
                body = gzip.decompress(body)
            text = body.decode('utf-8', 'replace')
            if '<programme' in text or '<channel' in text:
                CACHE.parent.mkdir(parents=True, exist_ok=True)
                CACHE.write_text(text, encoding='utf-8')
                ORIGIN[0] = 'upstream'
                return text
            last = 'upstream returned no programme/channel element'
        except Exception as exc:
            last = exc
        if attempt + 1 < ATTEMPTS:
            time.sleep(5 * (attempt + 1))
    if CACHE.exists():
        print('     upstream unavailable (%s); reusing cached copy %s'
              % (last, CACHE), file=sys.stderr)
        ORIGIN[0] = 'cache'
        return CACHE.read_text(encoding='utf-8')
    raise RuntimeError('upstream XMLTV unavailable and no cached copy: %s' % last)


def diyp_day(gid, date, policy):
    """取一个频道的 diyp 节目单并剥水印。失败返回 []，绝不因为一个频道拖垮整份节目单。

    这里不能走 checker.network.cms()：它要求响应里有 `list`（CMS 内容接口的形状），
    而 diyp 节目单接口返回的是 `epg_data`，会被它当成坏响应拒掉。
    """
    from checker.network import fetch
    url = policy['epg_diyp_upstream'].replace('{id}', gid).replace('{date}', date)
    try:
        payload = json.loads(fetch(url, timeout=15)[0])
    except Exception:
        return []
    day = []
    for item in payload.get('epg_data') or []:
        start, stop = str(item.get('start', '')), str(item.get('end', ''))
        title = WATERMARK.sub('', str(item.get('title', ''))).strip()
        if len(start) == 5 and len(stop) == 5 and title:
            day.append((start.replace(':', '') + '00', stop.replace(':', '') + '00', title))
    return day


def xmltv_date(text):
    found = re.search(r'<programme\s+start="(\d{8})', text)
    return found.group(1) if found else time.strftime('%Y%m%d')


def proven_ids(channels, policy):
    """只有身份核验当场能证明的 id 才允许出现在节目单里；没有就空着，绝不现编。"""
    now = int(time.time())
    age = policy['epg_evidence_max_age_days']
    sources = set(policy['epg_sources'])
    return {c['id']: epg_identity(c, now, age, sources) for c in channels}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--upstream', default=None, help='local copy of the upstream XMLTV')
    ap.add_argument('--out', default=str(ROOT / 'output/guide.xml.gz'))
    args = ap.parse_args()

    policy = json.loads((ROOT / 'policy/operations.json').read_text())
    channels = json.loads((ROOT / 'registry/channels.json').read_text())
    by_name = {c['name']: c for c in channels}
    proven = {c['id']: gid for c in channels for gid in [proven_ids([c], policy)[c['id']]] if gid}

    raw = load_upstream(args.upstream, policy['epg_guide_upstream'])

    # 上游 id -> 上游显示名；再由显示名 -> 我们的 epg_id。两层都不能想当然：
    # 上游 id 是 1..101 这种序号，跟本仓库的 CCTV4 毫无关系。
    upstream_name = {}
    for channel_id, block in CHANNEL_BLOCK.findall(raw):
        names = [normalize(n) for n in DISPLAY.findall(block) if normalize(n)]
        if names:
            upstream_name[channel_id] = names[0]

    rename, unmatched = {}, []
    for name in sorted(by_name):
        channel = by_name[name]
        gid = proven.get(channel['id'])
        if not gid:
            continue
        want = [normalize(gid), normalize(name)]
        match = next((cid for cid, theirs in upstream_name.items()
                      if theirs and any(w and same_channel(w, theirs) for w in want)), None)
        if match:
            rename[match] = gid
        else:
            unmatched.append(name)

    # XMLTV 命中的直接重映射；没命中的（地方/港澳台/付费）回问 diyp 并剥水印。
    # 这样 51zmt 两份数据都用上，谁都不用为去水印放弃频道覆盖。
    channel_lines, programme_lines = [], []
    emitted, programmes = set(), 0
    keep = False
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.startswith('<channel '):
            found = re.match(r'<channel id="([^"]*)"', stripped)
            keep = bool(found and found.group(1) in rename)
            if keep:
                gid = rename[found.group(1)]
                channel_lines.append('  <channel id="%s">' % escape(gid))
                channel_lines.append('    <display-name lang="zh">%s</display-name>' % escape(gid))
                channel_lines.append('  </channel>')
                emitted.add(gid)
            continue
        if stripped.startswith('<programme'):
            found = PROGRAMME.match(stripped)
            keep = bool(found and found.group(1) in rename)
            if not keep:
                continue
            programme_lines.append('    ' + re.sub(r'channel="[^"]*"',
                                                   'channel="%s"' % rename[found.group(1)], stripped, count=1))
            programmes += 1
            continue
        if stripped.startswith('<title'):
            if keep:
                title = WATERMARK.sub('', stripped[len('<title>'):-len('</title>')]).strip()
                programme_lines.append('      <title>%s</title>' % title)
            continue
        if stripped == '</programme>':
            if keep:
                programme_lines.append('    </programme>')
            continue
        # tv 开闭标签、doctype、注释一律不透传：输出完全由这里生成，不受上游格式漂移影响。

    # diyp 兜底：只问 XMLTV 没覆盖的频道，按天取，失败就少一个频道的节目单，不报错。
    date = xmltv_date(raw)
    fallback = 0
    if unmatched:
        from concurrent.futures import ThreadPoolExecutor
        def day_for(name):
            channel = by_name[name]
            gid = proven[channel['id']]
            return gid, diyp_day(gid, '%s-%s-%s' % (date[:4], date[4:6], date[6:]), policy)
        with ThreadPoolExecutor(max_workers=3) as pool:
            for gid, day in pool.map(day_for, unmatched):
                if not day:
                    continue
                if gid not in emitted:
                    channel_lines.append('  <channel id="%s">' % escape(gid))
                    channel_lines.append('    <display-name lang="zh">%s</display-name>' % escape(gid))
                    channel_lines.append('  </channel>')
                    emitted.add(gid)
                for start, stop, title in day:
                    programme_lines.append('    <programme start="%s%s +0800" stop="%s%s +0800" channel="%s">'
                                           % (date, start, date, stop, escape(gid)))
                    programme_lines.append('      <title>%s</title>' % escape(title))
                    programme_lines.append('    </programme>')
                    fallback += 1

    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<!DOCTYPE tv SYSTEM "xmltv.dtd">',
           '<tv generator-info-name="WKC guide" source-info-name="51zmt XMLTV + diyp, watermark stripped">']
    out += channel_lines + programme_lines + ['</tv>']
    payload = gzip.compress(('\n'.join(out) + '\n').encode('utf-8'), 9)
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    programmes += fallback

    report = {'checked_at': int(time.time()), 'upstream': policy['epg_guide_upstream'],
              'source': ORIGIN[0],
              'upstream_channels': len(upstream_name), 'xmltv_channels': len(rename),
              'diyp_channels': len(emitted) - len(rename), 'verified_channels': len(proven),
              'programmes': programmes, 'bytes': len(payload),
              'verified_without_guide': sorted({n for n in unmatched
                                                if proven[by_name[n]['id']] not in emitted})}
    (ROOT / 'reports/epg-guide.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print('GUIDE %d channels / %d programmes / %d bytes; %d of %d verified channels covered'
          % (len(emitted), programmes, len(payload), len(emitted), len(proven)))
    print('     xmltv %d + diyp fallback %d; still without a guide: %s'
          % (len(rename), len(emitted) - len(rename),
             ', '.join(report['verified_without_guide'][:12]) or '(none)'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
