"""Stage-4 VOD frame review: tile each candidate's 5 timestamp frames into
labeled grids (one row per candidate, 6 candidates per grid) and write
frames/vod-index.json mapping rows to candidates for decisions."""
import json
from pathlib import Path
from PIL import Image,ImageDraw
ROOT=Path(__file__).resolve().parents[1];FR=ROOT/'frames'
W,H=300,169;COLS=5;ROWS=6
def main():
    data=json.loads((ROOT/'input/vod-candidates.json').read_text())
    cands=[c for c in data['candidates'] if not c.get('frame_probe_failed')]
    idx=[]
    grids=[]
    for c in cands:
        files=[FR/f"{c['cand_idx']}-{t}s.jpg" for t in (3,60,300,900,1800)]
        if all(f.exists() for f in files):
            idx.append({'cand_idx':c['cand_idx'],'name':c['vod_name'],'year':c['vod_year'],
                        'category':c['category'],'providers':[r['provider'] for r in c['routes']],
                        'episode_counts':c['episode_counts'],'frames':c.get('frames_captured',[])})
    print(f"[vodframes] {len(idx)}/{len(cands)} 候选有完整帧")
    (FR/'vod-index.json').write_text(json.dumps(idx,ensure_ascii=False,indent=1)+'\n')
    for s in range(0,len(idx),ROWS):
        chunk=idx[s:s+ROWS]
        grid=Image.new('RGB',(COLS*W,ROWS*(H+26)),(15,15,15))
        d=ImageDraw.Draw(grid)
        for r,ent in enumerate(chunk):
            d.text((8,r*(H+26)+6),f"row{r} {ent['cand_idx']} {ent['name']}({ent['year']}) {ent['category']} 线路{len(ent['providers'])}",fill=(255,220,80))
            for cidx,t in enumerate((3,60,300,900,1800)):
                f=FR/f"{ent['cand_idx']}-{t}s.jpg"
                if f.exists():
                    im=Image.open(f).convert('RGB').resize((W,H))
                    grid.paste(im,(cidx*W,r*(H+26)+26))
            d.text((8+260,r*(H+26)+6),f"3s/60s/300s/900s/1800s",fill=(160,160,160))
        out=FR/f"vodgrid-{s//ROWS}.jpg"
        grid.save(out,quality=82)
        grids.append(str(out))
        print(f"[vodframes] {out.name}: rows {s}..{s+len(chunk)-1}")
if __name__=='__main__':main()
