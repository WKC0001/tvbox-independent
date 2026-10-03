"""Stage-3 merge: apply recorded visual review decisions to the live catalogue.

Inputs:
  input/review-live.json            harvest candidates (with probe evidence)
  frames/index.json                 tile index from live_review_frames.py
  input/review-live-decisions.json  {"<i>": "pass"|"fail", ...} from visual review
  input/approved-live.json          existing fixed-review entries (30)

Outputs:
  input/approved-live.json          merged (new entries origin=iptv-org@<commit>,
                                    frame_review_pass=true only where approved)
  input/live-allowed-hosts.json     host allowlist (data-driven, consumed by assemble)
  reports/live-gaps.json            target channels with no usable route
"""
import json,re,sys,time
from pathlib import Path
from urllib.parse import urlsplit
ROOT=Path(__file__).resolve().parents[1]
COMMIT=json.loads((ROOT/'input/review-live.json').read_text())['provenance']['commit']
TARGETS_CCTV=[f'CCTV-{n}' for n in range(1,18)]
SAT=['湖南','浙江','东方','江苏','北京','广东','深圳','山东','安徽','湖北','四川','重庆','河南','河北','江西','辽宁','天津','福建东南','广西','云南','贵州','黑龙江','吉林','山西','陕西','甘肃','青海','宁夏','内蒙古','新疆','西藏','海南','兵团','厦门']
SAT_TARGETS=[s+'卫视' for s in SAT]
HKMO=['凤凰中文','凤凰资讯','凤凰香港','TVB翡翠台','TVB明珠台','港台电视31','港台电视32','澳视澳门','澳门莲花','凤凰卫视香港台']
NEWS=['CGTN英语','CGTN纪录','CGTN西语','CGTN法语','CGTN俄语','CGTN阿拉伯语']
SPORTS=['五星体育','广东体育','BTV体育','福建体育']
KIDS=['卡酷少儿','金鹰卡通','哈哈炫动','优漫卡通','嘉佳卡通']
DOCS=['上海纪实','纪实人文','金鹰纪实','湖南金鹰纪实']
TARGET_NAMES=set(TARGETS_CCTV+SAT_TARGETS+HKMO+NEWS+SPORTS+KIDS+DOCS)

def norm(s):return re.sub(r'\s+','',s).replace('-','').replace('+','plus').lower()
def main():
    rev=json.loads((ROOT/'input/review-live.json').read_text())
    idx=json.loads((ROOT/'frames/index.json').read_text())
    dec=json.loads((ROOT/'input/review-live-decisions.json').read_text())
    approved=json.loads((ROOT/'input/approved-live.json').read_text())
    ok_by_idx={int(k):v for k,v in dec.items() if v.get('verdict')=='pass'}
    have_urls={e['url'] for e in approved}
    per_name={}
    for e in approved:per_name.setdefault(e['name'],[]).append(urlsplit(e['url']).hostname)
    hosts=set()
    for e in approved:
        h=urlsplit(e['url']).hostname or ''
        hosts.add(h)
    added=0
    for r in idx:
        i=int(r['i'])
        if i not in ok_by_idx:continue
        src=rev['channels'].get(f"{r['group']}|{r['name']}")
        cands=[c for c in (src or []) if c['url']==r['url']]
        if not cands:continue
        c=cands[0]
        if c['url'] in have_urls:continue
        nm=r['name']
        if len(per_name.get(nm,[]))>=3:continue  # 每频道至多3条线路
        approved.append({'name':nm,'id':c.get('meta_id',''),'source_group':r['group'],
            'origin':f"iptv-org@{COMMIT[:12]}",'url':c['url'],'headers':c.get('headers',{}),
            'fresh_probe':{'ok':True,'level':c['probe']['level'],'ms':c['probe']['segment_ms']},
            'frame_review_pass':True,'frame_review':'visual-agent',
            'frame_note':'agent visual inspection of tiled frames '+time.strftime('%Y-%m-%d')})
        have_urls.add(c['url']);per_name.setdefault(nm,[]).append(urlsplit(c['url']).hostname)
        h=urlsplit(c['url']).hostname or ''
        hosts.add(h)
        added+=1
    (ROOT/'input/approved-live.json').write_text(json.dumps(approved,ensure_ascii=False,indent=2)+'\n')
    allow=sorted(h for h in hosts if h and not h.replace('.','').isdigit())
    # 允许表按注册域后缀聚合（同 broadcaster 多子域免重复维护）
    bases=set()
    for h in allow:
        parts=h.split('.')
        base='.'.join(parts[-3:]) if h.endswith(('com.cn','net.cn','org.cn','gov.cn','edu.cn')) else '.'.join(parts[-2:])
        bases.add(base)
    (ROOT/'input/live-allowed-hosts.json').write_text(json.dumps({'hosts':sorted(bases),'policy':'broadcaster/verified relay suffixes only; extend only after probe+segment+visual frame review'},ensure_ascii=False,indent=1)+'\n')
    # gaps report：按频道身份匹配（CCTV-N 前缀 / 省名前缀 / 精确名），而非整名等值
    def covered(t):
        m=re.match(r'CCTV-(\d+)$',t)
        if m:
            n=m.group(1)
            return any(re.match(rf'CCTV-{n}(\D|$)',e['name']) for e in approved)
        if t.endswith('卫视'):
            prov=t[:-2]
            return any(e['name'].replace('福建东南','东南').startswith(prov) for e in approved)
        return any(norm(t)==norm(e['name']) or norm(t) in norm(e['name']) for e in approved)
    gaps=[t for t in TARGET_NAMES if not covered(t)]
    (ROOT/'reports/live-gaps.json').write_text(json.dumps({'targets_without_route':gaps,'total_targets':len(TARGET_NAMES)},ensure_ascii=False,indent=1)+'\n')
    print(f"[merge] +{added} routes; allowlist {len(allow)} hosts; gaps {len(gaps)}: {gaps}")
if __name__=='__main__':main()
