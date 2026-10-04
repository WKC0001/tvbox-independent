"""广告结论必须要有抽帧证据撑着，没有就退回 pending。

为什么需要这一道
----------------
`ad_scan` 决定点播源在"点我切源"里的排序：确认干净的排在前面，没扫过的排在后面。
所以写一个 `clean` 就是在替用户做判断——而这个判断必须能翻出当时那次扫描的记录。

实测发现 6 家正在发布给用户的 CMS 里，飘零、360、量子三家在 registry 里写着
`clean`，但 `reports/ad-frame-scan.json` 里**根本没有它们的扫描记录**。也就是说
一半的源带着一句没有出处的"无广告"，排在另外三家真扫过的旁边——这正好是
`ingest_ad_scan.py` 开头明令禁止的事（"没有扫描证据时写 clean 等于伪造结论"），
只是之前没人回头核对过。

这里做的事很直白：结论要能在证据报告里翻出对应条目，且采样帧数达到下限，否则
退回 `pending`。宁可这几家排在后面，也不能让一个来路不明的"干净"替用户拍板。

用法：
  python3 scripts/verify_ad_evidence.py            # 检查并把不合规的结论退回 pending
  python3 scripts/verify_ad_evidence.py --check    # 只检查，不改动注册表
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITES = ROOT / 'registry/sites.json'
SCAN = ROOT / 'reports/ad-frame-scan.json'
POLICY = ROOT / 'policy/operations.json'
REPORT = ROOT / 'reports/ad-evidence.json'


def load(path, fallback=None):
    return json.loads(Path(path).read_text()) if Path(path).exists() else (fallback or {})


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--check', action='store_true', help='只报告，不写回注册表')
    ap.add_argument('--min-frames', type=int, default=0,
                    help='覆盖 policy 里的 ad_scan_min_frames')
    args = ap.parse_args()

    policy = load(POLICY)
    floor = args.min_frames or int(policy.get('ad_scan_min_frames', 6) or 6)
    sites = load(SITES, [])
    evidence = load(SCAN, {})

    kept, demoted, missing = [], [], []
    for site in sites:
        review = site.setdefault('review', {})
        claimed = review.get('ad_scan')
        if not claimed or claimed == 'pending':
            continue
        scan = evidence.get(site['id'])
        if not isinstance(scan, dict):
            demoted.append({'id': site['id'], 'name': site.get('config', {}).get('name', ''),
                            'claimed': claimed, 'reason': 'no frame-scan record exists'})
            review['ad_scan'] = 'pending'
            review['ad_frame_scan'] = ''
            review['ad_scan_demoted_at'] = int(time.time())
            continue
        sampled = int(scan.get('sampled', 0) or 0)
        if sampled < floor:
            demoted.append({'id': site['id'], 'name': site.get('config', {}).get('name', ''),
                            'claimed': claimed,
                            'reason': 'only %d frames sampled, floor is %d' % (sampled, floor)})
            review['ad_scan'] = 'pending'
            review['ad_frame_scan'] = ''
            review['ad_scan_demoted_at'] = int(time.time())
            continue
        if not scan.get('ok'):
            demoted.append({'id': site['id'], 'name': site.get('config', {}).get('name', ''),
                            'claimed': claimed, 'reason': 'scan did not complete'})
            review['ad_scan'] = 'pending'
            review['ad_scan_demoted_at'] = int(time.time())
            continue
        kept.append({'id': site['id'], 'name': site.get('config', {}).get('name', ''),
                     'verdict': claimed, 'frames': sampled})

    # 证据报告里记着、注册表里却挂不上的站点，也如实报出来：说明有扫描白做了。
    known = {s['id'] for s in sites}
    for site_id in sorted(evidence):
        if site_id not in known:
            missing.append(site_id)

    report = {'checked_at': int(time.time()), 'min_frames': floor,
              'with_evidence': kept, 'demoted': demoted,
              'orphan_evidence': missing,
              'checked_sites': len(sites)}
    if not args.check:
        Path(SITES).write_text(json.dumps(sites, ensure_ascii=False, indent=2) + '\n')
    Path(REPORT).parent.mkdir(parents=True, exist_ok=True)
    Path(REPORT).write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')

    print('ad evidence: %d kept, %d demoted to pending, %d orphan records'
          % (len(kept), len(demoted), len(missing)))
    for row in demoted:
        print('   demoted %s (%s): was %s, %s' % (row['id'], row['name'], row['claimed'],
                                                  row['reason']))
    for row in missing:
        print('   orphan scan record with no registry site: %s' % row, file=sys.stderr)
    if demoted and args.check:
        # 检查模式下发现问题要让人知道，但不能靠退出码把流水线打断在半路。
        print('   run without --check to write the demotions back', file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
