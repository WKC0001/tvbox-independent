"""Stage-4 VOD harvest: curated title pool -> reviewed-provider discovery.

For each pool title, queries the reviewed CMS provider allowlist, keeps works
found in >=2 independent providers (>=2 routes requirement), verifies episode
numbering consistency, probes first-episode playability, and samples first-
episode frames (3s/60s/300s/900s/1800s) for visual review.

Outputs:
  input/vod-candidates.json   candidates with full evidence (never auto-published)
  reports/vod-gaps.json       pool titles not admitted (not found / <2 routes)
  frames/vod-XXXXX.jpg        per-work 5-timestamp frame strips for review
"""
import concurrent.futures as cf,json,re,subprocess,sys,time,unicodedata
from pathlib import Path
from urllib.parse import urljoin,urlsplit,quote
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from policy.content_policy import ContentPolicy
POLICY=ContentPolicy(ROOT/'policy/blocked-sources.json')
UA={'User-Agent':'okhttp/3.15'}
PROBE_TIMEOUT=12

# 提供商允许表（来源可追溯：均在此前项目经过内容白名单审核；此处仅按片名精确检索，不做开放浏览）
PROVIDERS=[
 ('360','https://360zy.com/api.php/provide/vod/'),
 ('量子','https://cj.lziapi.com/api.php/provide/vod/'),
 ('暴风','https://bfzyapi.com/api.php/provide/vod/'),
 ('非凡','https://cj.ffzyapi.com/api.php/provide/vod/'),
 ('无尽','https://api.wujinapi.me/api.php/provide/vod/'),
 ('天涯','https://tyyszy.com/api.php/provide/vod/'),
 ('茅台','https://mtzy.me/api.php/provide/vod/'),
 ('金鹰','https://jyzyapi.com/api.php/provide/vod/'),
]
TITLE_POOL={
 '电影':[('霸王别姬','1993'),('让子弹飞','2010'),('我不是药神','2018'),('哪吒之魔童降世','2019'),
  ('战狼2','2017'),('红海行动','2018'),('流浪地球2','2023'),('满江红','2023'),('封神第一部','2023'),
  ('大话西游之大圣娶亲','1995'),('功夫','2004'),('千与千寻','2001'),('疯狂动物城','2016'),
  ('寻梦环游记','2017'),('阿甘正传','1994'),('盗梦空间','2010'),('星际穿越','2014'),('起风了','2013')],
 '电视剧':[('西游记','1986'),('红楼梦','1987'),('三国演义','1994'),('水浒传','1998'),('亮剑','2005'),
  ('士兵突击','2006'),('琅琊榜','2015'),('人民的名义','2017'),('觉醒年代','2021'),('山海情','2021'),
  ('狂飙','2023'),('潜伏','2009'),('天道','2008'),('大染坊','2003'),('闯关东','2008')],
 '综艺':[('中国诗词大会 第一季','2016'),('国家宝藏 第一季','2017'),('朗读者 第一季','2017'),('声生不息','2022')],
 '动漫':[('大闹天宫','1961'),('哪吒闹海','1979'),('天书奇谭','1983'),('葫芦兄弟','1986'),
  ('黑猫警长','1984'),('中国奇谭','2023'),('罗小黑战记','2019'),('雾山五行','2020')],
 '纪录片':[('舌尖上的中国 第一季','2012'),('航拍中国 第一季','2017'),('我在故宫修文物','2016'),
  ('河西走廊','2015'),('美丽中国','2008'),('蓝色星球 第二季','2017')],
 '少儿':[('舒克和贝塔','1989'),('邋遢大王奇遇记','1987'),('阿凡提的故事','1980'),
  ('大头儿子和小头爸爸','1995'),('黑猫警长','1984'),('葫芦兄弟','1986')],
}
CAT_OF_TYPE=re.compile(r'电影|电视剧|综艺|动漫|纪录片|少儿')
def category_of(type_name):
    t=type_name or ''
    if '纪录片' in t or '纪录' in t or '纪实' in t:return '纪录片'
    if '综艺' in t or '真人秀' in t or '晚会' in t:return '综艺'
    if '动漫' in t or '动画' in t or '卡通' in t:return '动漫'
    if '少儿' in t or '早教' in t or '亲子' in t:return '少儿'
    if '剧' in t or '短剧' in t:return '电视剧'
    if '片' in t:return '电影'
    return None

def fetch_json(url,timeout=PROBE_TIMEOUT):
    import urllib.request
    try:
        req=urllib.request.Request(url,headers=UA)
        with urllib.request.urlopen(req,timeout=timeout) as r:
            return json.loads(r.read().decode('utf-8','ignore'))
    except Exception:
        return None

def norm_title(s):
    s=unicodedata.normalize('NFKC',s or '')
    return re.sub(r'[\s：:·，,。.!！？?\-—_（）()【】\[\]''""]+','',s).lower()

def search_provider(pid,api,wd):
    d=fetch_json(api+f'?ac=videolist&wd={quote(wd)}')
    if not d:return []
    return d.get('list') or []

def detail(api,vids):
    d=fetch_json(api+f'?ac=videolist&ids={quote(",".join(map(str,vids)))}')
    return (d.get('list') or []) if d else []

def probe_hls(url):
    import urllib.request
    try:
        req=urllib.request.Request(url,headers=UA)
        with urllib.request.urlopen(req,timeout=PROBE_TIMEOUT) as r:
            body=r.read(262144).decode('utf-8','ignore')
        if '#EXTM3U' not in body:return None
        seg=next((l.strip() for l in body.splitlines() if l.strip() and not l.startswith('#')),None)
        if not seg:return None
        seg_url=urljoin(url,seg)
        with urllib.request.urlopen(urllib.request.Request(seg_url,headers=UA),timeout=PROBE_TIMEOUT) as r:
            n=len(r.read(131072))
        return {'ok':n>=4096,'segment_bytes':n,'level':'HLS + media segment'}
    except Exception:
        return None

def grab_frames(url,out_prefix):
    """5 个时间点抽帧；返回成功的时间点列表"""
    ts_ok=[]
    for t in (3,60,300,900,1800):
        out=ROOT/'frames'/f'{out_prefix}-{t}s.jpg'
        cmd=['ffmpeg','-hide_banner','-loglevel','error','-user_agent','okhttp/4.12.0',
             '-ss',str(t),'-i',url,'-frames:v','1','-q:v','4',str(out)]
        try:
            subprocess.run(cmd,capture_output=True,timeout=45)
            if out.exists() and out.stat().st_size>3000:ts_ok.append(t)
        except Exception:
            pass
    return ts_ok

def main():
    FR=ROOT/'frames'
    if not FR.exists():FR.mkdir(parents=True)
    (ROOT/'reports').mkdir(exist_ok=True) if not (ROOT/'reports').exists() else None
    approved=json.loads((ROOT/'input/approved-catalog.json').read_text())
    have={(norm_title(v['vod_name']),str(v.get('vod_year',''))) for v in approved['list']}
    # 1. 探活提供商
    alive=[]
    for pid,api in PROVIDERS:
        d=fetch_json(api+'?ac=list')
        if d and d.get('class') is not None:alive.append((pid,api));print(f'[vod] provider {pid} OK, {len(d["class"])} 分类')
        else:print(f'[vod] provider {pid} 不可用')
    # 2. 逐片名并发检索
    jobs=[(cat,name,year) for cat,items in TITLE_POOL.items() for name,year in items]
    def search_one(job):
        cat,name,year=job
        hits=[]
        for pid,api in alive:
            for it in search_provider(pid,api,name):
                if norm_title(it.get('vod_name'))!=norm_title(name):continue
                ty=str(it.get('vod_year',''))
                if year and ty and not ty.startswith(year[:4]):continue
                catx=category_of(it.get('type_name',''))
                if catx!=cat:continue  # 分类必须与目标一致（防错片）
                st,why=POLICY.title_state(it.get('vod_name',''),it.get('vod_content',''))
                if st=='blocked':continue
                hits.append((pid,api,it))
        return job,hits
    found={}
    with cf.ThreadPoolExecutor(12) as ex:
        for job,hits in ex.map(search_one,jobs):
            if hits:found[job]=hits
    print(f'[vod] {len(found)}/{len(jobs)} 片名命中')
    # 3. 详情 + >=2 独立线路筛选 + 集号核实
    candidates=[];gaps=[]
    for (cat,name,year),hits in sorted(found.items()):
        by_p={}
        for pid,api,it in hits:
            if pid in by_p:continue
            det=detail(api,[it['vod_id']])
            if det:by_p[pid]=(api,det[0])
        if len(by_p)<2:
            gaps.append({'title':name,'year':year,'category':cat,'reason':f'仅 {len(by_p)} 个提供商命中(需>=2)','providers':list(by_p)});continue
        routes=[];ep_counts=[]
        for pid,(api,det) in by_p.items():
            pu=str(det.get('vod_play_url',''))
            # 先拆线路（$$$），再拆集（#）；每提供商最多取2条线路
            prs=[]
            for rs in pu.split('$$$'):
                eps=[e for e in rs.split('#') if '$' in e]
                if eps:prs.append(eps)
            for eps in prs[:2]:
                ep_counts.append(len(eps))
                routes.append({'provider':pid,'episode_count':len(eps),
                               'play_url':'#'.join(eps),'remarks':det.get('vod_remarks',''),
                               'vod_pic':det.get('vod_pic',''),'vod_content':det.get('vod_content',''),
                               'vod_actor':det.get('vod_actor',''),'vod_director':det.get('vod_director',''),
                               'type_name':det.get('type_name','')})
        n_prov=len({r['provider'] for r in routes})
        if n_prov<2:
            gaps.append({'title':name,'year':year,'category':cat,'reason':f'仅 {n_prov} 个提供商命中(需>=2)','providers':list(by_p)});continue
        # 集号核实：各提供商首线路集数必须一致（电影除外）
        first_counts={pid:max(r['episode_count'] for r in routes if r['provider']==pid) for pid in {r['provider'] for r in routes}}
        if cat!='电影' and len(set(first_counts.values()))>1:
            gaps.append({'title':name,'year':year,'category':cat,'reason':f'各提供商集数不一致 {first_counts}，需人工核定','providers':list(by_p)});continue
        base=routes[0]
        key=(norm_title(name),year)
        cand={'vod_name':name,'vod_year':year,'category':cat,'type_name':base['type_name'],
              'vod_remarks':base['remarks'],'vod_actor':base['vod_actor'],'vod_director':base['vod_director'],
              'vod_content':base['vod_content'],'vod_pic':base['vod_pic'],
              'routes':[{k:r[k] for k in ('provider','episode_count','play_url','remarks')} for r in routes],
              'episode_counts':ep_counts}
        candidates.append(cand)
    print(f'[vod] {len(candidates)} 部 >=2 独立线路；{len(gaps)} 部缺口')
    # 4. 首集可播性 + 帧采样
    def first_url(route):
        ep=route['play_url'].split('#')[0]
        return ep.split('$',1)[1] if '$' in ep else None
    for i,c in enumerate(candidates):
        idx=f'vod{i:03d}'
        c['cand_idx']=idx
        for r in c['routes']:
            u=first_url(r)
            r['probe']=probe_hls(u) if u else None
        ok_routes=[r for r in c['routes'] if r['probe'] and r['probe']['ok']]
        if len(ok_routes)<2:
            c['frame_probe_failed']=True
            print(f"[vod] {c['vod_name']} 可播线路不足({len(ok_routes)})")
            continue
        ts=grab_frames(first_url(ok_routes[0]),idx)
        c['frames_captured']=ts
        print(f"[vod] {c['vod_name']} 帧: {ts}")
    # 5. 落盘
    (ROOT/'input/vod-candidates.json').write_text(json.dumps(
        {'provenance':{'providers':{p:a for p,a in alive},'harvested_at':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())},
         'candidates':candidates},ensure_ascii=False,indent=1)+'\n')
    (ROOT/'reports/vod-gaps.json').write_text(json.dumps({'gaps':gaps},ensure_ascii=False,indent=1)+'\n')
    print(f"[vod] 候选 {len(candidates)} → input/vod-candidates.json；缺口 {len(gaps)} → reports/vod-gaps.json")
if __name__=='__main__':main()
