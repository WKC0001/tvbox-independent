"""Stage-4 VOD merge: apply recorded visual review decisions to the catalogue.

Inputs:
  input/vod-candidates.json            harvest candidates (>=2 routes, probed)
  frames/vod-index.json                row mapping from vod_review_frames.py
  input/vod-review-decisions.json      {"<cand_idx>": {"verdict":"pass"|"fail", ...}}
  input/approved-catalog.json          current immutable catalogue (8 works)

Output:
  input/approved-catalog.json          merged (new works approved=true only when
                                       verdict=pass); routes joined as $$$ lines;
                                       existing works gain an independent 2nd route
                                       when the same title was found on another
                                       reviewed provider (marked route_review=harvest).
"""
import json,hashlib,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from catalog.ids import work_id
from policy.content_policy import ContentPolicy
POLICY=ContentPolicy(ROOT/'policy/blocked-sources.json')

def ep_name(eps):
    """规范化分集名：保留提供商集名（第01集 / 正片 / HD）。"""
    out=[]
    for e in eps.split('#'):
        if '$' not in e:continue
        n,u=e.split('$',1)
        out.append(f"{n.strip()}${u.strip()}")
    return '#'.join(out)

def main():
    data=json.loads((ROOT/'input/vod-candidates.json').read_text())
    idx=json.loads((ROOT/'frames/vod-index.json').read_text())
    dec=json.loads((ROOT/'input/vod-review-decisions.json').read_text())
    approved=json.loads((ROOT/'input/approved-catalog.json').read_text())
    rows=approved['list']
    have={(v['vod_name'],str(v.get('vod_year',''))) for v in rows}
    # 1) 给现有 8 部补第 2 独立线路（若候选中发现同名同年作品且判定通过）
    by_key={(c['vod_name'],str(c['vod_year'])):c for c in data['candidates']}
    for v in rows:
        c=by_key.get((v['vod_name'],str(v.get('vod_year',''))))
        if not c or dec.get(c.get('cand_idx',''),{}).get('verdict')!='pass':continue
        cur_from=str(v['vod_play_from']).split('$$$');cur_url=str(v['vod_play_url']).split('$$$')
        cur_provs={f.split(':')[0] for f in cur_from}
        added=0
        for r in c['routes']:
            tag=f"审核线路·{r['provider']}"
            provs={f.replace('审核线路·','') for f in cur_from}
            if r['provider'] in provs:continue
            if not (r.get('probe') or {}).get('ok'):continue
            cur_from.append(tag);cur_url.append(ep_name(r['play_url']));added+=1
            if len(cur_from)>=3:break
        if added:
            v['vod_play_from']='$$$'.join(cur_from);v['vod_play_url']='$$$'.join(cur_url)
            v['route_review']='visual-agent'
            print(f"[vodmerge] {v['vod_name']} +{added} 独立线路")
    # 2) 新作品入册
    added=0
    for c in data['candidates']:
        if c.get('frame_probe_failed'):continue
        d=dec.get(c.get('cand_idx',''),{})
        if d.get('verdict')!='pass':continue
        if (c['vod_name'],str(c['vod_year'])) in have:continue
        if len({r['provider'] for r in c['routes']})<2:continue
        ok_routes=[r for r in c['routes'] if (r.get('probe') or {}).get('ok')]
        if len(ok_routes)<2:continue
        # 内容门禁最后防线
        st,why=POLICY.title_state(c['vod_name'],c.get('vod_content',''))
        assert st!='blocked',f"候选污点: {c['vod_name']} {why}"
        for r in ok_routes:
            for ep in r['play_url'].split('#'):
                u=ep.split('$',1)[-1]
                st,_=POLICY.provider_state('',u);assert st!='blocked',f"候选命中封禁域名: {c['vod_name']} {u[:60]}"
        v={'vod_id':'wkc_'+work_id(c['vod_name'],c.get('vod_year',''))[:12],
           'vod_name':c['vod_name'],'vod_year':c.get('vod_year',''),
           'vod_remarks':c.get('vod_remarks',''),'vod_actor':c.get('vod_actor',''),
           'vod_director':c.get('vod_director',''),'vod_pic':c.get('vod_pic',''),
           'vod_content':c.get('vod_content',''),'type_name':c.get('type_name',''),
           'category':c['category'],'approved':True,
           'vod_play_from':'$$$'.join(f"审核线路·{r['provider']}" for r in ok_routes[:3]),
           'vod_play_url':'$$$'.join(ep_name(r['play_url']) for r in ok_routes[:3]),
           'route_review':'visual-agent',
           'review_note':f"目检帧审 {time.strftime('%Y-%m-%d')}；集数 {c['episode_counts']}；{d.get('note','')}"}
        rows.append(v);have.add((c['vod_name'],str(c['vod_year'])));added+=1
        print(f"[vodmerge] + {c['vod_name']}({c.get('vod_year')}) {c['category']} 线路{min(3,len(ok_routes))}")
    # 3) work_id 唯一性 + 分类覆盖
    wids=[work_id(v['vod_name'],v.get('vod_year','')) for v in rows]
    assert len(wids)==len(set(wids)),f"重复 work_id: {[v['vod_name'] for v in rows]}"
    approved['list']=rows
    (ROOT/'input/approved-catalog.json').write_text(json.dumps(approved,ensure_ascii=False,indent=2)+'\n')
    cats={}
    for v in rows:cats[v['category']]=cats.get(v['category'],0)+1
    print(f"[vodmerge] 新增 {added} 部 → 总 {len(rows)} 部；分类 {cats}")
if __name__=='__main__':main()
