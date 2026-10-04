"""节目单上游：把「有哪些源、什么形态、时区该怎么理解」集中在一处登记。

为什么要这一层
--------------
原来只有 51zmt 一家（diyp JSON 接口 + cc.xml 两份数据都是它）。它是单台小机，
实测整台失联：2026-10-04 起 `cc.xml` 与 `api/diyp/` 都直接 Empty reply，节目单
当场降级到缓存（频道从 125 掉到 63）。单一上游失联就等于节目单整体塌陷，所以
这里允许登记多个上游，并且每个上游自己声明它的时区该怎么理解。

时区必须显式声明
----------------
epg.pw 把**北京时间**按 `+0000` 标进文件：新闻联播字面在 19:00、朝闻天下在 06:00
（都是北京时间），凌晨 02:30 的「晚间新闻」是重播。照抄那个 `+0000` 会让播放器
把整份节目单往后挪 8 小时——19:00 的新闻联播会显示在凌晨 3 点。

所以每个上游带两个时区字段：
  * `declared_tz` —— 文件里实际写着的时区标记；
  * `tz`           —— 这些字面数字**真正所属**的时区。
归一化的做法是把标记换成 `tz`，**数字一字不动**。这不是"按时区差做位移"：
epg.pw 的数字本来就是北京时间，只是标签贴错了。做真实位移反而会把它推偏。

认领频道的标准
--------------
不论哪家上游，认领一个频道都只有一条路：它确实返回了节目，且它给出的频道名
仍然像同一个频道。没有任何一步是按命名规则凭空推出来的。
"""
import gzip
import re
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / '.build-cache'

CHANNEL_BLOCK = re.compile(r'<channel id="([^"]*)"[^>]*>(.*?)</channel>', re.S)
DISPLAY = re.compile(r'<display-name[^>]*>([^<]*)</display-name>')
PROGRAMME_CHANNEL = re.compile(r'<programme\s[^>]*channel="([^"]*)"')
PROGRAMME_DAY = re.compile(r'<programme\s[^>]*start="(\d{8})')
# 一个 <programme> 开标签里同时取频道和日期。分块取而不是各取一次，是因为
# channel 与 start 的先后顺序各家写法不同（epg.pw 是 channel 在前），两条独立
# 的 findall 对不上号。
PROGRAMME_TAG = re.compile(r'<programme\s[^>]*?>', re.S)
STAMP = re.compile(r'\b\d{14}\s*([+-]\d{4})')
SLUG = re.compile(r'[^a-z0-9]+')


def host_of(url):
    body = re.sub(r'^\w+://', '', str(url)).split('/')[0]
    return body.split(':')[0] or 'upstream'


def slug_of(name):
    return SLUG.sub('-', str(name).lower()).strip('-') or 'upstream'


def normalize_upstream(entry):
    """接受字符串（旧写法）或字典；补齐时区字段，默认认为上游声明即真实。"""
    if isinstance(entry, str):
        entry = {'url': entry}
    url = str(entry['url'])
    tz = str(entry.get('tz') or '+0800')
    out = {
        'name': str(entry.get('name') or host_of(url)),
        'url': url,
        'tz': tz,
        'declared_tz': str(entry.get('declared_tz') or tz),
    }
    # 按「频道 + 日期」回查的接口模板。整份 XMLTV 里多数频道只有一天，想要第二天
    # 只能走这条路；没有它就说明这家上游只能给整份文件里那点天数。
    if entry.get('day_api'):
        out['day_api'] = str(entry['day_api'])
    return out


def upstreams(policy):
    """policy 里登记的 XMLTV 上游。兼容旧的单个 `epg_guide_upstream`。"""
    listed = policy.get('epg_guide_upstreams')
    if listed:
        return [normalize_upstream(x) for x in listed]
    one = policy.get('epg_guide_upstream')
    return [normalize_upstream(one)] if one else []


def retime(text, up):
    """把上游写错（或写法不同）的时区标记换成它真实所属的时区，数字不动。"""
    if up['declared_tz'] == up['tz']:
        return text
    return STAMP.sub(lambda m: m.group(0)[:-5] + up['tz'], text)


def fetch(url, timeout=60):
    request = urllib.request.Request(url, headers={'User-Agent': 'okhttp/4.12.0'})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def load(up, attempts=4, log=None):
    """下载一份上游 XMLTV。上游抖动时退回上一次的缓存，而不是让节目单塌陷。

    返回 (文本, 来源)；来源只可能是 'upstream' 或 'cache'，绝不伪造。
    """
    cache = CACHE_DIR / ('epg-%s.xml' % slug_of(up['name']))
    last = None
    for attempt in range(attempts):
        try:
            body = fetch(up['url'])
            if body[:2] == b'\x1f\x8b':
                body = gzip.decompress(body)
            text = body.decode('utf-8', 'replace')
            if '<programme' in text or '<channel' in text:
                CACHE_DIR.mkdir(parents=True, exist_ok=True)
                cache.write_text(text, encoding='utf-8')
                return retime(text, up), 'upstream'
            last = 'upstream returned no programme/channel element'
        except Exception as exc:
            last = exc
        if attempt + 1 < attempts:
            time.sleep(5 * (attempt + 1))
    if cache.exists():
        if log:
            print('     %s unavailable (%s); reusing cached %s' % (up['name'], last, cache),
                  file=log)
        return retime(cache.read_text(encoding='utf-8'), up), 'cache'
    raise RuntimeError('%s unavailable and no cached copy: %s' % (up['name'], last))


def index(text, normalize=None):
    """解析一份 XMLTV：频道 id -> 显示名（原文），每个频道的节目数，以及覆盖日期。

    `exact` 是归一化显示名到频道 id 的直接索引。几百个频道要跟几百个频道两两比
    较，先走一遍哈希能省掉绝大部分 `same_channel` 调用；它没有命中时仍然会退回
    逐条比较，所以加这个索引只会更快，不会改变结果。
    """
    names, counts, days, exact, cadays = {}, {}, set(), {}, {}
    for channel_id, block in CHANNEL_BLOCK.findall(text):
        for name in DISPLAY.findall(block):
            if name.strip():
                names[channel_id] = name.strip()
                if normalize:
                    key = normalize(name.strip())
                    if key and key not in exact:
                        exact[key] = channel_id
                break
    for tag in PROGRAMME_TAG.findall(text):
        found = PROGRAMME_CHANNEL.search(tag)
        if not found:
            continue
        channel_id = found.group(1)
        counts[channel_id] = counts.get(channel_id, 0) + 1
        day = PROGRAMME_DAY.search(tag)
        if day:
            days.add(day.group(1))
            cadays.setdefault(channel_id, set()).add(day.group(1))
    # `days` 是整份文件的天数，`cadays` 是**每个频道自己**的天数。两者差别很大：
    # epg.pw 整份给七天，但 654 个频道里只有热门台真有七天，多数只有一两天。
    # 挑上游时必须看后者，看前者会把频道锁死在只给一天的那家上。
    return {'names': names, 'counts': counts, 'days': sorted(days), 'exact': exact,
            'cadays': cadays}


def days(text):
    """这份 XMLTV 实际覆盖了哪几天（YYYYMMDD）。"""
    return sorted(PROGRAMME_DAY.findall(text))


def confirm(up, idx, name, normalize, same_channel):
    """上游是否真的在提供这个频道的节目。命中返回证据，没命中返回 None。

    这里的"命中"不靠猜名字：上游必须给出一个显示名，且该名字与我们的频道名
    经同一套 `same_channel` 判定为同一频道，同时这个上游频道名下确有节目。
    三条缺一不可，任何一条不满足就当没看见，不去认领。
    """
    want = normalize(name)
    if not want:
        return None
    # 精确索引先走一遍：命中就是同一条，省掉整轮逐条比较。
    direct = idx.get('exact', {}).get(want)
    if direct is not None and idx['counts'].get(direct, 0) > 0:
        theirs = idx['names'].get(direct, '')
        if theirs:
            return {'id': direct, 'served_name': theirs,
                    'programmes': idx['counts'][direct], 'upstream': up['name']}
    for channel_id, theirs in idx['names'].items():
        if idx['counts'].get(channel_id, 0) <= 0:
            continue
        if not theirs or not same_channel(want, normalize(theirs)):
            continue
        return {'id': channel_id, 'served_name': theirs,
                'programmes': idx['counts'][channel_id], 'upstream': up['name']}
    return None
