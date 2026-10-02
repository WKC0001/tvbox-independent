import json,re,hashlib,unicodedata,time,sys
from collections import defaultdict,Counter
from urllib.parse import urlsplit
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];PACK=json.loads((ROOT/'package.json').read_text());VERSION=PACK['version'];PACKAGE=PACK['name'];BASE=f'https://cdn.jsdelivr.net/npm/{PACKAGE}@{VERSION}/'
GROUPS=['央视','卫视','地方','港澳台','影视轮播','体育','少儿与纪录','综艺轮播','音乐','游戏直播','风景慢直播','国际']
SAT=['湖南','浙江','东方','江苏','北京','广东','深圳','山东','安徽','湖北','四川','重庆','河南','河北','江西','辽宁','天津','福建东南','广西','云南','贵州','黑龙江','吉林','山西','陕西','甘肃','青海','宁夏','内蒙古','新疆','西藏','海南','兵团','厦门']
CCTV={1:'综合',2:'财经',3:'综艺',4:'中文国际',5:'体育',6:'电影',7:'国防军事',8:'电视剧',9:'纪录',10:'科教',11:'戏曲',12:'社会与法',13:'新闻',14:'少儿',15:'音乐',16:'奥林匹克',17:'农业农村'}
def load(p):return json.loads(p.read_text())
def dump(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
def norm(s):return re.sub(r'[^\w+]+','',unicodedata.normalize('NFKC',s)).lower()
metadata={x['id']:x for x in load(ROOT/'input/channel-metadata.json')}
aliases={norm(n):x for x in metadata.values() if x.get('country') in ('CN','HK','MO','TW') for n in [x['name']]+x.get('alt_names',[]) if n}

def label(e):
 name=unicodedata.normalize('NFKC',e['name']).strip()
 name=re.sub(r'\s*[\[(（][^\])）]*[\])）]','',name)
 name=re.sub(r'(?i)\b(?:fullhd|fhd|hd|sd)\b|超高清|超清|高清|标清|\d{3,4}p|\[.*?\]|频道','',name).strip()
 ident=e.get('id','').split('@')[0];m=metadata.get(ident) or aliases.get(norm(name))
 if m:
  if m.get('is_nsfw'):return None
  chinese=next((n for n in m.get('alt_names',[]) if re.search('[\u4e00-\u9fff]',n)),None)
  if chinese:name=chinese
  elif not re.search('[\u4e00-\u9fff]',name):name=m['name']
 name=name.replace('中央电视台','CCTV').replace('中央','CCTV')
 match=re.match(r'(?i)^CCTV[\s_-]*(\d{1,2})(\+|plus)?',name)
 if match:
  n=int(match[1]);rest=name[match.end():];plus=bool(match[2])
  if re.search(r'(?i)4k|8k',name):
   name='CCTV-8K' if '8k' in name.lower() else 'CCTV-4K'
  elif re.search('欧洲|美洲',rest):name=f'CCTV-{n}'+('欧洲' if '欧洲' in rest else '美洲')
  elif n in CCTV:name=f'CCTV-{n}'+('+' if plus else '')+' '+('体育赛事' if plus else CCTV[n])
 name={'东南卫视':'福建东南卫视','凤凰中文台':'凤凰中文','凤凰资讯台':'凤凰资讯','东方卫视高清':'东方卫视'}.get(name,name)
 name={'鳳凰衛視中文台':'凤凰中文','鳳凰衛視資訊台':'凤凰资讯','凤凰卫视台':'凤凰卫视','TVBS-Asia':'TVBS亚洲','TVBS Asia':'TVBS亚洲','CGTN记录':'CGTN纪录','翡翠台':'TVB翡翠台','RTHK31':'港台电视31','港台電視31':'港台电视31'}.get(name,name)
 if not name or re.match(r'^\d{4}-\d{2}-\d{2} ',name) or name in ('卫视频道','央视频道','更新','更新时间','4K'):return None
 sg=e.get('source_group','');country=m.get('country','') if m else ''
 ott=bool(re.search(r'/(?:huya|douyu|yy)/',e['url']))
 if re.search('电视塔|醉美|沙滩|风景|景区|慢直播|雪山|大熊猫|黄山|峨眉|漓江',name):g='风景慢直播'
 elif name.upper().startswith('CCTV'):g='央视'
 elif country in ('HK','MO','TW') or re.search(r'^凤凰|^鳳凰|翡翠台|香港|澳门|澳視|東森|东森|三立|TVBS|民視|中天|港台电视',name,re.I):g='港澳台'
 elif '卫视' in name:g='卫视'
 elif re.search('体育|體育|sport|足球|篮球|围棋',name,re.I):g='体育'
 elif re.search('少儿|卡通|动漫|纪实|纪录|紀錄|七龙珠|哆啦|动画|海贼王|蜡笔小新',name):g='少儿与纪录'
 elif re.search('春晚|综艺|德云|相声|小品|脱口秀|综艺',name) :g='综艺轮播'
 elif re.search('音乐|音樂|演唱会|MV|Music',name,re.I):g='音乐'
 elif re.search('「B站」|「斗鱼」|「虎牙」|电竞|王者荣耀|英雄联盟|斗地主|第五人格|原神|金铲铲|使命召唤|和平精英|游戏|火影忍者',name):g='游戏直播'
 elif re.search('(?:一套|二套|三套|综合|新闻|生活|教育|经济法制|维吾尔|哈萨克)$',name):g='地方'
 elif re.search('轮播|電影|影院|剧场|电影|电视剧|影视',name) or ott:g='影视轮播'
 elif name.upper().startswith('CGTN') or (country and country not in ('CN','HK','MO','TW')) or re.search('[A-Za-z]{2}',name):g='国际'
 else:g='地方'
 # Same display name inside a group is one app channel; retain regional parts of local names.
 return g,name,m

def live_sort(item):
 (g,name),routes=item
 if g=='央视':
  m=re.search(r'CCTV-(\d+)(\+)?',name);key=(int(m[1]),bool(m[2]),name) if m else (99,False,name)
 elif g=='卫视':key=(next((i for i,x in enumerate(SAT) if name.startswith(x)),99),False,name)
 else:key=(0,False,name)
 return (GROUPS.index(g),key)

def category_map(classes):
 from probe import category,CATS
 blocked=re.compile('伦理|倫理|成人|色情|预告|預告|擦边|擦邊')
 byid={str(c['type_id']):c for c in classes};mapping={k:[] for k in CATS};allowed=[]
 for c in classes:
  name=str(c.get('type_name',''))
  if blocked.search(name):continue
  k=category(name)
  if not k:
   parent=byid.get(str(c.get('type_pid','')),{})
   k=category(str(parent.get('type_name','')))
  if k:mapping[k].append(str(c['type_id']));allowed.append(name)
 for k in CATS:
  root=next((c for c in classes if c.get('type_name') in ([k,'连续剧'] if k=='电视剧' else [k,'记录片'] if k=='纪录片' else [k]) and str(c.get('type_pid','0'))=='0'),None)
  if root:mapping[k]=[str(root['type_id'])]
 return mapping,list(dict.fromkeys(allowed))

def main():
 probe=ROOT/'probe-output';reports=ROOT/'reports';reports.mkdir(exist_ok=True)
 original=load(probe/'original-api.json');accepted=[x for x in load(probe/'vod-probes.json') if x.get('accepted')]
 # Prefer verified media, then category/poster coverage and measured latency. Aliases share a provider family.
 preference=['电影天堂','光影','量子','非凡','新浪','索尼','无尽','红牛','暴風','光速','闪电','极速','玉兔','辣椒','金鹰','360','百度','茅台','乐播']
 def friendly(s):
  n=re.sub(r'采集|资源|影视|直连|\(切\)|\[直连\]|[┃|｜\[\]🍓💮🧀🌞️]','',s).strip()
  n=n.replace('天堂','电影天堂') if n=='天堂' else n
  return n or '影视接口'
 for x in accepted:
  x['display_name']=friendly(x['name']);x['categories'],x['allowed_classes']=category_map(x['classes'])
 accepted.sort(key=lambda x:(not x.get('media_verified'),-sum(bool(v) for v in x['categories'].values()),x.get('list_ms',999999) if x.get('media_verified') else next((i for i,n in enumerate(preference) if n in x['display_name']),99),x.get('list_ms',999999)))
 primary=[];backup=[];seen=set();profiles=[];endpoints=set()
 for x in accepted:
  family=next((n for n in preference if n in x['display_name']),x['display_name'])
  host=urlsplit(x['api']).netloc
  identity=(host,x['flag'])
  if identity in endpoints:continue
  endpoints.add(identity)
  key='wkc_'+hashlib.sha256((host+urlsplit(x['api']).path.rstrip('/')).encode()).hexdigest()[:12]
  x['key']=key;x['family']=family
  if family in seen:backup.append(x)
  else:primary.append(x);seen.add(family)
 accepted=primary+backup
 for x in accepted:profiles.append({'key':x['key'],'name':x['display_name'],'api':x['api'],'categories':x['categories']})
 assert len(primary)>=6,'Enrichment did not add enough independent provider families'
 sites=[{'key':'wkc_home','name':'首页｜精选片单','type':3,'api':'csp_WkcHome','searchable':1,'quickSearch':0,'changeable':1,'ext':{'sources':profiles},'categories':['电视剧','电影','综艺','动漫','纪录片','短剧'],'style':{'type':'rect','ratio':0.67}}]
 for i,x in enumerate(accepted):
  name=x['display_name']+('｜备用' if x in backup else '')+('｜待实播' if not x.get('media_verified') else '')
  sites.append({'key':x['key'],'name':name,'type':1,'api':x['api'],'searchable':1,'quickSearch':int(i<4),'changeable':1,'categories':x['allowed_classes']})
 channels=defaultdict(list);excluded=[];seenurls=set();aliasesmerged=Counter();live=load(probe/'live-probes.json')
 for e in sorted([x for x in live if x['ok']],key=lambda e:e.get('ms',999999)):
  if e['url'] in seenurls:continue
  seenurls.add(e['url']);name=label(e)
  if not name:excluded.append(e);continue
  g,n,m=name;channels[(g,n)].append(e)
  if n!=e['name']:aliasesmerged[n]+=1
 # Resolve display-name group conflicts; upstream often labels movie loops as local TV.
 namegroups=defaultdict(list)
 for g,n in list(channels):namegroups[n].append(g)
 for n,gs in namegroups.items():
  if len(gs)<2:continue
  target=next((g for g in gs if g!='地方'),gs[0]);combined=[]
  for g in gs:combined.extend(channels.pop((g,n)))
  channels[(target,n)]=sorted(combined,key=lambda e:e.get('ms',999999))
 # Limit three routes per channel and choose distinct hosts first, preserving headers for each route.
 for k,es in channels.items():
  picked=[];hosts=set()
  for e in es:
   h=urlsplit(e['url']).netloc
   if h not in hosts:picked.append(e);hosts.add(h)
   if len(picked)>=3:break
  for e in es:
   if len(picked)>=3:break
   if e not in picked:picked.append(e)
  channels[k]=picked
 assert len(channels)>59,'Live enrichment did not improve channel coverage'
 lines=['#EXTM3U'];summary=[]
 for (g,n),es in sorted(channels.items(),key=live_sort):
  ident=es[0].get('id','');summary.append({'group':g,'name':n,'routes':len(es),'origins':list(dict.fromkeys(e['origin'] for e in es)),'urls':[e['url'] for e in es]})
  for e in es:
   ua=e.get('headers',{}).get('User-Agent','')
   attr=(' http-user-agent="'+ua.replace('"','')+'"') if ua else ''
   lines.append(f'#EXTINF:-1 tvg-id="{ident}" group-title="{g}"{attr},{n}')
   for k,h in [('User-Agent','http-user-agent'),('Referer','http-referrer')]:
    if e.get('headers',{}).get(k):lines.append('#EXTVLCOPT:'+h+'='+e['headers'][k])
   lines.append(e['url'])
 (ROOT/'live.m3u').write_text('\n'.join(lines)+'\n')
 md5=hashlib.md5((ROOT/'home.jpg').read_bytes()).hexdigest()
 api={'spider':BASE+'home.jpg;md5;'+md5,'sites':sites,'lives':[{'name':'WKC｜分类直播','url':BASE+'live.m3u','ua':'okhttp/4.12.0','timeout':10}], 'parses':[],'flags':[]}
 dump(ROOT/'api.json',api)
 groups={g:sum(x['group']==g for x in summary) for g in GROUPS}
 cctv_missing=[f'CCTV-{n}' for n in range(1,18) if not any(s['group']=='央视' and re.match(f'^CCTV-{n}(?: |$)',s['name']) for s in summary)]
 sat_missing=[x+'卫视' for x in SAT if not any(x in s['name'] for s in summary if s['group']=='卫视')]
 audit={'original_url':'https://cdn.jsdelivr.net/npm/wkc0001-tvbox@latest/api.json','sha256':hashlib.sha256((probe/'original-api.json').read_bytes()).hexdigest(),'site_count':len(original.get('sites',[])),'live_entries':original.get('lives',[]),'sites':[{'key':s.get('key'),'name':s.get('name'),'type':s.get('type'),'api':s.get('api'),'requires_adapter':s.get('type')==3} for s in original.get('sites',[])],'note':'Adapters, encrypted ext and non-movie entries are not silently copied into the independent config.'}
 dump(reports/'original-source-audit.json',audit)
 ranking=[{'rank':i+1,'name':s['display_name'],'api':s['api'],'family':s['family'],'media_verified':s['media_verified'],'categories':list(k for k,v in s['categories'].items() if v),'list_ms':s['list_ms'],'backup':s in backup} for i,s in enumerate(accepted)]
 report={'version':VERSION,'vod_sites':len(accepted),'vod_provider_families':len(primary),'home_sites':1,'vod_media_verified':sum(s['media_verified'] for s in accepted),'vod_order':ranking,'live_channels':len(summary),'live_routes':sum(s['routes'] for s in summary),'live_groups':groups,'live_channel_list':summary,'missing_cctv':cctv_missing,'missing_satellite':sat_missing,'cctv5plus_present':any('CCTV-5+' in s['name'] for s in summary),'raw_routes':load(probe/'input-report.json')['raw_routes'],'tested_routes':len(live),'passed_routes':sum(x['ok'] for x in live),'failed_routes':sum(not x['ok'] for x in live),'normalization_count':sum(aliasesmerged.values()),'excluded_nsfw_or_placeholder':len(excluded),'tested_at':load(probe/'input-report.json')['generated_at'],'validation':'CMS list, exact/negative search, detail, categories, direct M3U8 line filter; sampled HLS child/segment bytes; JVM homepage failover/dedup/routing tests. No device first-frame, UI, or China ISP certification.','update_policy':'manual test release; no scheduled polling enabled'}
 dump(reports/'enrichment-report.json',report)
 for f in ['vod-probes.json','input-report.json']:dump(reports/f,load(probe/f))
 manifest={'package':PACKAGE,'version':VERSION,'vod_sites':len(sites),'home_categories':api['sites'][0]['categories'],'live_channels':len(summary),'live_routes':report['live_routes'],'generated_at':report['tested_at'],'files':{n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in ['api.json','live.m3u','home.jpg']}}
 dump(ROOT/'manifest.json',manifest)
 print(json.dumps({k:report[k] for k in ['vod_sites','vod_provider_families','vod_media_verified','live_channels','live_routes','live_groups','missing_cctv','missing_satellite']},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
