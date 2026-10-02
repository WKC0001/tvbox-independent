import json,subprocess,concurrent.futures as cf
from pathlib import Path
from urllib.request import Request,urlopen
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'asset-review';OUT.mkdir(exist_ok=True)
rows=json.loads((ROOT/'input/review-candidates.json').read_text())
def work(item):
 i,v=item; result={'index':i,'name':v['approved_title'],'category':v['approved_category'],'type_name':v['type_name'],'frames':[]}
 try:
  b=urlopen(Request(v['vod_pic'],headers={'User-Agent':'Mozilla/5.0'}),timeout=10).read(2000000);(OUT/f'poster-{i}.jpg').write_bytes(b);result['poster']=f'poster-{i}.jpg'
 except Exception:pass
 url=v['vod_play_url'].split('#')[0].split('$',1)[1]
 for sec in [300,900,1800]:
  target=OUT/f'frame-{i}-{sec}.jpg'
  try:
   p=subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-rw_timeout','7000000','-user_agent','okhttp/4.12.0','-ss',str(sec),'-i',url,'-frames:v','1','-vf','scale=480:-1','-y',str(target)],timeout=35,capture_output=True)
   if p.returncode==0 and target.exists():result['frames'].append(target.name)
  except Exception:pass
 print('ASSET',i,result['name'],len(result['frames']),flush=True);return result
with cf.ThreadPoolExecutor(5) as pool:results=list(pool.map(work,enumerate(rows)))
(OUT/'index.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
