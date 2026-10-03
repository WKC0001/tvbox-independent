import json,re,hashlib,unicodedata,time,sys
from collections import defaultdict,Counter
from urllib.parse import urlsplit
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];PACK=json.loads((ROOT/'package.json').read_text());VERSION=PACK['version'];PACKAGE=PACK['name'];BASE=f'https://cdn.jsdelivr.net/npm/{PACKAGE}@{VERSION}/'
GROUPS=['央视','卫视','地方','港澳台','新闻国际','体育','少儿','纪录']
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
 # iptv-org 英文台名 → 标准中文卫视名（频道身份归并：省级上星台不得误入国际组）
 name={'Hunan TV':'湖南卫视','Qinghai TV':'青海卫视','Xinjiang TV':'新疆卫视','Yunnan TV':'云南卫视',
  'Guizhou TV':'贵州卫视','Guangxi TV':'广西卫视','Gansu TV':'甘肃卫视','Jilin TV':'吉林卫视',
  'Liaoning TV':'辽宁卫视','Shanxi TV':'山西卫视','Shaanxi TV':'陕西卫视','Henan TV':'河南卫视',
  'Hubei TV':'湖北卫视','Hebei TV':'河北卫视','Sichuan TV':'四川卫视','Anhui TV':'安徽卫视',
  'Jiangxi TV':'江西卫视','Tianjin TV':'天津卫视','Chongqing TV':'重庆卫视','Shandong TV':'山东卫视',
  'Guangdong TV':'广东卫视','Shenzhen TV':'深圳卫视','Heilongjiang TV':'黑龙江卫视',
  'Nei Mongol TV':'内蒙古卫视','Ningxia TV':'宁夏卫视','Tibet TV':'西藏卫视','Bingtuan TV':'兵团卫视',
  'Xiamen TV':'厦门卫视','Hainan TV':'海南卫视','Hunan International Channel':'湖南国际频道',
  'Xinjiang TV 2':'新疆卫视维吾尔语','Xinjiang TV 3':'新疆卫视哈萨克语','Xinjiang TV 8':'新疆卫视少儿频道',
  'Zhejiang International Channel':'浙江国际','Zhejiang TV International':'浙江国际','Harbin Movie Channel':'哈尔滨影视',
  'CGTN记录':'CGTN纪录','CGTN Spanish':'CGTN西语','CGTN French':'CGTN法语',
  'CGTN Russian':'CGTN俄语','CGTN Arabic':'CGTN阿拉伯语','CGTN Documentary':'CGTN纪录',
  '凤凰中文台':'凤凰中文','鳳凰衛視中文台':'凤凰中文','鳳凰衛視資訊台':'凤凰资讯','凤凰卫视台':'凤凰卫视',
  'TVBS-Asia':'TVBS亚洲','TVBS Asia':'TVBS亚洲','翡翠台':'TVB翡翠台','RTHK31':'港台电视31','港台電視31':'港台电视31'}.get(name,name)
 if not name or re.match(r'^\d{4}-\d{2}-\d{2} ',name) or name in ('卫视频道','央视频道','更新','更新时间','4K'):return None
 sg=e.get('source_group','');country=m.get('country','') if m else ''
 ott=bool(re.search(r'/(?:huya|douyu|yy)/',e['url']))
 if re.search('电视塔|醉美|沙滩|风景|景区|慢直播|雪山|大熊猫|黄山|峨眉|漓江',name):return None  # 风景慢直播不入目录
 elif name.upper().startswith('CCTV'):g='央视'
 elif country in ('HK','MO','TW') or re.search(r'^凤凰|^鳳凰|翡翠台|香港|澳门|澳視|東森|东森|三立|TVBS|民視|中天|港台电视',name,re.I):g='港澳台'
 elif '卫视' in name:g='卫视'
 elif re.search('体育|體育|sport|足球|篮球|围棋',name,re.I):g='体育'
 elif re.search('少儿|卡通|动漫|纪实|纪录|紀錄|七龙珠|哆啦|动画|海贼王|蜡笔小新',name):
  g='纪录' if re.search('纪实|纪录|紀錄|documentary',name,re.I) else '少儿'
 elif re.search('(?:一套|二套|三套|综合|新闻|生活|教育|经济法制|维吾尔|哈萨克)$',name):g='地方'  # 地方台名优先于中转链路判定
 elif re.search('春晚|综艺|德云|相声|小品|脱口秀',name) or ott:return None  # 轮播/匿名中转不入目录
 elif re.search('音乐|音樂|演唱会|MV|Music',name,re.I):return None
 elif re.search('「B站」|「斗鱼」|「虎牙」|电竞|王者荣耀|英雄联盟|斗地主|第五人格|原神|金铲铲|使命召唤|和平精英|游戏|火影忍者',name):return None
 elif re.search('轮播|電影|影院|剧场|电影|电视剧|影视',name):return None  # 影视轮播不入目录
 elif name.upper().startswith('CGTN') or (country and country not in ('CN','HK','MO','TW')) or re.search('[A-Za-z]{2}',name):g='新闻国际'
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

