"""把一次抽帧 OCR 扫描的结论写进注册表。

扫描本身不在这个仓库里做（`live-source-audit/wkc-pipeline/adscan.py`，需要
rapidocr + ffmpeg），这里只负责把它的产出固化成准入证据，避免结论只留在聊天记录里。

为什么结论必须是三态而不是布尔：没有扫描证据时写 `clean` 等于伪造结论，
插件会把没扫过的源当成无广告排到确认干净的前面。所以缺省是 `pending`。

用法：
  python3 scripts/ingest_ad_scan.py --site cms_bfzyapicom --scan /tmp/adscan-暴風.json
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SITES = ROOT / 'registry/sites.json'
REPORT = ROOT / 'reports/ad-frame-scan.json'


def load(path):
    return json.loads(Path(path).read_text())


def dump(path, obj):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n')


def verdict(scan):
    """adult 也算 flagged：准入条件本来就同时排除博彩广告和成人内容。"""
    value = scan.get('verdict')
    if value in ('ad', 'adult'):
        return 'flagged'
    if value == 'clean':
        return 'clean'
    raise SystemExit('Unusable scan verdict: %r' % value)


def note(scan):
    episode = scan.get('episode') or {}
    return ('local OCR frame scan: %d frames sampled from %s (%s), '
            '%d gambling-ad frames / %d adult frames'
            % (scan.get('sampled', 0), episode.get('title', 'unknown title'),
               episode.get('flag', 'unknown flag'),
               scan.get('ad_frames', 0), scan.get('adult_frames', 0)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--site', required=True)
    ap.add_argument('--scan', required=True)
    args = ap.parse_args()

    scan = load(args.scan)
    if not scan.get('ok'):
        raise SystemExit('Scan did not complete: %s' % scan.get('error', 'unknown error'))
    if scan.get('sampled', 0) < 2:
        raise SystemExit('Only %s frames sampled; too few to call it a verdict' % scan.get('sampled', 0))

    result = verdict(scan)
    sites = load(SITES)
    target = None
    for site in sites:
        if site['id'] == args.site:
            target = site
            break
    if target is None:
        raise SystemExit('Unknown site: %s' % args.site)

    review = target.setdefault('review', {})
    before = review.get('ad_scan')
    review['ad_scan'] = result
    review['ad_frame_scan'] = note(scan)
    review['ad_frame_scan_at'] = scan.get('checked_at') or int(__import__('time').time())
    dump(SITES, sites)

    evidence = load(REPORT) if REPORT.exists() else {}
    evidence[args.site] = {k: v for k, v in scan.items() if k != 'frames'}
    dump(REPORT, evidence)

    print('%s (%s): ad_scan %s -> %s, %d frames, report %s'
          % (args.site, target['config']['name'], before or 'pending', result,
             scan.get('sampled', 0), REPORT.relative_to(ROOT)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
