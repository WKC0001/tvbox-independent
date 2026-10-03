"""Build ONLY the fixed catalogue after manual poster/frame review. No CMS discovery admission."""
import json,hashlib,time,re,sys,copy
from pathlib import Path
from urllib.parse import urlsplit
from collections import defaultdict,Counter
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from catalog.ids import work_id,route_id,channel_id
from checker import health
from policy.content_policy import ContentPolicy,host_of
from channel_layout import label,live_sort
POLICY=ContentPolicy(ROOT/'policy/blocked-sources.json')
def dump(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def is_isolated(state,url):
 return any(rec.get('isolated') for rec in state.get(route_id(url),{}).values())
def without_isolated_media(rows,state):
 out=[]
 for v in rows:
  flags=v['vod_play_from'].split('$$$');sources=v['vod_play_url'].split('$$$')
  assert len(flags)==len(sources), 'Play-source and episode-list counts differ'
  kept_flags=[];kept_sources=[]
  for flag,source in zip(flags,sources):
   eps=[]
   for ep in source.split('#'):
    assert '$' in ep, 'Malformed episode'
    if not is_isolated(state,ep.split('$',1)[1]):eps.append(ep)
   if eps:kept_flags.append(flag);kept_sources.append('#'.join(eps))
  if kept_sources:
   v['vod_play_from']='$$$'.join(kept_flags);v['vod_play_url']='$$$'.join(kept_sources);out.append(v)
 return out
def main():
 pkg=json.loads((ROOT/'package.json').read_text());base=f"https://cdn.jsdelivr.net/npm/{pkg['name']}@{pkg['version']}/"
 reviewed=json.loads((ROOT/'input/approved-catalog.json').read_text());assert reviewed['visual_review_complete']
 rows=copy.deepcopy(reviewed['list']);assert rows and all(v['approved'] for v in rows)
 state=health.load_state(ROOT/'state/health.json')
 rows=without_isolated_media(rows,state)
 assert rows, 'No approved non-isolated works remain; refuse empty VOD release'
 # Package-owned poster assets move with the release, not with mutable upstream URLs.
 for v in rows:
  pic=urlsplit(v['vod_pic'])
  prefix='/npm/'+pkg['name']+'@'
  assert pic.scheme=='https' and pic.hostname=='cdn.jsdelivr.net' and pic.path.startswith(prefix), 'Poster must be a bundled reviewed asset'
  relative=pic.path[len(prefix):].split('/',1)[1]
  assert re.fullmatch(r'posters/[A-Za-z0-9_-]+\.(?:jpg|jpeg|png|webp)',relative) and (ROOT/relative).is_file(), 'Missing reviewed poster asset'
  v['vod_pic']=base+relative
 # 门禁防线：批准目录逐行过内容策略 + 封禁域名双重扫描（域名+提供方名）
 for v in rows:
  st,why=POLICY.title_state(v['vod_name'],v.get('vod_content',''));assert st!='blocked',f"批准目录污点: {v['vod_name']} {why}"
  st,why=POLICY.provider_state(str(v.get('vod_play_from','')),'https://placeholder.invalid/');assert st!='blocked',f"批准目录封禁提供方: {v.get('vod_play_from')} {why}"
  for source in str(v.get('vod_play_url','')).split('$$$'):
   for ep in source.split('#'):
    u=ep.split('$',1)[-1];h=host_of(u)
    st,_=POLICY.provider_state('',u);assert st!='blocked',f"批准目录命中封禁域名 {h}: {v['vod_name']}"
 # 稳定 ID：work_id 由片名+年份派生，必须唯一（同名同年重复=上游数据缺陷）
 seen_wids=set()
 for v in rows:
  v['work_id']=work_id(v['vod_name'],v.get('vod_year',''))
  assert v['work_id'] not in seen_wids,f"重复 work_id: {v['vod_name']}({v.get('vod_year')})"
  seen_wids.add(v['work_id'])
 data=json.dumps(rows,ensure_ascii=False,separators=(',',':'));digest=hashlib.sha256(data.encode()).hexdigest()
 (ROOT/'java/src/com/github/catvod/spider/ApprovedCatalogue.java').write_text('package com.github.catvod.spider; public final class ApprovedCatalogue { public static final String SHA256="'+digest+'"; }\n')
 channels=defaultdict(list);seen=set()
 # 允许表数据驱动：probe+segment+目检帧审通过的主机才入表（live_merge.py 维护）
 _ah=ROOT/'input/live-allowed-hosts.json'
 allowed=set(json.loads(_ah.read_text())['hosts']) if _ah.exists() else \
  {'cctvplus.com','cgtn.com','cztv.com','jlntv.cn','hebtv.com','gztv.com','zohi.tv','nmtv.cn','hrbtv.net'}
 aliases={'CGTN':'CGTN英语','CGTN记录':'CGTN纪录','Harbin Movie Channel':'哈尔滨影视','Zhejiang International Channel':'浙江国际','浙江教科':'浙江教科影视','浙江教育':'浙江教科影视','浙江经济':'浙江经济生活','浙江经视':'浙江经济生活','浙江民生':'浙江民生休闲','浙江休闲台':'浙江民生休闲','浙江钱江':'浙江钱江都市','浙江钱江频道':'浙江钱江都市','钱江都市':'浙江钱江都市','数码时代':'浙江数码时代','中国蓝新闻':'浙江新闻','CCTV+ 1':'CCTV+ 新闻直播1（不定时）','CCTV+ 2':'CCTV+ 新闻直播2（不定时）'}
 skip={'敦化一套','延边2','浙江留学','CGTN纪录','CGTN记录','新闻综合频道','河北电视台','CGTN法语','Chifeng Comprehensive News Chanel','China Travel','Discovering China','CGTN Global Biz'}
 LIVE_GROUPS=['央视','卫视','地方','港澳台','新闻国际','体育','少儿','纪录']
 for e in json.loads((ROOT/'input/approved-live.json').read_text()):
  if not e.get('fresh_probe',{}).get('ok') or not e.get('frame_review_pass'):continue
  if is_isolated(state,e['url']):continue
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
  if g not in LIVE_GROUPS:continue
  st,_=POLICY.provider_state('',e['url'])
  if st=='blocked':continue  # 封禁注册表域名防线（直播线路）
  # Canonical HLS identity ignores rendition and dated auth query; a channel retains one route per stream identity.
  p=urlsplit(e['url']);path=re.sub(r'/channel0+(\d+)',r'/channel\1',p.path);path=re.sub(r'/(?:sd|hd|1080p|720p)(?=/|\.m3u8)','',path)
  identity=(host,path)
  if identity in seen:continue
  seen.add(identity);channels[(g,name)].append(e)
 lines=['#EXTM3U'];route_count=0;route_registry=[]
 for (g,name),es in sorted(channels.items(),key=live_sort):
  cid=channel_id(name,es[0].get('id',''))
  for e in es:
   attrs=f'group-title="{g}"';agent=e.get('headers',{}).get('User-Agent')
   if agent:attrs+=' http-user-agent="'+agent.replace('"','')+'"'
   tid=e.get('id') or ''
   if tid:attrs+=f' tvg-id="{tid}"'  # 真实 EPG 身份映射（iptv-org 频道数据库 id）
   lines.extend([f'#EXTINF:-1 {attrs},{name}',e['url']]);route_count+=1
   rid=route_id(e['url'])
   route_registry.append({'route_id':rid,'channel_id':cid,'channel':name,'group':g,'url':e['url'],'headers':e.get('headers',{}),'upstream_host':urlsplit(e['url']).hostname})
 (ROOT/'reports/route-registry.json').write_text(json.dumps({'routes':route_registry,'policy':'route_id 指纹与播放 URL 分离；channel_id 对应实际频道身份；HD/SD 同频道收敛','channels':len(channels)},ensure_ascii=False,indent=2)+'\n')
 (ROOT/'live.m3u').write_text('\n'.join(lines)+'\n')
 api={'spider':base+'home.jpg','sites':[{'key':'wkc_reviewed_home','name':'WKC · 已审核片单','type':3,'api':'csp_WkcHome','searchable':1,'quickSearch':1,'changeable':1,'filterable':0,'ext':{'catalog_json':data}}], 'lives':[{'name':'WKC · 精选电视直播','type':0,'url':base+'live.m3u','playerType':1,'epg':'http://epg.51zmt.top:8000/api/diyp/'}], 'parses':[], 'flags':[], 'rules':[]}
 if (ROOT/'home.jpg').exists():api['spider']+=';md5;'+hashlib.md5((ROOT/'home.jpg').read_bytes()).hexdigest()
 dump(ROOT/'api.json',api)
 _live_src=json.loads((ROOT/'input/approved-live.json').read_text())
 report={'version':pkg['version'],'policy':'Immutable title whitelist; no raw CMS browse/search/detail; matching catalogue hash required by plugin','reviewed_titles':len(rows),'categories':dict(Counter(v['category'] for v in rows)),'removed_providers':['玉兔','辣椒','滴滴','乐播','火速','光速'],'live_channels':len(channels),'live_routes':route_count,'live_frames_manual':sum(1 for e in _live_src if e.get('frame_review')=='manual' or 'frame_review' not in e),'live_frames_auto':sum(1 for e in _live_src if e.get('frame_review')=='visual-agent'),'live_groups':dict(Counter(g for g,n in channels)), 'live_policy':'Broadcaster host allowlist (data-driven), successful HLS/media probe plus frame inspection (manual for fixed-review entries, agent visual inspection of tiled frames for harvested entries); black/no-signal/placeholder/misnamed/anonymous routes excluded', 'limits':['Poster review and sampled frames only; no full-episode/full-series certification','Remote media may change; runtime URLs do not guarantee future content','No Android device playback test or mainland ISP verification','Live routes: visual review covers sampled still frames, not continuous monitoring'],'original_repo_modified':False,'original_npm_modified':False}
 dump(ROOT/'reports/content-review.json',report)
 # A version's snapshot time must survive rebuilding in CI; otherwise an
 # unchanged manifest differs from both the published package and the CDN.
 previous=json.loads((ROOT/'manifest.json').read_text()) if (ROOT/'manifest.json').exists() else {}
 same_version=previous.get('package')==pkg['name'] and previous.get('version')==pkg['version']
 generated_at=previous.get('generated_at') if same_version else None
 if not generated_at:generated_at=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())
 manifest={**report,'package':pkg['name'],'generated_at':generated_at,'catalog_sha256':digest,'files':{f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in ['api.json','live.m3u','home.jpg'] if (ROOT/f).exists()}}
 for p in (ROOT/'posters').glob('*'):manifest['files'][str(p.relative_to(ROOT))]=hashlib.sha256(p.read_bytes()).hexdigest()
 dump(ROOT/'manifest.json',manifest);print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
