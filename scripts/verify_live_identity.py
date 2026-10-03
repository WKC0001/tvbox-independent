#!/usr/bin/env python3
"""Reject live routes that answer a request for one channel with a different one.

A free/ad-supported aggregator can hand back an advertisement loop instead of the channel:
requesting `.../live/dfwshd.m3u8` returns a redirect into `.../applive/mkt.m3u8`, and `mkt`
turned out to be a home-shopping feed (麦可通). Every byte of that is valid HLS, so the
reachability probe in checker.network.media passes and the ad source wins the latency
ranking in checker.television.playlist. Reachability cannot separate the two; identity can.

The check follows the redirect chain and requires the served playlist to still denote the
requested channel. Route slugs carry the channel (`dfwshd` -> `dfws`, `cctv5hd` -> `cctv5`),
which is enough to tell "still the same channel" from "someone else's channel". Routes whose
slugs name nothing (opaque uuids, bare ids) are unverifiable and are never condemned.

A single response is not evidence: the sampled source answered correctly about one time in
five, so a route is only quarantined when mismatches outnumber consistencies across several
independent requests. Being unreachable never counts against a route here.
"""
import argparse
import concurrent.futures as cf
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import parse_qsl, urljoin, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

USER_AGENT = 'okhttp/4.12.0'
SUFFIXES = ('hd', 'sd', 'fhd', 'uhd', 'plus')
# Generated identifiers carry no channel meaning and must never be read as one. Short numeric
# ids do: the sampled ad lineup serves `107` and `102`, so only long digit runs are opaque.
OPAQUE = (re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'),
          re.compile(r'^[0-9a-f]{16,}$'), re.compile(r'^\d{8,}$'))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def slug(url):
    path = urlsplit(url).path.rstrip('/')
    name = path.rsplit('/', 1)[-1]
    return name.rsplit('.', 1)[0].lower() if '.' in name else name.lower()


def normalize(value):
    """`dfwshd` and `dfws` are the same channel; `cctv1hd` and `cctv1` are the same channel."""
    out = value
    changed = True
    while changed and len(out) > 3:
        changed = False
        for suffix in SUFFIXES:
            if out.endswith(suffix) and len(out) - len(suffix) >= 3:
                out = out[:-len(suffix)]
                changed = True
    return out


def judgeable(value):
    return bool(value) and len(value) >= 2 and not any(p.match(value) for p in OPAQUE)


def same_channel(left, right):
    """Names for one channel differ between providers: `cwjd` arrives as `CBN_XP_cwjdHD`."""
    if left == right:
        return True
    if len(left) >= 4 and left in right:
        return True
    if len(right) >= 4 and right in left:
        return True
    return len(left) >= 3 and len(right) >= 3 and (left.startswith(right) or right.startswith(left))


def trace(url, headers=None, max_hops=5, timeout=12):
    """Follow redirects by hand so the hop where the channel changes stays visible."""
    if urlsplit(url).scheme not in ('http', 'https'):
        return None, 'non-http transport'
    opener = urllib.request.build_opener(_NoRedirect)
    chain, current = [], url
    for _ in range(max_hops):
        request = urllib.request.Request(current, headers={'User-Agent': USER_AGENT, **(headers or {})})
        try:
            with opener.open(request, timeout=timeout) as response:
                return {'served': current, 'body': response.read(2048), 'chain': chain}, ''
        except urllib.error.HTTPError as error:
            if error.code in (301, 302, 303, 307, 308):
                location = error.headers.get('Location')
                if not location:
                    return {'served': current, 'body': b'', 'chain': chain}, 'redirect without location'
                current = urljoin(current, location)
                chain.append(current)
                continue
            return None, 'HTTP %d' % error.code
        except Exception as error:  # noqa: BLE001 - any transport failure is "no answer"
            return None, type(error).__name__
    return None, 'too many redirects'


def identity_tokens(url):
    """Every spelling of the requested channel that a route may express.

    Some routes put the channel in the path (`live/dfwshd.m3u8`), others keep a generic path
    and name it in the query (`gslb/zbdq5.m3u8?id=cctv8k`). Comparing only the path would call
    the second kind a mismatch, so both are collected and the served playlist only has to
    agree with one of them.
    """
    parts = urlsplit(url)
    tokens = [normalize(slug(url))]
    for _, value in parse_qsl(parts.query, keep_blank_values=True):
        base = value.rsplit('/', 1)[-1]
        base = base.rsplit('.', 1)[0] if '.' in base else base
        tokens.append(normalize(base.lower()))
    return [t for t in dict.fromkeys(tokens) if judgeable(t)]


def sample(url, headers=None):
    result, error = trace(url, headers)
    if result is None:
        return {'status': 'unanswered', 'detail': error, 'requested': identity_tokens(url), 'served': None}
    requested = identity_tokens(url)
    served = normalize(slug(result['served']))
    if not requested or not judgeable(served):
        return {'status': 'unverifiable', 'requested': requested, 'served': served, 'detail': ''}
    ok = any(same_channel(token, served) for token in requested)
    return {'status': 'consistent' if ok else 'mismatch', 'requested': requested, 'served': served,
            'detail': 'served ' + served if not ok else ''}


def screen_verdict(samples):
    """Does this route ever answer with something other than the requested channel?"""
    statuses = {item['status'] for item in samples}
    if 'mismatch' in statuses:
        return 'suspect'
    if 'consistent' in statuses:
        return 'clean'
    return 'unknown'


def filler_map(results):
    """Identities that answer for several unrelated requests are filler, not a channel.

    `mkt` is served for 东方卫视, 湖南卫视, CCTV-5 and dozens more: no real channel does that.
    A provider that merely renames a channel answers for that one channel only (`jingjishenghuo`
    for 河北经济), so renaming never looks like filler. Error states never serve television.
    """
    seen = {}
    for item in results:
        for sample_row in item['samples']:
            if sample_row['status'] != 'mismatch' or not sample_row.get('served'):
                continue
            seen.setdefault(sample_row['served'], set()).add(tuple(sample_row.get('requested') or ()))
    return {name: sorted(requests) for name, requests in seen.items() if len(requests) >= 2 and requests}


def filler_hits(samples, fillers):
    return sum(1 for s in samples if s.get('served') in fillers or str(s.get('served')).startswith('error'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--samples', type=int, default=5)
    parser.add_argument('--confirm', type=int, default=8,
                        help='extra requests used to re-test every candidate before it is condemned')
    parser.add_argument('--workers', type=int, default=6)
    parser.add_argument('--limit', type=int, default=0)
    parser.add_argument('--group', default='', help='only routes referenced by channels in this group')
    parser.add_argument('--apply', action='store_true', help='write the registry and health state')
    args = parser.parse_args()

    channels = json.loads((ROOT / 'registry/channels.json').read_text())
    routes = json.loads((ROOT / 'registry/routes.json').read_text())
    index = {r['id']: r for r in routes}

    wanted = None
    if args.group:
        wanted = {rid for ch in channels if ch.get('group') == args.group for rid in ch['routes']}

    targets = []
    for route in routes:
        if route.get('review') == 'quarantined':
            continue
        if wanted is not None and route['id'] not in wanted:
            continue
        if urlsplit(route['url']).scheme not in ('http', 'https'):
            continue
        targets.append(route)
    if args.limit:
        targets = targets[:args.limit]

    def measure(route, count):
        samples = [sample(route['url'], route.get('headers') or {}) for _ in range(count)]
        return {'id': route['id'], 'url': route['url'], 'samples': samples,
                'verdict': screen_verdict(samples)}

    results = []
    with cf.ThreadPoolExecutor(args.workers) as pool:
        for i, item in enumerate(pool.map(lambda r: measure(r, args.samples), targets), 1):
            results.append(item)
            if i % 50 == 0:
                print('screened', i, len(targets), flush=True)

    # Only identities that answered for several unrelated requests are treated as filler, so a
    # provider that simply uses a longer name for the same channel is never condemned.
    fillers = filler_map(results)
    print('filler identities:', sorted(fillers))

    # Every suspect is re-tested before it is condemned: the source answers correctly often
    # enough that a short screening run can catch a good route on a bad moment.
    suspects = [r for r in results if r['verdict'] == 'suspect']
    confirmed = {}
    if suspects and args.confirm:
        print('re-testing', len(suspects), 'suspects with', args.confirm, 'more requests', flush=True)
        with cf.ThreadPoolExecutor(args.workers) as pool:
            for item in pool.map(lambda r: measure(r, args.confirm), suspects):
                confirmed[item['id']] = item

    def proof(route_id):
        return (confirmed.get(route_id) or next(r for r in results if r['id'] == route_id))['samples']

    condemned, watched = [], []
    for item in results:
        if item['verdict'] != 'suspect':
            item['verdict'] = 'ok' if item['verdict'] == 'clean' else 'unknown'
            continue
        second = proof(item['id'])
        hits = filler_hits(second, fillers)
        # A majority of the re-tests must land on a filler identity before a route is retired.
        if hits * 2 > len(second):
            item['verdict'] = 'quarantine'
            condemned.append(item)
        else:
            item['verdict'] = 'watch'
            watched.append(item)
    print('routes checked', len(results), '| suspects', len(suspects),
          '| quarantine', len(condemned), '| watch', len(watched))
    for item in condemned[:25]:
        served = sorted({s.get('served') for s in proof(item['id']) if s.get('served')})
        print('  QUARANTINE', item['id'], item['url'][:66], '->', served)

    report = {
        'checked_at': int(time.time()),
        'samples_per_route': args.samples,
        'confirm_samples': args.confirm,
        'routes_checked': len(results),
        'filler_identities': {name: len(requests) for name, requests in sorted(fillers.items())},
        'quarantined': [r['id'] for r in condemned],
        'watch': [r['id'] for r in watched],
        'results': sorted(results, key=lambda r: (r['verdict'] != 'quarantine', r['id'])),
        'confirmation': [confirmed[r['id']] for r in condemned if r['id'] in confirmed],
    }

    if not args.apply:
        print('dry run; pass --apply to write registry/routes.json, state and the report')
        return

    def evidence(route_id):
        rows = proof(route_id)
        served = sorted({s.get('served') for s in rows if s.get('served')})
        requested = next((s.get('requested') for s in rows if s.get('requested')), [])
        return requested, served

    for item in condemned:
        route = index[item['id']]
        requested, served = evidence(item['id'])
        route['review'] = 'quarantined'
        route['quarantine_reason'] = 'channel identity mismatch: requested %s, served %s (%d/%d re-tests)' % (
            '/'.join(requested) or '?', '/'.join(served) or 'unknown', args.confirm, args.confirm)

    (ROOT / 'registry/routes.json').write_text(json.dumps(routes, ensure_ascii=False, indent=2) + '\n')
    (ROOT / 'reports/live-identity.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')

    if condemned:
        from checker import health
        state_path = ROOT / 'state/multisite-health.json'
        state = health.load_state(state_path)
        for item in condemned:
            _, served = evidence(item['id'])
            health.update(state, item['id'], 'global', False, pollution=True,
                          reason='channel identity mismatch (served ' + '/'.join(served) + ')')
        health.save_state(state_path, state)
    print('applied; quarantined', len(condemned), 'routes')


if __name__ == '__main__':
    main()
