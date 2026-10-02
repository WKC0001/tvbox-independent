import concurrent.futures as cf, hashlib, json, re, time, unicodedata, ipaddress
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urlsplit,urlunsplit,urlencode,parse_qsl,urljoin
from collections import defaultdict
OUT=Path('probe-output');OUT.mkdir(exist_ok=True)
def fetch(url,timeout=9,limit=4000000,headers=None):
 t=time.monotonic()
 try:
  h={'User-Agent':'okhttp/4.12.0',**(headers or {})}
  with urlopen(Request(url,headers=h),timeout=timeout) as r:
   return r.read(limit),r.geturl(),round((time.monotonic()-t)*1000)
 except Exception as e:raise ValueError(str(e)[:160])
def public(u):
 try:
  p=urlsplit(u)
  if p.scheme not in ('http','https') or not p.hostname or p.username:return False
  try:return ipaddress.ip_address(p.hostname).is_global
  except ValueError:return p.hostname not in ('localhost',) and not p.hostname.endswith('.local')
 except:return False
def query(u,**kw):
 p=urlsplit(u);q=dict(parse_qsl(p.query));q.update(kw);return urlunsplit((p.scheme,p.netloc,p.path,urlencode(q),''))
def norm(x):return re.sub(r'\W+','',unicodedata.normalize('NFKC',str(x))).lower()
def media(u,headers=None):
 try:
  b,final,ms=fetch(u,7,65536,headers);s=b.decode(errors='replace').lstrip('\ufeff\r\n ')
  if s.startswith('#EXTM3U'):
   lines=[x.strip() for x in s.splitlines() if x.strip() and not x.startswith('#')]
   if not lines:raise ValueError('empty HLS')
   child=urljoin(final,lines[0]);b2,_,_=fetch(child,6,4096,headers)
   if '#EXT-X-STREAM-INF' in s:
    if not b2.lstrip().startswith(b'#EXTM3U'):raise ValueError('invalid HLS child')
    return {'ok':True,'level':'HLS master + child','ms':ms}
   if not bytes_media(b2):raise ValueError('invalid first segment')
   return {'ok':True,'level':'HLS + media segment','ms':ms}
  if bytes_media(b):return {'ok':True,'level':'media bytes','ms':ms}
  raise ValueError('not media')
 except Exception as e:return {'ok':False,'reason':str(e)[:180]}
def bytes_media(b):return len(b)>24 and ((b[0]==71 and (len(b)<189 or b[188]==71)) or b[4:8] in (b'ftyp',b'styp',b'moof') or b[:3] in (b'FLV',b'ID3') or b[:2] in (b'\xff\xf1',b'\xff\xf9',b'\xff\xfb'))
def cms(u,**kw):
 b,_,ms=fetch(query(u,**kw),12);o=json.loads(b);assert isinstance(o.get('list'),list),'CMS JSON list missing';return o,ms
CATS=['电视剧','电影','综艺','动漫','纪录片','短剧']
def category(name):
 if re.search('短剧|爽文',name):return '短剧'
 if re.search('纪录|记录',name):return '纪录片'
 if re.search('综艺|演唱会',name):return '综艺'
 if re.search('动漫|动画',name):return '动漫'
 if re.search('电视剧|连续剧|国产剧|香港剧|港剧|台湾剧|台剧|欧美剧|韩国剧|韩剧|日本剧|日剧|泰剧|泰国剧|海外剧|自制剧',name):return '电视剧'
 if re.search('片|电影',name):return '电影'
 return None
def vod_probe(x):
 row={**x,'accepted':False}
 try:
  o,ms=cms(x['api'],ac='list',pg=1);classes=o.get('class',[]);items=o['list'];assert items,'empty CMS'
  ids=','.join(str(v['vod_id']) for v in items[:3]);d,_=cms(x['api'],ac='detail',ids=ids)
  flags=list(dict.fromkeys(f for v in d['list'] for f in str(v.get('vod_play_from','')).split('$$$') if 'm3u8' in f.lower()))
  assert flags,'no direct m3u8 line';flag=flags[0];u=query(x['api'],**{'from':flag})
  filtered,_=cms(u,ac='detail',ids=ids)
  assert all(str(v.get('vod_play_from',''))==flag for v in filtered['list']),'line filter ignored'
  known=str(items[0]['vod_name']);s,_=cms(u,ac='detail',wd=known,pg=1)
  assert any(norm(v.get('vod_name',''))==norm(known) for v in s['list']),'exact-title search failed'
  negative,_=cms(u,ac='detail',wd='WKC_NO_MATCH_'+hashlib.sha256(u.encode()).hexdigest()[:20],pg=1)
  assert not negative['list'],'search keyword ignored'
  mapping={k:[] for k in CATS}
  for c in classes:
   k=category(str(c.get('type_name','')))
   if k:mapping[k].append(str(c['type_id']))
  assert sum(bool(v) for v in mapping.values())>=3,'incomplete categories'
  checks=[]
  for v in filtered['list'][:2]:
   ep=str(v.get('vod_play_url','')).split('#')[0];p=ep.split('$',1)[-1]
   checks.append(media(p))
   if checks[-1]['ok']:break
  row.update(accepted=True,api=u,flag=flag,categories=mapping,classes=classes,list_ms=ms,poster_count=sum(bool(v.get('vod_pic')) for v in d['list']),media_verified=any(z['ok'] for z in checks),media_checks=checks,known_title=known)
 except Exception as e:row['reason']=str(e)[:180]
 print('VOD',row['name'],row.get('accepted'),row.get('media_verified'),row.get('reason'),flush=True);return row

def parse_live(text,origin):
 arr=[];info=None;headers={}
 for raw in text.splitlines():
  line=raw.strip()
  if line.startswith('#EXTINF'):
   meta,_,name=line.partition(',');a=dict(re.findall(r'([\w-]+)="([^"]*)"',meta));info={'name':name,'id':a.get('tvg-id',''),'source_group':a.get('group-title',''),'origin':origin};headers={}
  elif line.startswith('#EXTVLCOPT:http-user-agent='):headers['User-Agent']=line.split('=',1)[1]
  elif line.startswith('#EXTVLCOPT:http-referrer='):headers['Referer']=line.split('=',1)[1]
  elif line and not line.startswith('#') and info:
   if public(line):arr.append({**info,'url':line,'headers':headers.copy()})
   info=None
 return arr

def main():
 feeds=[];raw=None
 try:
  b,_,_=fetch('https://cdn.jsdelivr.net/npm/wkc0001-tvbox@latest/api.json',15)
  (OUT/'original-api.json').write_bytes(b);raw=json.loads(b)
  print('ORIGINAL',len(raw.get('sites',[])),len(raw.get('lives',[])),flush=True)
 except Exception as e:raise RuntimeError('Original current URL audit failed: '+str(e))
 candidates=json.loads(Path('input/cms-candidates.json').read_text())
 for s in raw.get('sites',[]):
  if s.get('type')==1 and public(str(s.get('api',''))):candidates.append({'name':s.get('name'),'api':s['api'],'origins':[{'name':'original-current-config'}]})
 unique={}
 for x in candidates:
  p=urlsplit(x['api']);identity=(p.netloc,p.path.rstrip('/'))
  if identity not in unique:unique[identity]=x
 with cf.ThreadPoolExecutor(10) as ex:vod=list(ex.map(vod_probe,unique.values()))
 (OUT/'vod-probes.json').write_text(json.dumps(vod,ensure_ascii=False,indent=2))
 for l in raw.get('lives',[]):
  if 'wkc0001-tvbox@' in str(l.get('url','')):feeds.append(('original-own-live',l['url']))
 feeds += [(x,'https://iptv-org.github.io/iptv/'+x) for x in ['countries/cn.m3u','countries/hk.m3u','countries/mo.m3u','countries/tw.m3u','languages/zho.m3u']]
 feeds += [('vbskycn','https://cdn.jsdelivr.net/gh/vbskycn/iptv@master/tv/iptv4.m3u'),('Guovin','https://cdn.jsdelivr.net/gh/Guovin/iptv@gd/output/result.m3u'),('suxuang','https://cdn.jsdelivr.net/gh/suxuang/myIPTV@main/ipv4.m3u'),('Kimentanm','https://cdn.jsdelivr.net/gh/Kimentanm/aptv@master/m3u/iptv.m3u')]
 entries=parse_live(Path('input/previous-live.m3u').read_text(),'previous-independent');feedreport=[]
 for n,u in feeds:
  try:
   b,_,_=fetch(u,12,8000000);ls=parse_live(b.decode(errors='replace'),n);entries+=ls;feedreport.append({'name':n,'url':u,'channels':len(ls),'ok':True})
  except Exception as e:feedreport.append({'name':n,'url':u,'ok':False,'reason':str(e)})
 uniqueurls={}
 for e in entries:
  if re.search(r'成人|色情|AV频道|潘多拉',e['name'],re.I):continue
  uniqueurls.setdefault(e['url'],e)
 # Bound network checks per identity; preserve previous release and diversify stream hosts.
 buckets=defaultdict(list)
 for e in uniqueurls.values():buckets[e['id'] or norm(re.sub(r'\[.*?\]|\(.*?\)|高清|超清|HD|FHD|标清','',e['name'],flags=re.I))].append(e)
 selected=[]
 for es in buckets.values():
  hosts=set();chosen=[]
  for e in es:
   h=urlsplit(e['url']).netloc
   if h not in hosts:chosen.append(e);hosts.add(h)
   if len(chosen)>=4:break
  for e in es:
   if e not in chosen and len(chosen)<6:chosen.append(e)
  selected+=chosen
 selected=selected[:2000]
 def test(e):return {**e,**media(e['url'],e['headers'])}
 results=[]
 with cf.ThreadPoolExecutor(24) as ex:
  for i,r in enumerate(ex.map(test,selected),1):
   results.append(r)
   if i%100==0:print('LIVE',i,len(selected),sum(x['ok'] for x in results),flush=True)
 (OUT/'live-probes.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
 (OUT/'input-report.json').write_text(json.dumps({'feeds':feedreport,'raw_routes':len(entries),'unique_urls':len(uniqueurls),'tested_routes':len(selected),'generated_at':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'vantage':'GitHub Actions Ubuntu network; not China ISP or device playback'},ensure_ascii=False,indent=2))
 print('DONE',sum(x['accepted'] for x in vod),sum(x['ok'] for x in results),flush=True)
if __name__=='__main__':main()
