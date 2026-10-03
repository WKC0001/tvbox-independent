"""Bounded representative video decoding; connectivity is not playback acceptance."""
import argparse,concurrent.futures as cf,json,os,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def probe(item,out):
    target=out/(item['id']+'.png');headers=item.get('headers',{})
    cmd=['ffmpeg','-nostdin','-hide_banner','-loglevel','info','-rw_timeout','10000000']
    if headers:cmd+=['-headers',''.join(k+': '+v+'\r\n' for k,v in headers.items())]
    if item.get('offset'):cmd+=['-ss',str(item['offset'])]
    cmd+=['-i',item['url'],'-map','0:v:0','-frames:v','1','-vf','scale=480:-2','-y',str(target)]
    result={**item,'checked_at':int(time.time()),'decoded':False}
    try:
        p=subprocess.run(cmd,capture_output=True,text=True,timeout=35)
        result.update(decoded=p.returncode==0 and target.exists() and target.stat().st_size>1000,
          video_stream=next((s.strip() for s in p.stderr.splitlines() if 'Video:' in s),''),
          audio_stream=next((s.strip() for s in p.stderr.splitlines() if 'Audio:' in s),''))
        if result['decoded']:result['frame']=target.name
        else:result['reason']=p.stderr[-1200:]
    except subprocess.TimeoutExpired:result['reason']='Decode timeout (35s)'
    print(item['id'],result['decoded'],flush=True);return result

def main():
    ap=argparse.ArgumentParser();ap.add_argument('samples');ap.add_argument('--out',default='frames/acceptance');ap.add_argument('--report',default='reports/decode-samples.json');args=ap.parse_args()
    out=ROOT/args.out;out.mkdir(parents=True,exist_ok=True)
    items=json.loads(Path(args.samples).read_text())
    with cf.ThreadPoolExecutor(6) as ex:results=list(ex.map(lambda x:probe(x,out),items))
    (ROOT/args.report).write_text(json.dumps({'network':'local-direct','exhaustive':False,'results':results},ensure_ascii=False,indent=2)+'\n')
    print('Decoded',sum(x['decoded'] for x in results),'of',len(results))

if __name__=='__main__':main()
