import json,concurrent.futures as cf,subprocess
from pathlib import Path
from probe import media
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'live-review';OUT.mkdir(exist_ok=True)
rows=json.loads((ROOT/'input/review-live.json').read_text())
def check(v):
 r=dict(v);r['fresh_probe']=media(v['url'],v.get('headers',{}));return r
with cf.ThreadPoolExecutor(12) as pool:out=list(pool.map(check,rows))
(OUT/'live.json').write_text(json.dumps(out,ensure_ascii=False,indent=2))
sampled=[];hosts=set()
from urllib.parse import urlsplit
for i,v in enumerate(out):
 if not v['fresh_probe']['ok']:continue
 h=urlsplit(v['url']).hostname
 if h in hosts:continue
 hosts.add(h);target=OUT/f'live-{i}.jpg'
 try:
  p=subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-rw_timeout','5000000','-i',v['url'],'-frames:v','1','-vf','scale=480:-1','-y',str(target)],timeout=18,capture_output=True)
  if p.returncode==0 and target.exists():sampled.append({'index':i,'name':v['name'],'frame':target.name})
 except Exception:pass
(OUT/'frames.json').write_text(json.dumps(sampled,ensure_ascii=False,indent=2));print('LIVE_CHECKED',len(out),'PASS',sum(v['fresh_probe']['ok'] for v in out),'frames',len(sampled))
