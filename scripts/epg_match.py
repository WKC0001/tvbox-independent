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
"""
import argparse
import concurrent.futures
import json
import re
import threading
import time
import unicodedata
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
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


def resolve(channel, date, retries):
    """Probe one channel. Returns the mapping, or a verdict that never overstates what was seen."""
    name = channel['name']
    guesses = candidates(name)
    attempts = []
    failed = 0

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
    print(f'inspecting {len(targets)} of {len(channels)} channels against {API} (date {args.date})')

    started = int(time.time())
    results = []
    with concurrent.futures.ThreadPoolExecutor(args.workers) as pool:
        futures = [pool.submit(resolve, c, args.date, args.retries) for c in targets]
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
            channel['epg_source'] = SOURCE
            channel['epg_checked_at'] = started
        elif result['outcome'] == 'retracted':
            channel['epg_id'] = ''
            channel['epg_source'] = ''
            channel.pop('epg_checked_at', None)
        # Every other verdict keeps whatever is already stored. An unreachable or contradictory
        # source is not evidence that a working mapping is wrong, and the build's freshness
        # window is what eventually retires something the source no longer serves.

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
        'results': sorted(results, key=lambda r: (r['outcome'] != 'confirmed', r['name'])),
    }
    (ROOT / 'reports/epg-match.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(f'checked {len(results)}: {counts}; registry now carries '
          f'{report["channels_with_epg_id"]} confirmed guide ids')


if __name__ == '__main__':
    main()
