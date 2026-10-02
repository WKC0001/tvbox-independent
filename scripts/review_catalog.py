import sys,json,re,unicodedata,concurrent.futures as cf,hashlib,time
from pathlib import Path
from urllib.parse import urlsplit
from probe import cms,media,fetch,public
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'review-output';OUT.mkdir(exist_ok=True)
BANNED_HOSTS={'apiyutu.com','apilj.com','api.ddapi.cc','lbapi9.com','api.huosuapi.cc','api.guangsuapi.com'}
# Limit the correction to general libraries. No live upstream home/list is imported.
HOSTS={'360zy.com','ffzy.tv'}
BLOCK=re.compile(r'伦理|倫理|理论片|理論片|成人|色情|三級|三级|福利|擦边|擦邊|写真|寫真|热舞|熱舞|两性|兩性|无码|無碼|有码|有碼|传媒|傳媒|自拍|主播秀|萝莉|蘿莉|AV明星|巨乳|人妻|性爱|性愛|无码|无码|SM调教',re.I)
CATS=['电视剧','电影','综艺','动漫','纪录片']
def norm(s):return re.sub(r'[\s\W_]+','',unicodedata.normalize('NFKC',str(s)))
def clean_provider(p):
 assert urlsplit(p['api']).hostname not in BANNED_HOSTS
 return {'api':p['api'],'name':p.get('display_name',p['name']),'key':'review_'+hashlib.sha256(p['api'].encode()).hexdigest()[:10],'blocked_ids':[str(c['type_id']) for c in p['classes'] if BLOCK.search(c['type_name'])]}
def main():
 raw=json.loads((ROOT/'input/review-provider-probes.json').read_text());providers=[clean_provider(p) for p in raw if p.get('accepted') and urlsplit(p['api']).hostname in HOSTS]
 titles=json.loads((ROOT/'input/reviewed-titles.json').read_text());results=[];rejected=[]
 def lookup(pair):
  title,p=pair;allowed={norm(n) for n in [title['name']]+title.get('aliases',[])}
  try:
   o,_=cms(p['api'],ac='detail',wd=title['name'],pg=1)
   matches=[v for v in o['list'] if norm(v.get('vod_name','')) in allowed and str(v.get('vod_year','')) in title['years']]
   found=[]
   for v in matches[:2]:
    if not v.get('vod_play_url'):v=cms(p['api'],ac='detail',ids=str(v['vod_id']))[0]['list'][0]
    if str(v.get('type_id')) in p['blocked_ids'] or BLOCK.search(str(v.get('type_name',''))):continue
    if norm(v.get('vod_name','')) not in allowed or str(v.get('vod_year','')) not in title['years']:continue
    flags=str(v.get('vod_play_from','')).split('$$$');lines=str(v.get('vod_play_url','')).split('$$$');clean=[]
    for f,l in zip(flags,lines):
     episodes=[]
     for ep in l.split('#'):
      en,sep,u=ep.partition('$')
      if sep and public(u) and (urlsplit(u).path.lower().endswith('.m3u8') or 'm3u8' in f.lower()):episodes.append((en,u))
     if episodes:clean.append((f,episodes))
    if not clean or not v.get('vod_pic'):continue
    f,eps=clean[0];check=media(eps[0][1]);
    found.append({'approved_title':title['name'],'approved_category':title['category'],'provider':p['name'],'provider_key':p['key'],'original_id':str(v['vod_id']),
     'vod_name':title['name'],'vod_year':str(v['vod_year']),'type_name':str(v.get('type_name','')),'type_id':str(v.get('type_id','')),
     'vod_pic':v['vod_pic'],'vod_remarks':v.get('vod_remarks',''),'vod_content':re.sub('<[^>]+>','',str(v.get('vod_content','')))[:1000],
     'vod_actor':str(v.get('vod_actor','')),'vod_director':str(v.get('vod_director','')),
     'vod_play_from':p['name'],'vod_play_url':'#'.join(n+'$'+u for n,u in eps),'media_sample':check})
   return found
  except Exception as e:return []
 with cf.ThreadPoolExecutor(10) as ex:
  for i,rows in enumerate(ex.map(lookup,[(t,p) for t in titles for p in providers]),1):
   results+=rows
   if i%15==0:print('REVIEW_PROGRESS',i,len(titles)*len(providers),'matched',len(results),flush=True)
 (OUT/'candidate-catalog.json').write_text(json.dumps({'list':results,'catalog_version':1,'policy':'Exact editorial title+year whitelist, prohibited providers/categories removed, fixed content snapshots. Poster visual review pending.','generated_at':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())},ensure_ascii=False,indent=2))
 # Extract a single early frame from media-verified candidates. No adult candidates are fetched.
 import subprocess
 frames=OUT/'frames';frames.mkdir(exist_ok=True)
 sampled=[]
 for i,v in enumerate(results):
  if not v['media_sample']['ok']:continue
  if any(s['approved_title']==v['approved_title'] for s in sampled):continue
  target=frames/(str(i)+'.jpg');url=v['vod_play_url'].split('#')[0].split('$',1)[1]
  try:
   p=subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-rw_timeout','6000000','-user_agent','okhttp/4.12.0','-i',url,'-ss','3','-frames:v','1','-vf','scale=480:-1','-y',str(target)],timeout=16,capture_output=True)
   if p.returncode==0 and target.exists():sampled.append({'index':i,'approved_title':v['approved_title'],'frame':target.name})
  except Exception:pass
  if len(sampled)>=12:break
 (OUT/'frame-review.json').write_text(json.dumps(sampled,ensure_ascii=False,indent=2))
 print('CATALOG',len(results),'frames',len(sampled),flush=True)
if __name__=='__main__':main()
