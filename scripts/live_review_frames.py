"""Stage-3 visual frame review helper.

Reads input/review-live.json (harvest output), extracts one frame per route,
tiles them into labeled grids (12 tiles each) under frames/, and writes
frames/index.json mapping tile index -> route. A human (or the reviewing
agent) then inspects the grids and records pass/fail per index into
input/review-live-decisions.json for scripts/live_merge.py to apply.
"""
import concurrent.futures as cf,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
FR=ROOT/'frames'
def grab(idx,route):
    url=route['url'];ua=(route.get('headers') or {}).get('User-Agent','okhttp/3.15')
    out=FR/f'f{idx:03d}.jpg'
    cmd=['ffmpeg','-hide_banner','-loglevel','error','-user_agent',ua,'-i',url,
         '-t','6','-vf','select=gte(n\\,120),scale=320:180','-frames:v','1','-q:v','4',str(out)]
    try:
        subprocess.run(cmd,capture_output=True,timeout=40)
    except Exception:
        pass
    return idx,out.exists()

def tile_grid(idxs,size=(4,3)):
    """One grid image with index labels drawn via Pillow (ffmpeg lacks drawtext)."""
    from PIL import Image,ImageDraw
    w,h=320,180
    cols,rows=size
    grid=Image.new('RGB',(cols*w,rows*h),(12,12,12))
    d=ImageDraw.Draw(grid)
    n=0
    for k,i in enumerate(idxs):
        f=FR/f'f{i:03d}.jpg'
        if not f.exists():continue
        im=Image.open(f).convert('RGB')
        x=(k%cols)*w;y=(k//cols)*h
        grid.paste(im,(x,y))
        d.rectangle([x+4,y+4,x+92,y+34],fill=(200,0,0))
        d.text((x+10,y+8),f"#{i:03d}",fill=(255,255,255))
        n+=1
    if not n:return False,'no frames'
    out=FR/f"grid-{idxs[0]:03d}-{idxs[-1]:03d}.jpg"
    grid.save(out,quality=85)
    return True,''

def main():
    if not FR.exists():FR.mkdir(parents=True)
    for old in FR.glob('*'):old.unlink()
    data=json.loads((ROOT/'input/review-live.json').read_text())
    routes=[]
    for key,cs in sorted(data['channels'].items()):
        for c in cs:
            routes.append({'group':key.split('|')[0],'name':key.split('|')[1],**c})
    print(f'[frames] {len(routes)} routes')
    idx_map=[]
    with cf.ThreadPoolExecutor(8) as ex:
        for idx,okc in ex.map(lambda t:grab(*t),enumerate(routes)):
            if okc:
                idx_map.append({'i':idx,'group':routes[idx]['group'],'name':routes[idx]['name'],
                                'url':routes[idx]['url'],'headers':routes[idx].get('headers',{})})
    print(f'[frames] {len(idx_map)} frames captured')
    (FR/'index.json').write_text(json.dumps(idx_map,ensure_ascii=False,indent=1)+'\n')
    # grids of 12
    ids=[r['i'] for r in idx_map]
    for s in range(0,len(ids),12):
        chunk=ids[s:s+12]
        ok,err=tile_grid(chunk)
        print(f'[frames] grid {chunk[0]:03d}-{chunk[-1]:03d}: {"OK" if ok else err}')
if __name__=='__main__':main()
