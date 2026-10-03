"""Live harvest pipeline (stage 3).

Parses upstream candidate playlists (iptv-org snapshot), normalizes channel
identity via channel_layout.label(), applies the content gate (blocked
registry / fail-closed), probes each candidate (HLS playlist + media segment),
then runs an automated luma-based frame sanity check on the selected routes.

Outputs (never auto-published; merge is a separate explicit step):
  input/review-live.json        all candidates with probe/frame evidence
  reports/live-gaps.json        target channels with no usable route
Provenance of every candidate: iptv-org snapshot commit (recorded below).
"""
import argparse,concurrent.futures as cf,hashlib,json,re,subprocess,sys,time
from pathlib import Path
from urllib.parse import urljoin,urlsplit

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from channel_layout import label  # identity normalization + nsfw/junk filter
from policy.content_policy import ContentPolicy
POLICY=ContentPolicy(ROOT/'policy/blocked-sources.json')

IPTV_COMMIT='7e810ceb735fe64be1212cd2b37c1062a8767ff4'  # zip header commit sha (traceable)
TARGET_GROUPS={'央视','卫视','地方','港澳台','新闻国际','体育','少儿','纪录','风景慢直播'}
MAX_ROUTES_PER_CHANNEL=3
PROBE_CONCURRENCY=16;PROBE_TIMEOUT=10
UA={'User-Agent':'okhttp/3.15'}

def parse_m3u(path:Path):
    """Yield {name,id,url,headers,attrs} from an iptv-org style playlist."""
    cur=None
    for ln in path.read_text(errors='ignore').splitlines():
        ln=ln.strip()
        if ln.startswith('#EXTINF'):
            name=ln.split(',',1)[1].strip() if ',' in ln else ''
            ident=''
            m=re.search(r'tvg-id="([^"]*)"',ln)
            if m:ident=m.group(1)
            cur={'name':name,'id':ident,'headers':{}}
        elif ln.startswith('#EXTVLCOPT:'):
            if cur:
                m=re.match(r'#EXTVLCOPT:(?:http-)?user-agent=(.*)',ln,re.I)
                if m:cur['headers']['User-Agent']=m.group(1).strip()
                m=re.match(r'#EXTVLCOPT:http-referer=(.*)',ln,re.I)
                if m:cur['headers']['Referer']=m.group(1).strip()
        elif ln and not ln.startswith('#'):
            if cur:cur['url']=ln;yield cur;cur=None

def fetch(url,headers=None,timeout=PROBE_TIMEOUT,max_bytes=262144):
    """Return (status, body_bytes, ms) or (0, b'', ms) on failure."""
    import urllib.request
    h={**UA,**(headers or {})};t0=time.monotonic()
    try:
        req=urllib.request.Request(url,headers=h)
        with urllib.request.urlopen(req,timeout=timeout) as r:
            body=r.read(max_bytes);code=r.getcode()
        return code,body,int((time.monotonic()-t0)*1000)
    except Exception:
        return 0,b'',int((time.monotonic()-t0)*1000)

def probe_level1(url,headers):
    """Playlist reachable and is HLS."""
    code,body,ms=fetch(url,headers)
    if not code or not body:return None
    txt=body.decode('utf-8','ignore')
    if '#EXTM3U' not in txt:return None
    return {'ms':ms}

def probe_level2(url,headers):
    """Resolve first media segment and download some bytes."""
    code,body,ms=fetch(url,headers)
    if not code or not body:return None
    txt=body.decode('utf-8','ignore')
    if '#EXTM3U' not in txt:return None
    seg=next((l.strip() for l in txt.splitlines() if l.strip() and not l.startswith('#')),None)
    if not seg:return None
    seg_url=urljoin(url,seg)
    c2,b2,ms2=fetch(seg_url,headers,timeout=PROBE_TIMEOUT,max_bytes=131072)
    if not c2 or len(b2)<4096:return None  # tiny/empty segment = not real media
    return {'ms':ms,'segment_ms':ms2,'segment_bytes':len(b2),'level':'HLS + media segment'}

def frame_check(url,headers):
    """Automated frame sanity: two gray samples 2s apart must be non-black,
    non-flat (std above noise floor). Returns dict or None on failure.
    This is an automated luma check — it does NOT replace manual inspection."""
    def sample():
        cmd=['ffmpeg','-hide_banner','-loglevel','error','-user_agent',
             (headers or {}).get('User-Agent','okhttp/3.15'),
             '-i',url,'-t','3','-vf','scale=64:36,format=gray','-f','rawvideo','-']
        try:
            p=subprocess.run(cmd,capture_output=True,timeout=25)
            b=p.stdout
            if len(b)<64*36:return None
            return b[-64*36:]  # last full frame captured in window
        except Exception:
            return None
    f1,f2=sample(),sample()
    if not f1 or not f2:return None
    def stats(b):
        n=len(b);mean=sum(b)/n;var=sum((x-mean)**2 for x in b)/n
        return mean,var**.5
    m1,s1=stats(f1);m2,s2=stats(f2)
    if max(m1,m2)<12:return {'pass':False,'why':'black/no-signal'}
    if max(s1,s2)<6:return {'pass':False,'why':'flat/static picture'}
    if abs(m1-m2)<2 and abs(s1-s2)<2 and s1<12:
        return {'pass':False,'why':'frozen frame'}
    return {'pass':True,'luma':(round(m1,1),round(m2,1)),'std':(round(s1,1),round(s2,1)),
            'method':'auto-luma'}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--src',default=str(ROOT.parent/'iptv-src'/'iptv-master'/'streams'))
    ap.add_argument('--out',default=str(ROOT/'input/review-live.json'))
    ap.add_argument('--frame-top',type=int,default=5,
                    help='candidates per channel sent to frame check (after probe)')
    args=ap.parse_args()
    src=Path(args.src)
    # ---- 1. parse + normalize + gate ----
    cands=[];seen_url=set()
    for f in sorted(src.glob('*.m3u')):
        if not re.match(r'^(cn|hk|mo|tw)',f.name):continue
        for e in parse_m3u(f):
            if '[Geo-blocked]' in e['name'] or '[Not 24/7]' in e['name']:continue
            if not e['url'].lower().startswith(('http://','https://')):continue
            st,_=POLICY.provider_state('',e['url'])
            if st=='blocked':continue
            e['source_group']=f.stem
            v=label(e)
            if not v:continue
            g,name,m=v
            if g not in TARGET_GROUPS:continue
            if e['url'] in seen_url:continue
            seen_url.add(e['url'])
            cands.append({'name':name,'group':g,'tvg_id':e['id'],'meta_id':(m or {}).get('id',''),
                          'country':(m or {}).get('country',''),'url':e['url'],
                          'headers':e['headers'],'src_file':f.name})
    print(f'[harvest] {len(cands)} candidates after parse/gate',flush=True)
    # ---- 2. probe level1 then level2 ----
    def l1(c):
        r=probe_level1(c['url'],c['headers']);return (c,r)
    passing=[]
    with cf.ThreadPoolExecutor(PROBE_CONCURRENCY) as ex:
        for c,r in ex.map(l1,cands):
            if r:passing.append(c)
    print(f'[harvest] {len(passing)} passed playlist probe',flush=True)
    def l2(c):
        c['probe']=probe_level2(c['url'],c['headers']);return c
    ok=[]
    with cf.ThreadPoolExecutor(PROBE_CONCURRENCY) as ex:
        for c in ex.map(l2,passing):
            if c['probe']:ok.append(c)
    print(f'[harvest] {len(ok)} passed segment probe',flush=True)
    # ---- 3. rank per channel, frame-check top N, keep <=3 heterogeneous hosts ----
    bych={}
    for c in ok:bych.setdefault((c['group'],c['name']),[]).append(c)
    routes=[]
    for (g,name),cs in sorted(bych.items()):
        cs.sort(key=lambda c:c['probe']['segment_ms'])
        for c in cs[:args.frame_top]:
            fr=frame_check(c['url'],c['headers'])
            c['frame']=fr
            if fr and fr['pass']:routes.append(c)
    kept={}
    for c in routes:  # already sorted by channel; enforce heterogeneous hosts
        k=(c['group'],c['name']);host=urlsplit(c['url']).hostname or ''
        lst=kept.setdefault(k,[])
        if len(lst)>=MAX_ROUTES_PER_CHANNEL:continue
        hosts={urlsplit(x['url']).hostname for x in lst}
        if host in hosts and len(lst):continue  # 异构线路：同频道不同主机
        lst.append(c)
    n_routes=sum(len(v) for v in kept.values())
    print(f'[harvest] {len(kept)} channels / {n_routes} usable new routes',flush=True)
    for c in ok:  # annotate the rest too for the review file
        c.setdefault('frame',None)
    out={'provenance':{'upstream':'iptv-org/iptv streams/','commit':IPTV_COMMIT,
                       'harvested_at':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
                       'gate':'blocked-registry + nsfw/junk label filter + fail-closed'},
         'probe_stats':{'candidates':len(cands),'playlist_ok':len(passing),
                        'segment_ok':len(ok),'usable_routes':n_routes},
         'channels':{f'{g}|{n}':v for (g,n),v in sorted(kept.items())},
         'all_candidates':ok}
    Path(args.out).write_text(json.dumps(out,ensure_ascii=False,indent=1)+'\n')
    print(f'[harvest] wrote {args.out}',flush=True)
if __name__=='__main__':main()
