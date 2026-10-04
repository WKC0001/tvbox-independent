"""Measure how fast each CMS provider answers the request the home screen actually makes.

首页调的是 `ac=detail&pg=1`（首页片单），而 `state/provider-audit.json` 里的 `latency_ms`
测的是 `ac=list`（分类表）—— 两者根本不是一个接口，实测也不相关：

    p2100    latency_ms=954   首页 ac=detail 实测 5080ms
    bfzyapi  latency_ms=1372  首页 ac=detail 实测 1770ms

按 latency_ms 排序会把最慢的那家排在第一位，而首页是"先答者优先"，
于是每次冷启动都在等最慢的那家。这份测量就是用来纠正这个排序的。

只读网络、只写 state/home-latency.json，不动注册表、不动健康状态、不动准入结论。
"""
import argparse
import concurrent.futures as cf
import json
import time
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from checker.network import cms


def probe(site, samples):
    url = site['config']['api']
    readings = []
    error = ''
    for _ in range(samples):
        try:
            body, ms = cms(url, ac='detail', pg=1)
            if not body.get('list'):
                raise ValueError('empty home list')
            readings.append(ms)
        except Exception as exc:
            error = str(exc)[:200]
            break
    out = {'id': site['id'], 'name': site['config']['name'], 'samples': len(readings)}
    if readings:
        # 取最小值而不是平均值：我们要的是"这家正常情况下能多快"，
        # 一次偶发抖动不该把它永久排到最后。
        out['home_ms'] = min(readings)
        out['readings'] = readings
    else:
        out['error'] = error or 'no successful sample'
    print('HOME', out['name'], out.get('home_ms', '-'), out.get('error', ''), flush=True)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--samples', type=int, default=2)
    ap.add_argument('--workers', type=int, default=4)
    args = ap.parse_args()
    sites = json.loads((ROOT / 'registry/sites.json').read_text())
    candidates = [s for s in sites if s['kind'] == 'cms' and s['status'] != 'excluded']
    with cf.ThreadPoolExecutor(args.workers) as ex:
        results = list(ex.map(lambda s: probe(s, args.samples), candidates))
    data = {'checked_at': int(time.time()), 'samples_per_provider': args.samples,
            'providers': {r['id']: r for r in results}}
    path = ROOT / 'state/home-latency.json'
    staging = path.with_suffix('.tmp')
    staging.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    staging.replace(path)
    ranked = sorted((r for r in results if 'home_ms' in r), key=lambda r: r['home_ms'])
    print('MEASURED', len(ranked), 'of', len(results), 'providers')
    for r in ranked:
        print('  %6d ms  %s' % (r['home_ms'], r['name']))


if __name__ == '__main__':
    main()
