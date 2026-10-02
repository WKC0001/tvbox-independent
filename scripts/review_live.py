import json,concurrent.futures as cf,subprocess
from pathlib import Path
from probe import media
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'live-review';OUT.mkdir(exist_ok=True)
rows=json.loads((ROOT/'input/review-live.json').read_text())
def check(v):
 r=dict(v);r['fresh_probe']=media(v['url'],v.get('headers',{}));return r
with cf.ThreadPoolExecutor(12) as pool:out=list(pool.map(check,rows))
(OUT/'live.json').write_text(json.dumps(out,ensure_ascii=False,indent=2))
def frame(item):
 i,v=item
 if not v['fresh_probe']['ok']:return None
 target=OUT/f'live-{i}.jpg'
 try:
  p=subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-rw_timeout','5000000','-i',v['url'],'-frames:v','1','-vf','scale=480:-1','-y',str(target)],timeout=14,capture_output=True)
  if p.returncode==0 and target.exists():return {'index':i,'name':v['name'],'frame':target.name}
 except Exception:pass
 return None
with cf.ThreadPoolExecutor(6) as pool:sampled=[x for x in pool.map(frame,enumerate(out)) if x]
(OUT/'frames.json').write_text(json.dumps(sampled,ensure_ascii=False,indent=2));print('LIVE_CHECKED',len(out),'PASS',sum(v['fresh_probe']['ok'] for v in out),'frames',len(sampled))
