#!/usr/bin/env python3
"""Ingest a per-route throughput measurement into state/live-measured.json.

排序真正需要回答的是"这条线路跟不跟得上播放"，而不是"它响应快不快"。
本脚本把一次逐线路实测（下载速度比 = 已下载切片的播出时长 ÷ 真实耗时）落到状态文件，
build_multisite.with_measurements() 会把它挂到线路上，checker.television 据此排序。

输入：逐线路结果 JSON（数组，或含 routes/results 数组的对象）。每条至少含 id / ok，
ok 为真时还应含 speed。未注册的 id 一律忽略——不能靠一份测量数据凭空造出线路。
"""
import argparse
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEEP = ('ok', 'speed', 'tier', 'ttfb_ms', 'measured_mbps', 'measured_bps', 'segments',
        'errors', 'sample_seconds', 'played_seconds', 'note', 'media_url')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('source', help='逐线路实测结果 JSON')
    ap.add_argument('--out', default='state/live-measured.json')
    args = ap.parse_args()
    raw = json.loads(Path(args.source).read_text())
    if isinstance(raw, dict):
        raw = raw.get('routes') or raw.get('results') or []
    known = {r['id'] for r in json.loads((ROOT / 'registry/routes.json').read_text())}

    out, unknown = {}, 0
    for item in raw:
        rid = item.get('id')
        if rid not in known:
            unknown += 1
            continue
        out[rid] = {k: item[k] for k in KEEP if k in item}

    path = ROOT / args.out
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'sampled_at': int(time.time()),
                                'metric': 'speed = played segment seconds / wall-clock seconds',
                                'routes': out}, ensure_ascii=False, indent=1) + '\n')
    reachable = sum(1 for v in out.values() if v.get('ok'))
    usable = sum(1 for v in out.values()
                 if v.get('ok') and isinstance(v.get('speed'), (int, float)) and v['speed'] >= 1.0)
    print('INGESTED %d records, %d reachable, %d at or above playback speed (%d unknown ids ignored) -> %s'
          % (len(out), reachable, usable, unknown, args.out))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
