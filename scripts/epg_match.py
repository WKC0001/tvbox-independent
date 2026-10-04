"""Verify every television channel against the 51zmt diyp EPG API.

Only mappings that the API itself confirms are recorded: a channel keeps an empty
`epg_id` unless a query returns real programme data whose channel name still looks
like the same channel. Nothing is derived from a naming rule alone.

This source answers unreliably under load (it closes the connection outright, and it
sometimes reports "未提供" for a channel it served a moment earlier), so the matcher is
built to be wrong-proof rather than fast:

  * only a run with zero transport errors and two independent refusals retracts a mapping;
  * anything else keeps what is already stored, and never fabricates a replacement;
  * the registry is only rewritten when its contents actually change, so a throttled run
    cannot become a meaningless release;
  * `--window` walks the registry in slices so a weekly job never bulk-queries the source.

A second kind of source can be registered alongside this one: a whole XMLTV file that is
downloaded once and indexed by display name (`epg_sources.confirm`). It is only ever asked
about channels that carry **no** guide id at all, so a working 51zmt mapping is never
displaced by a later run — and when 51zmt itself goes dark (it does; see epg_sources), the
XMLTV source is what keeps the guide from collapsing to yesterday's cache.
"""
import argparse
import concurrent.futures
import json
import re
import sys
import threading
import time
import unicodedata
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
import epg_sources  # noqa: E402
from verify_live_identity import same_channel  # noqa: E402
API = 'http://epg.51zmt.top:8000/api/diyp/'
SOURCE = 'diyp:51zmt'
PLACEHOLDER = '暂未提供节目预告信息'
REFUSAL = '未提供'
CURSOR = ROOT / 'state/epg-cursor.json'
CN = timezone(timedelta(hours=8))
SUFFIX = re.compile(r'(高清|标清|超清|蓝光|4K|8K|HD|FHD|SD|PLUS)$', re.I)
STATION = re.compile(r'[a-z]{2,}\d', re.I)
CACHE = {}
LOCK = threading.Lock()


def norm(value):
    text = unicodedata.normalize('NFKC', str(value))
    text = re.sub(r'[（(].*?[)）]', '', text)
    text = re.sub(r'[\s\-_.·、,，]', '', text)
    text = SUFFIX.sub('', text)
    return text.casefold()


def candidates(name):
    """Ordered guesses to try against the API; the first confirmed one wins."""
    out = []

    def add(value):
        value = str(value).strip()
        if value and value not in out:
            out.append(value)

    raw = unicodedata.normalize('NFKC', str(name)).strip()
    # The API's own ids drop the separator ("CCTV1", never "CCTV-1"), so the hyphenated spelling is
    # a guaranteed miss. Try the joined form first instead of paying for a request we know fails.
    joined = re.fullmatch(r'([A-Za-z]{2,})[-\s]+(\d+\+?)', raw)
    if joined:
        add(joined.group(1) + joined.group(2))
    add(raw)
    base = re.sub(r'[（(].*?[)）]', '', raw).strip()
    add(base)
    compact = re.sub(r'[\s\-]+', '', base)
    add(compact)
    upper = compact.upper()
    add(upper)
    m = re.fullmatch(r'(CCTV|CGTN|CETV)[-\s]*(\d+\+?)', upper)
    if m:
        add(m.group(1) + m.group(2))
    m = re.fullmatch(r'([A-Z]+)-?(\d+\+?)', upper)
    if m:
        add(m.group(1) + m.group(2))
    add(upper.replace('+', 'P'))
    add(re.sub(r'(综合|新闻|经济|国际|中文|English)$', '', compact, flags=re.I))
    m = re.match(r'^(.*?)(卫视)$', base)
    if m:
        add(m.group(1) + '卫视')
    return out


def query(identifier, date, retries=2):
    # The cache key is the identifier actually sent. Two spellings that normalize alike can
    # resolve differently ("CCTV-1" is unknown while "CCTV1" is CCTV-1综合), so a normalized
    # key would let a miss poison the candidate that would have hit.
    key = (str(identifier).strip().casefold(), date)
    with LOCK:
        if key in CACHE:
            return CACHE[key]
    url = API + '?' + urllib.parse.urlencode({'ch': identifier, 'date': date})
    payload = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(url, timeout=20) as response:
                payload = json.loads(response.read().decode('utf8', 'replace'))
            break
        except Exception:
            if attempt == retries:
                raise
            time.sleep(1.5 * (attempt + 1))
    with LOCK:
        CACHE[key] = payload
    return payload


def confirmed(identifier, payload, name):
    if not isinstance(payload, dict):
        return None
    served = str(payload.get('channel_name') or '')
    rows = payload.get('epg_data') or []
    if served in ('', REFUSAL) or not rows:
        return None
    real = [row for row in rows if PLACEHOLDER not in str(row.get('title', ''))]
    if not real:
        return None
    ours, theirs = norm(name), norm(served)
    if not ours or not theirs:
        return None
    if ours.startswith(theirs) or theirs.startswith(ours):
        return {'id': identifier, 'served_name': served, 'programmes': len(real)}
    # Some entries are served under a renamed label (CCTV16 -> "CCTV奥林匹克频道").
    # Accept only when the identifier itself is this channel's own code, so a
    # coincidental programme name can never bind two different stations.
    if norm(identifier) == ours and (STATION.search(identifier) or len(ours) >= 4):
        return {'id': identifier, 'served_name': served, 'programmes': len(real)}
    return None


def xmltv_claims(loaded, channels, log=None):
    """第二源的认领表：一个上游频道只允许被一个本仓库频道认领。

    不这样约束就会串台。上游的频道名往往很粗，epg.pw 里一条「新疆卫视」能同时
    匹配上维吾尔语、哈萨克语、少儿三个不同频道，「CCTV中学生」那条更是被 CCTV+1、
    CCTV+2、CCTV-Health、CCTV新影-中学生 一起认领。让它们各自拿走同一个 id，播放器
    里就会互相串节目——点开健康频道看到中学生节目，而且没人会报，因为它"有节目单"。

    所以多对一的认领一律作废：宁可这几个频道暂时没有节目单，也不能让它们互串。
    """
    claims, contested = {}, []
    pending = {}
    for channel in channels:
        if channel.get('epg_id'):
            continue
        for up, index in loaded:
            hit = epg_sources.confirm(up, index, channel['name'], norm, same_channel)
            if not hit:
                continue
            key = (up['name'], hit['id'])
            pending.setdefault(key, {'up': up, 'hit': hit, 'ids': []})
            pending[key]['ids'].append(channel['id'])
            break
    for key, entry in pending.items():
        if len(entry['ids']) == 1:
            claims[entry['ids'][0]] = entry
        else:
            contested.append({'upstream': key[0], 'upstream_id': key[1],
                              'served_name': entry['hit']['served_name'],
                              'claimed_by': entry['ids']})
    if log and contested:
        print('%d upstream channels were claimed by more than one local channel; ignored'
              % len(contested), file=log)
    return claims, contested


def resolve(channel, date, retries, xmltv=None, claims=None):
    """Probe one channel. Returns the mapping, or a verdict that never overstates what was seen.

    `xmltv` is the optional second source: a list of (upstream, index) pairs already
    downloaded. `claims` is the one-to-one table built from it by `xmltv_claims`. Both are
    consulted only when this channel has no guide id of its own, so the second source fills
    gaps instead of competing with a mapping the diyp source already proved.
    """
    name = channel['name']
    guesses = candidates(name)
    attempts = []
    failed = 0

    if claims and not channel.get('epg_id'):
        entry = claims.get(channel['id'])
        if entry:
            up, hit = entry['up'], entry['hit']
            attempts.append({'id': hit['id'], 'result': 'served=' + hit['served_name']})
            return {'channel_id': channel['id'], 'name': name, 'matched': hit,
                    'attempts': attempts, 'outcome': 'confirmed',
                    'source': 'xmltv:' + up['name']}
        for up, _index in xmltv or ():
            attempts.append({'id': up['name'], 'result': 'no unique match in ' + up['name']})

    def ask(identifier, label=''):
        """Return the mapping, or 'no' / 'unknown'."""
        nonlocal failed
        try:
            payload = query(identifier, date, retries)
        except Exception as error:
            failed += 1
            attempts.append({'id': identifier, 'result': label + 'error: ' + type(error).__name__})
            return 'unknown'
        hit = confirmed(identifier, payload, name)
        if hit:
            return hit
        served = str((payload or {}).get('channel_name') or REFUSAL)
        attempts.append({'id': identifier, 'result': label + 'served=' + served})
        return 'no'

    for identifier in guesses:
        hit = ask(identifier)
        if hit not in ('no', 'unknown'):
            return {'channel_id': channel['id'], 'name': name, 'matched': hit, 'attempts': attempts,
                    'outcome': 'confirmed'}
    # One refusal is not proof of absence: this API is known to refuse channels it just served,
    # so re-ask the strongest spelling before we consider retiring a mapping.
    if guesses:
        hit = ask(guesses[0], label='recheck ')
        if hit not in ('no', 'unknown'):
            return {'channel_id': channel['id'], 'name': name, 'matched': hit, 'attempts': attempts,
                    'outcome': 'confirmed'}
    answers = len(attempts) - failed
    if not attempts or failed == len(attempts):
        outcome = 'unanswered'
    elif failed == 0 and answers >= 2:
        outcome = 'retracted'
    else:
        outcome = 'contaminated'
    return {'channel_id': channel['id'], 'name': name, 'matched': None, 'attempts': attempts, 'outcome': outcome}


def dedupe_registry(channels, log=None):
    """一个节目单 id 只能归一个频道；抢到同一个 id 的，只留名字真正对得上的那个。

    上游的频道名往往很粗：epg.pw 里一个「新疆卫视」底下就挂着维吾尔语、哈萨克语、
    少儿三个不同频道，「CCTV中学生」那一条甚至被 CCTV+1 / CCTV+2 / CCTV-Health /
    CCTV新影-中学生 一起认领。弱匹配放行这些，结果就是节目单串台——点开健康频道
    看到的是中学生节目，这比"没有节目单"更糟，而且是安静地错，没人会报。

    裁决办法：名字与上游返回的名字完全对得上的那个留下；对不上（或者有两个都
    对得上）就全部作废，宁缺勿错。作废记进 `epg_conflicts`，不静默丢掉。
    """
    groups = {}
    for channel in channels:
        gid = channel.get('epg_id')
        if gid:
            groups.setdefault((channel.get('epg_source', ''), gid), []).append(channel)
    conflicts = []
    for (source, gid), group in groups.items():
        if len(group) == 1:
            continue
        exact = [c for c in group
                 if norm(c['name']) and norm(c.get('epg_served_name', ''))
                 and norm(c['name']) == norm(c['epg_served_name'])]
        winner = exact[0] if len(exact) == 1 else None
        for channel in group:
            if channel is winner:
                continue
            conflicts.append({'name': channel['name'], 'epg_id': gid, 'source': source,
                              'served_name': channel.get('epg_served_name', ''),
                              'kept_by': winner['name'] if winner else ''})
            channel['epg_id'] = ''
            channel['epg_source'] = ''
            channel.pop('epg_checked_at', None)
            channel.pop('epg_served_name', None)
    if log and conflicts:
        print('dropped %d channels that shared a guide id with another channel' % len(conflicts),
              file=log)
    return conflicts


def targets_for(channels, args):
    """Walk the registry in rotating slices so no single run bulk-queries the source."""
    ordered = list(channels)
    if args.window and args.window < len(ordered):
        start = 0
        if CURSOR.exists():
            try:
                start = int(json.loads(CURSOR.read_text()).get('next', 0)) % len(ordered)
            except Exception:
                start = 0
        ordered = (ordered + ordered)[start:start + args.window]
        CURSOR.parent.mkdir(parents=True, exist_ok=True)
        CURSOR.write_text(json.dumps({'next': (start + args.window) % len(channels),
                                      'window': args.window, 'updated_at': int(time.time())},
                                     ensure_ascii=False, indent=2) + '\n')
    return [c for c in ordered if not (args.only_unmatched and c.get('epg_id'))]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--date', default=datetime.now(CN).strftime('%Y-%m-%d'))
    ap.add_argument('--workers', type=int, default=8)
    ap.add_argument('--limit', type=int, default=0, help='only inspect the first N channels')
    ap.add_argument('--window', type=int, default=0,
                    help='rotate through N channels per run, resuming from state/epg-cursor.json')
    ap.add_argument('--only-unmatched', action='store_true', help='skip channels that already carry an epg_id')
    ap.add_argument('--retries', type=int, default=2)
    args = ap.parse_args()

    path = ROOT / 'registry/channels.json'
    original = path.read_text()
    channels = json.loads(original)
    targets = targets_for(channels, args)
    if args.limit:
        targets = targets[:args.limit]

    # The XMLTV sources are whole-file downloads, so fetch each one once and index it here
    # rather than per channel. A source that cannot be fetched is skipped, not fatal: the
    # diyp probe below still runs, and "could not reach it" is never recorded as "no such
    # channel" — that distinction is the whole point of the outcome vocabulary below.
    policy = json.loads((ROOT / 'policy/operations.json').read_text())
    xmltv = []
    for spec in policy.get('epg_sources', []):
        kind, _, who = str(spec).partition(':')
        if kind != 'xmltv':
            continue
        up = next((u for u in epg_sources.upstreams(policy) if u['name'] == who), None)
        if up is None:
            continue
        try:
            text, origin = epg_sources.load(up, log=sys.stderr)
            xmltv.append((up, epg_sources.index(text)))
            print(f'xmltv source {who}: {origin}, {len(epg_sources.index(text)["names"])} channels')
        except Exception as error:
            print(f'xmltv source {who} skipped: {error}', file=sys.stderr)

    print(f'inspecting {len(targets)} of {len(channels)} channels against {API} (date {args.date})')

    # 认领表要在并发之前算好：一个上游频道归谁是全局判断，不能在各个线程里各判各的。
    claims, contested = xmltv_claims(xmltv, channels, log=sys.stderr)

    started = int(time.time())
    results = []
    with concurrent.futures.ThreadPoolExecutor(args.workers) as pool:
        futures = [pool.submit(resolve, c, args.date, args.retries, xmltv, claims) for c in targets]
        for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
            results.append(future.result())
            if index % 25 == 0 or index == len(futures):
                hits = sum(1 for r in results if r['matched'])
                print(f'  {index}/{len(futures)} checked, {hits} confirmed', flush=True)

    by_id = {r['channel_id']: r for r in results}
    counts = {'confirmed': 0, 'retracted': 0, 'unanswered': 0, 'contaminated': 0}
    for channel in channels:
        result = by_id.get(channel['id'])
        if result is None:
            continue
        counts[result['outcome']] += 1
        if result['outcome'] == 'confirmed':
            channel['epg_id'] = result['matched']['id']
            channel['epg_source'] = result.get('source', SOURCE)
            channel['epg_checked_at'] = started
            # 记下上游自己叫这个频道什么。日后若干个频道抢到同一个 id 时，只有这个
            # 名字能证明"这条确实是它的"，没有它就只能作废。
            channel['epg_served_name'] = result['matched'].get('served_name', '')
        elif result['outcome'] == 'retracted':
            channel['epg_id'] = ''
            channel['epg_source'] = ''
            channel.pop('epg_checked_at', None)
        # Every other verdict keeps whatever is already stored. An unreachable or contradictory
        # source is not evidence that a working mapping is wrong, and the build's freshness
        # window is what eventually retires something the source no longer serves.

    # 清算放在写回之前：一个上游 id 被好几个频道认领时只留一个，其余作废。
    conflicts = dedupe_registry(channels, log=sys.stderr)

    updated = json.dumps(channels, ensure_ascii=False, indent=2) + '\n'
    if updated == original:
        print(f'checked {len(results)}: {counts}; guide registry unchanged, nothing to publish')
        return
    path.write_text(updated)
    report = {
        'checked_at': started,
        'date': args.date,
        'api': API,
        'source': SOURCE,
        'inspected': len(results),
        **counts,
        'channels_with_epg_id': sum(1 for c in channels if c.get('epg_id')),
        'shared_id_dropped': conflicts,
        'contested_upstream_channels': contested,
        'results': sorted(results, key=lambda r: (r['outcome'] != 'confirmed', r['name'])),
    }
    (ROOT / 'reports/epg-match.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(f'checked {len(results)}: {counts}; registry now carries '
          f'{report["channels_with_epg_id"]} confirmed guide ids')


if __name__ == '__main__':
    main()
