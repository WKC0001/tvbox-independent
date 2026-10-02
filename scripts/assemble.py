"""Build ONLY the fixed catalogue after manual poster/frame review. No CMS discovery admission."""
import json,hashlib,time,re
from pathlib import Path
from urllib.parse import urlsplit
from collections import defaultdict,Counter
from channel_layout import label,live_sort
ROOT=Path(__file__).resolve().parents[1]
def dump(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def main():
 pkg=json.loads((ROOT/'package.json').read_text());base=f"https://cdn.jsdelivr.net/npm/{pkg['name']}@{pkg['version']}/"
 reviewed=json.loads((ROOT/'input/approved-catalog.json').read_text());assert reviewed['visual_review_complete']
 rows=reviewed['list'];assert rows and all(v['approved'] for v in rows)
 data=json.dumps(rows,ensure_ascii=False,separators=(',',':'));digest=hashlib.sha256(data.encode()).hexdigest()
 (ROOT/'java/src/com/github/catvod/spider/ApprovedCatalogue.java').write_text('package com.github.catvod.spider; public final class ApprovedCatalogue { public static final String SHA256="'+digest+'"; }\n')
 channels=defaultdict(list);seen=set()
 allowed={'cctvplus.com','cgtn.com','cztv.com','jlntv.cn','hebtv.com','gztv.com','zohi.tv','nmtv.cn','hrbtv.net'}
 aliases={'CGTN':'CGTN英语','CGTN记录':'CGTN纪录','Harbin Movie Channel':'哈尔滨影视','Zhejiang International Channel':'浙江国际','浙江教科':'浙江教科影视','浙江教育':'浙江教科影视','浙江经济':'浙江经济生活','浙江经视':'浙江经济生活','浙江民生':'浙江民生休闲','浙江休闲台':'浙江民生休闲','浙江钱江':'浙江钱江都市','浙江钱江频道':'浙江钱江都市','钱江都市':'浙江钱江都市','数码时代':'浙江数码时代','中国蓝新闻':'浙江新闻','CCTV+ 1':'CCTV+ 新闻直播1（不定时）','CCTV+ 2':'CCTV+ 新闻直播2（不定时）'}
 skip={'敦化一套','延边2','浙江留学','CGTN纪录','CGTN记录','新闻综合频道','河北电视台','CGTN法语','Chifeng Comprehensive News Chanel','China Travel','Discovering China','CGTN Global Biz'}
 for e in json.loads((ROOT/'input/approved-live.json').read_text()):
  if not e.get('fresh_probe',{}).get('ok') or not e.get('frame_review_pass'):continue
  host=urlsplit(e['url']).hostname or ''
  if not any(host==h or host.endswith('.'+h) for h in allowed):continue
  if host.endswith('cgtn.com') and e['url']!='http://english-livetx.cgtn.com/hls/yypdyyctzb_hd.m3u8':continue
  v=label(e)
  if not v:continue
  g,name,m=v
  if any(name.startswith(s) for s in skip):continue
  name=aliases.get(name,name)
  if host.endswith('jlntv.cn') and not any(x in name for x in ['综合','新闻','卫视','公共']):name+='综合'
  if name.startswith('CGTN'):g='央视'
  if g not in ['央视','卫视','地方','少儿与纪录']:continue
  # Canonical HLS identity ignores rendition and dated auth query; a channel retains one route per stream identity.
  p=urlsplit(e['url']);path=re.sub(r'/channel0+(\d+)',r'/channel\1',p.path);path=re.sub(r'/(?:sd|hd|1080p|720p)(?=/|\.m3u8)','',path)
  identity=(host,path)
  if identity in seen:continue
  seen.add(identity);channels[(g,name)].append(e)
 lines=['#EXTM3U'];route_count=0
 for (g,name),es in sorted(channels.items(),key=live_sort):
  for e in es:
   attrs=f'group-title="{g}"';agent=e.get('headers',{}).get('User-Agent')
   if agent:attrs+=' http-user-agent="'+agent.replace('"','')+'"'
   lines.extend([f'#EXTINF:-1 {attrs},{name}',e['url']]);route_count+=1
 (ROOT/'live.m3u').write_text('\n'.join(lines)+'\n')
 api={'spider':base+'home.jpg','sites':[{'key':'wkc_reviewed_home','name':'WKC · 已审核片单','type':3,'api':'csp_WkcHome','searchable':1,'quickSearch':1,'filterable':0,'ext':{'catalog_json':data}}], 'lives':[{'name':'WKC · 精选电视直播','type':0,'url':base+'live.m3u','playerType':1}], 'parses':[], 'flags':[], 'rules':[]}
 if (ROOT/'home.jpg').exists():api['spider']+=';md5;'+hashlib.md5((ROOT/'home.jpg').read_bytes()).hexdigest()
 dump(ROOT/'api.json',api)
 report={'version':pkg['version'],'policy':'Immutable title whitelist; no raw CMS browse/search/detail; matching catalogue hash required by plugin','reviewed_titles':len(rows),'categories':dict(Counter(v['category'] for v in rows)),'removed_providers':['玉兔','辣椒','滴滴','乐播','火速','光速'],'live_channels':len(channels),'live_routes':route_count,'live_frames_reviewed':len(json.loads((ROOT/'input/approved-live.json').read_text())),'live_groups':dict(Counter(g for g,n in channels)), 'live_policy':'Known broadcaster host suffix allowlist, successful fresh HLS/media probe and manually inspected frame required; black/no-signal/misnamed/anonymous routes excluded', 'limits':['Poster review and 4–5 sampled frames of first episode only; no full-episode/full-series certification','Remote media may change; runtime URLs do not guarantee future content','No Android device playback test or mainland ISP verification','CCTV1–17 coverage is incomplete; no anonymous relay added to fill gaps'],'original_repo_modified':False,'original_npm_modified':False}
 dump(ROOT/'reports/content-review.json',report)
 manifest={**report,'package':pkg['name'],'generated_at':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'catalog_sha256':digest,'files':{f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in ['api.json','live.m3u','home.jpg'] if (ROOT/f).exists()}}
 for p in (ROOT/'posters').glob('*'):manifest['files'][str(p.relative_to(ROOT))]=hashlib.sha256(p.read_bytes()).hexdigest()
 dump(ROOT/'manifest.json',manifest);print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
