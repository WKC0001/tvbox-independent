"""Lossless playlist import and stable television identities, independent of health."""
import hashlib
import json
import re
import unicodedata
from urllib.parse import urlsplit, unquote, parse_qsl, urlencode
from checker.health import effective

ALIASES = {
 'CCTV-6电影':'CCTV-6', 'CGTN英语':'CGTN', 'CGTN记录':'CGTN纪录',
 '上海第一财经':'第一财经', '凤凰资讯台':'凤凰资讯', '凤凰香港台':'凤凰香港',
 '凤凰卫视台':'凤凰中文', '凤凰卫视':'凤凰中文', '无线新闻':'无线新闻台',
 'TVB翡翠台':'翡翠台', 'TVB明珠台':'明珠台', 'TVB星河':'无线星河',
 '福建海峡卫视':'海峡卫视', '陕西农林卫视':'农林卫视', '陕西农林':'农林卫视',
 'CCTV文化精品':'文化精品', 'CCTV怀旧剧场':'怀旧剧场', 'CCTV第一剧场':'第一剧场',
 'CCTV-Culture of Quality SD':'文化精品', 'CCTV-Nostalgia Theater':'怀旧剧场',
 'CCTV-The First Theater':'第一剧场', 'CCTV-Billiards':'央视台球',
 'CCTV-Golf & Tennis':'高尔夫网球', 'CCTV-World Geography SD':'世界地理',
 'CCTV-Weapon & Technology':'兵器科技', 'CCTV-Women\'s Fashion SD':'女性时尚',
 'CCTV-Storm Football':'风云足球', 'CCTV-Storm Music':'风云音乐', 'CCTV-Storm Theater':'风云剧场',
 '广东大湾区':'大湾区卫视', '浙江钱江':'钱江都市', '浙江钱江都市':'钱江都市',
 '浙江经济':'浙江经济生活', '浙江经视':'浙江经济生活', '浙江数码时代':'数码时代',
 '浙江民生':'浙江民生休闲', '浙江教科':'浙江教科影视', '河北TV':'河北卫视',
 '涟水电视台综合':'涟水综合', '邯郸科教':'邯郸科技教育', '徐州新聞綜合':'徐州新闻综合',
 '绍兴电视台公共':'绍兴公共', 'Anhui TV':'安徽卫视', 'Guangdong Satellite TV':'广东卫视',
 'Nei Monggol TV':'内蒙古卫视', 'Hebei TV':'河北卫视', 'Hunan TV':'湖南卫视',
 'Harbin Comprehensive News Channel':'哈尔滨新闻综合', 'Harbin Movie Channel':'哈尔滨影视',
 'Guangzhou TV':'广州综合', 'Lanzhou Comprehensive News Channel':'兰州新闻综合',
 'Zhejiang International Channel':'浙江国际', 'Dragon TV International':'东方国际',
 'Astro AOD':'ASTRO AOD', 'Viutv':'ViuTV',
 'CCTV-1 综合':'CCTV-1', 'CCTV-12 社会与法':'CCTV-12',
 '四平广播电视台综合':'四平综合', '白城新闻综合频道':'白城新闻综合',
 '浙江 I 绍兴综合':'绍兴新闻综合', 'Zhejiang TV International':'浙江国际',
 '新视觉HD':'新视觉',
}
for _city in ('东丰','九台','双辽','柳河','桦甸','汪清','玛纳斯','磐石','通化县','靖宇','龙井'):
    ALIASES[_city] = _city + '综合'

PROVINCES = {
 '浙江': '浙江 杭州 宁波 温州 嘉兴 湖州 绍兴 金华 衢州 舟山 台州 丽水 余姚 余杭 云和 庆元 开化 文成 新昌 普陀 松阳 永嘉 洞头 海宁 平湖 缙云 象山 诸暨 遂昌 衢江 龙游 上虞 武义 嵊州 嵊泗 义乌 钱江 萧山 青田 兰溪 东阳 数码时代 中国蓝',
 '江苏': '江苏 南京 苏州 徐州 无锡 常州 南通 连云港 淮安 盐城 扬州 镇江 泰州 宿迁 宜兴 新沂 沭阳 涟水 滨海 靖江 句容 武进',
 '吉林': '吉林 长春 四平 通化 白山 白城 松原 辽源 延边 九台 东丰 双辽 柳河 桦甸 汪清 磐石 舒兰 珲春 辉南 龙井 靖宇 德惠 敦化 梅河口 长白',
 '四川': '四川 成都 绵阳 乐山 宜宾 雅安 甘孜 阿坝 叙州 名山 广安 旺苍 汶川 沐川 泸县 金川 营山 松潘 青川 井研 荥经 乐至 仁寿',
 '河北': '河北 石家庄 唐山 秦皇岛 邯郸 邢台 保定 张家口 承德 沧州 廊坊 衡水 平泉 昌黎 滦平 清河 任丘 兴隆',
 '广东': '广东 广州 深圳 珠海 汕头 佛山 韶关 湛江 肇庆 江门 茂名 惠州 梅州 汕尾 河源 阳江 清远 东莞 中山 潮州 揭阳 云浮',
 '安徽': '安徽 合肥 芜湖 蚌埠 淮南 马鞍山 淮北 铜陵 安庆 黄山 滁州 阜阳 宿州 六安 亳州 池州 宣城 固镇 广德 祁门',
 '甘肃': '甘肃 兰州 嘉峪关 金昌 白银 天水 武威 张掖 平凉 酒泉 庆阳 定西 陇南 天祝 永昌 渭源 秦安 西峰',
 '山西': '山西 太原 大同 阳泉 长治 晋城 朔州 晋中 运城 忻州 临汾 吕梁 万荣 古县 大宁 怀仁 长子 定襄 太谷 汾西',
 '新疆': '新疆 乌鲁木齐 克拉玛依 吐鲁番 哈密 阿克苏 和田 喀什 伊犁 奎屯 玛纳斯 可克达拉 兵团',
 '山东': '山东 济南 青岛 淄博 枣庄 东营 烟台 潍坊 济宁 泰安 威海 日照 临沂 德州 聊城 滨州 菏泽',
 '广西': '广西 南宁 柳州 桂林 梧州 北海 防城港 钦州 贵港 玉林 百色 贺州 河池 来宾 崇左 宾阳 灌阳 田东',
 '福建': '福建 福州 厦门 泉州 漳州 莆田 三明 南平 龙岩 宁德 云霄 晋江',
 '黑龙江':'黑龙江 哈尔滨 齐齐哈尔 牡丹江 佳木斯 大庆 鸡西 双鸭山 伊春 七台河 鹤岗 黑河 绥化 甘南县',
 '湖北':'湖北 武汉 黄石 十堰 宜昌 襄阳 鄂州 荆门 孝感 荆州 黄冈 咸宁 随州 恩施 江夏',
 '湖南':'湖南 长沙 株洲 湘潭 衡阳 邵阳 岳阳 常德 张家界 益阳 郴州 永州 怀化 娄底',
 '云南':'云南 昆明 曲靖 玉溪 保山 昭通 丽江 普洱 临沧 大理 楚雄 易门 通海',
 '辽宁':'辽宁 沈阳 大连 鞍山 抚顺 本溪 丹东 锦州 营口 阜新 辽阳 盘锦 铁岭 朝阳 葫芦岛',
 '上海':'上海 东方 第一财经 纪实人文 欢笑剧场 都市剧场 乐游', '北京':'北京 BRTV',
 '天津':'天津 津南', '重庆':'重庆 铜梁 璧山 江津', '河南':'河南 郑州 洛阳 开封 鹤壁',
 '海南':'海南 三沙', '陕西':'陕西 西安', '贵州':'贵州 贵阳 安顺', '青海':'青海 西宁',
 '宁夏':'宁夏 银川', '内蒙古':'内蒙古 赤峰', '西藏':'西藏 拉萨 康巴', '江西':'江西 南昌',
}


def uid(prefix, value):
    return prefix + hashlib.sha256(value.encode()).hexdigest()[:20]


def parse_m3u(text, origin):
    records, info = [], None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith('#EXTINF:'):
            quoted, pos = False, None
            for i, char in enumerate(line):
                if char == '"': quoted = not quoted
                elif char == ',' and not quoted: pos = i; break
            if pos is None: raise ValueError('Malformed EXTINF: missing name delimiter')
            attrs = dict(re.findall(r'([\w-]+)="([^"]*)"', line[:pos]))
            info = {'name': line[pos+1:].strip(), 'attributes': attrs, 'origin': origin,
                    'group': attrs.get('group-title', ''), 'headers': {}, 'directives': []}
            for attr, header in [('http-user-agent','User-Agent'),('http-referrer','Referer'),('http-origin','Origin')]:
                if attrs.get(attr): info['headers'][header] = attrs[attr]
        elif info and line.startswith('#'):
            info['directives'].append(line)
            for prefix, header in [('#EXTVLCOPT:http-user-agent=','User-Agent'),('#EXTVLCOPT:http-referrer=','Referer'),('#EXTVLCOPT:http-origin=','Origin')]:
                if line.startswith(prefix): info['headers'][header] = line[len(prefix):]
        elif info and line:
            url = line
            if '|' in line:
                url, suffix = line.split('|', 1)
                for key, value in parse_qsl(suffix): info['headers'][key] = value
            records.append({**info, 'url': url, 'source_record': len(records)+1})
            info = None
    return records


def canonical(name):
    name = unicodedata.normalize('NFKC', name).strip()
    name = re.sub(r'\s*\[(?:Not 24/7|Geo-blocked)\]', '', name, flags=re.I)
    name = re.sub(r'\s*\((?:\d{3,4}[pi]|HD|FHD|SD)\)', '', name, flags=re.I)
    name = re.sub(r'\s+(?:HD|FHD|UHD|1080P|720P)$', '', name, flags=re.I)
    name = re.sub(r'(?<=\d)[kK]', 'K', name)
    m = re.fullmatch(r'CCTV[- ]?(\d+)([+K]?)', name, re.I)
    if m: name = 'CCTV-' + str(int(m[1])) + m[2].upper()
    return ALIASES.get(name, name)


def exclusion(record):
    url, name = record['url'], record['name']
    p = urlsplit(url); host = (p.hostname or '').lower()
    # Exact path segments and domain suffixes: "shuyang" is not "huya".
    parts = {unquote(s).lower() for s in p.path.split('/')}
    if parts & {'huya','douyu','yy','huyayqk','douyuyqk','yylunbo'} or any(
        host == d or host.endswith('.'+d) for d in ('huya.com','douyu.com','yy.com','huya.live')):
        return 'platform-carousel'
    if re.search(r'斗鱼|虎牙|YY轮播', name, re.I): return 'platform-carousel'
    if '/bs3/video-hls/' in p.path or '/asp/hls/' in p.path or '/video/3005/record/' in p.path:
        return 'on-demand-file'
    if re.search(r'春晚(?:19|20)\d\d|(?:19|20)\d\d年春晚',name):return 'on-demand-file'
    if name=='支持作者' or (re.fullmatch(r'20\d\d-\d\d-\d\d .*',name) and p.path.endswith('.mp4')):
        return 'non-channel-promotion'
    if name in ('西游记','水浒传','闯关东') and p.hostname=='173.208.234.146':
        return 'programme-carousel'
    if host=='gcwbndali.v.myalicdn.com' and '/ipanda' in p.path:return 'scenic-webcam'
    if p.path.lower().endswith(('.mp4','.mkv','.avi','.flv','.mov')) and re.search(r'春晚|电影|之谜|求生|航拍|三国|西游|剧', name):
        return 'on-demand-file'
    if host == 'gcalic.v.myalicdn.com' and p.path.startswith('/gc/'):
        return 'scenic-webcam'
    if host in ('ls.qingting.fm','satellitepull.cnr.cn') or '/aac_' in p.path:
        return 'radio-route'
    if re.search(r'成人|色情|潘多拉|Playboy|Hustler', name, re.I): return 'content-quarantine'
    return None


def group(name, previous=''):
    if name.startswith('ASTRO') or name.startswith('韩国电影'):return '国际'
    if name.startswith(('CCTV','CGTN','CETV')) or name in ('文化精品','怀旧剧场','第一剧场','世界地理','兵器科技','央视台球','女性时尚','电视指南','风云剧场','风云足球','风云音乐','高尔夫网球'):
        return '央视及教育'
    if name.startswith(('凤凰','TVB','TVBS','RTHK','HOY','Viu','澳视')) or re.search(r'翡翠|明珠台|无线|东森|三立|台视|纬来|八大|美亚|天映|香港|澳门|耀才|ASTRO|人间卫视', name):
        return '港澳台'
    if '卫视' in name: return '卫视'
    if re.search('体育|足球|围棋|钓鱼|竞赛', name): return '体育'
    if re.search('少儿|动漫|卡通|宝贝', name): return '少儿动漫'
    if name.startswith(('CHC','NewTV','NEWTV')) or name in ('长影频道','电影八点档','黑莓电影','欢笑剧场','都市剧场','重温经典','新视觉'):
        return '电影剧场'
    if name in ('中国交通','中华特产','环球旅游','生态环境','车迷频道','茶友频道','音乐现场','音乐欣赏','梨园'):
        return '文化生活'
    if re.search('纪录|纪实|科教|地理', name): return '纪录科教'
    for province, prefixes in PROVINCES.items():
        if any(name.startswith(w) for w in prefixes.split()): return '地方·' + province
    if previous == '港澳台国际' or re.match(r'^[A-Za-z]', name): return '国际'
    if previous == '地方': return '地方·其他'
    return '其他电视·待核验'


def import_registry(records):
    channels, routes, migration = {}, {}, []
    for row in records:
        name = canonical(row['name'])
        # Timestamp-labelled CCTV-1 stream: retain the actual channel instead of deleting the row.
        if re.fullmatch(r'20\d\d-\d\d-\d\d .*',name) and dict(parse_qsl(urlsplit(row['url']).query)).get('id')=='cctv1hd':
            name='CCTV-1'
        why = exclusion(row)
        channel_id = uid('tv_', name.casefold())
        route_id = uid('r_', row['url']+'\n'+json.dumps(row['headers'],sort_keys=True))
        entry = {'origin':row['origin'], 'record':row['source_record'], 'old_name':row['name'],
                 'old_id':row['attributes'].get('tvg-id',''), 'channel_id':channel_id, 'route_id':route_id,
                 'action':why or ('alias-normalized' if name != row['name'] else 'retained')}
        migration.append(entry)
        # Non-television entries remain fully accounted for in the migration ledger.
        if why and why!='radio-route':
            entry['original'] = row
            continue
        if channel_id not in channels:
            channels[channel_id] = {'id':channel_id,'name':name,'group':group(name,row['group']),
                 'epg_id':'','epg_source':'','epg_checked_at':0,'logo':row['attributes'].get('tvg-logo',''),
                 'identity_status':'imported-needs-review','aliases':[], 'routes':[]}
        channel=channels[channel_id]
        if row['name'] not in channel['aliases']:channel['aliases'].append(row['name'])
        if why=='radio-route':
            entry['original']=row
            channel['identity_status']='television-name-with-audio-route-needs-replacement'
            continue
        if route_id not in channel['routes']:channel['routes'].append(route_id)
        elif not why:entry['action']='duplicate-route-merged'
        route=routes.setdefault(route_id, {'id':route_id,'url':row['url'],'headers':row['headers'],
             'directives':row['directives'],'origins':[],'review':'inherited-television'})
        route['origins'].append({'origin':row['origin'],'record':row['source_record']})
    return list(channels.values()), list(routes.values()), migration


GROUPS = ['央视及教育','卫视','电影剧场','体育','少儿动漫','纪录科教','文化生活','港澳台','国际']

# 实测下载速度比 = 已下载切片的播出时长 ÷ 真实耗时。只有它直接回答"会不会卡"：
# 延迟和可达性回答不了——一个 200ms 就返回清单的源，仍可能每一段都跟不上播放。
# >=1.50 稳定；>=1.00 勉强跟得上；<1.00 必然边看边缓冲。
SPEED_STABLE = 1.50
SPEED_FLOOR = 1.00


def measured_rank(route):
    """实测档位与速度比。返回 (档位, 速度比)，档位越小越优先。

    没有实测数据的线路排在"有实测数据"的后面：这不是说它一定差，
    而是"有证据"本身就比"没有证据"更值得优先；一旦采到数据就会自动归位。
    """
    measured = route.get('measured') or {}
    if not measured:
        return 3, 0.0
    if not measured.get('ok'):
        return 2, 0.0          # 实测打不开 / 切片全失败
    speed = measured.get('speed')
    if not isinstance(speed, (int, float)):
        return 3, 0.0
    return (0 if speed >= SPEED_FLOOR else 1), round(float(speed), 3)


def sort_key(channel):
    g=channel['group']; n=channel['name']
    m=re.fullmatch(r'CCTV-(\d+)([+K]?)',n)
    number=int(m[1])+(0.5 if m[2]=='+' else 30 if m[2]=='K' else 0) if m else 999
    return (GROUPS.index(g) if g in GROUPS else len(GROUPS) if g.startswith('地方') else len(GROUPS)+1,g,number,n)


def epg_identity(channel, now, max_age_days, sources):
    """The guide id this channel may publish, or '' when no source currently vouches for it.

    A stored id is not evidence by itself: it must come from a source we actually query, and
    that source must have confirmed it recently. Everything else degrades to "no guide" rather
    than to a wrong guide, which is why nothing here is ever derived from the channel name.
    """
    value = channel.get('epg_id')
    if not value: return ''
    if channel.get('epg_source') not in sources: return ''
    checked = channel.get('epg_checked_at') or 0
    if not isinstance(checked, int) or checked <= 0: return ''
    if checked > now: return ''
    if now - checked >= max_age_days * 86400: return ''
    return value


def playlist(channels, routes, health, network='domestic', max_routes=3, epg=None):
    def quote(value): return str(value).replace('"',"'").replace('\n',' ').replace('\r',' ')
    # Without an explicit source policy nothing can be verified, so no guide id is emitted at all.
    epg = epg or {}
    sources = set(epg.get('sources') or ())
    now = int(epg.get('now') or 0)
    max_age = epg.get('max_age_days') or 0
    lines=['#EXTM3U']; gaps=[]; route_map={r['id']:r for r in routes}
    for ch in sorted(channels,key=sort_key):
        if ch.get('review')=='excluded': continue
        candidates=[route_map[r] for r in ch['routes'] if r in route_map and route_map[r].get('review')!='quarantined']
        def score(r):
            evidence=health.get(r['id'],{})
            if any(v.get('isolated') for v in evidence.values()):return (99,0,0.0,999999)
            rec=evidence.get(network,{})
            state_rank={'healthy':0,'degraded':1,'unverified':2,'down':3}.get(effective(rec),2)
            quality,speed=measured_rank(r)
            # 顺序：健康状态 → 有没有实测证据/实测好坏 → 速度比（越大越好）→ 延迟（越小越好）。
            # 速度比和延迟不能混在一层比较，因为两者量纲和方向都不同。
            return (state_rank,quality,-speed,rec.get('latency_ms',999999))
        candidates=[r for r in sorted(candidates,key=score) if score(r)[0]<3]
        if not candidates:
            gaps.append({'channel_id':ch['id'],'name':ch['name'],'reason':'no admissible route'})
            continue
        if not any(score(r)[0] == 0 for r in candidates):
            gaps.append({'channel_id':ch['id'],'name':ch['name'],'reason':'no currently verified route on '+network})
        # Keep real imported routes when the network cannot prove them; never synthesize media URLs.
        for r in candidates[:max_routes]:
            attrs={'tvg-name':ch['name'],'group-title':ch['group']}
            guide=epg_identity(ch,now,max_age,sources)
            if guide: attrs['tvg-id']=guide
            if ch.get('local_logo'): attrs['tvg-logo']=ch['local_logo']
            lines.append('#EXTINF:-1 '+' '.join(k+'="'+quote(v)+'"' for k,v in attrs.items())+','+quote(ch['name']))
            mapped={'User-Agent':'http-user-agent','Referer':'http-referrer','Origin':'http-origin'}
            for key,value in r.get('headers',{}).items():
                if key in mapped:lines.append('#EXTVLCOPT:'+mapped[key]+'='+quote(value))
            for directive in r.get('directives',[]):
                if not directive.startswith(('#EXTVLCOPT:http-user-agent=','#EXTVLCOPT:http-referrer=','#EXTVLCOPT:http-origin=')):
                    lines.append(directive)
            extra={k:v for k,v in r.get('headers',{}).items() if k not in mapped}
            lines.append(r['url']+('|' + urlencode(extra) if extra else ''))
    return '\n'.join(lines)+'\n',gaps
