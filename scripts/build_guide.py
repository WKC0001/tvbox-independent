"""构建自有 XMLTV 节目单：去水印、频道 id 对齐本仓库的 tvg-id。

为什么要自己生成一份
--------------------
51zmt 的 diyp JSON 接口在每个节目名后面都拼了「 --免费使用」（服务端行为，
参数关不掉，实测 `?ch=CCTV4` 逐字返回 `新闻联播 --免费使用`）。播放器拿到什么
就显示什么，客户端拦不住。

同一家的 XMLTV（cc.xml）**没有**这个水印，而且标题更详细。播放器（FM影视TV
5.6.8，反编译确认 `bq0` 类）支持 XMLTV（含 gzip），并且用 `tvg-id` 精确匹配
`<channel id>`。但它的 id 是 `1..101` 这种无意义序号，跟我们的 `CCTV4` 对不上。

所以：下载上游 XMLTV → 按显示名对回本仓库已核验的 `epg_id` → 重写 `<channel id>`
与 `channel=` → gzip 成 `guide.xml.gz`，`epg` 直接指向它。
只输出能对上的频道；对不上的如实进报告，不编一个 id 出来。

上游 XMLTV 只覆盖约 101 个频道（央视与省级卫视），所以这会比 diyp 少覆盖一批
地方/港澳台频道——这是为了去掉水印付出的真实代价，缺口在报告里可见。

后来又接了第二家上游（epg.pw，见 scripts/epg_sources.py）：654 个频道、覆盖
7 天、标题里没有水印。两家合起来比任何一家单独都全，而且其中一家整机失联时
另一家还能顶住——51zmt 就整台失联过，那时节目单只能退回缓存。

每家的时区由 policy 自己声明：epg.pw 把北京时间按 +0000 写进文件（新闻联播
字面在 19:00），照抄会让整份节目单偏 8 小时，所以入库前先归一到 +0800。
"""
import argparse
import gzip
import json
import re
import os
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
from verify_live_identity import normalize, same_channel  # noqa: E402
from checker.television import epg_identity  # noqa: E402
import epg_sources  # noqa: E402

# 上游 diyp JSON 里拼的是「 --免费使用」；XMLTV 目前没有，但这里仍然剥一次，
# 防止哪天上游把水印加进 XMLTV 而没人发现。
WATERMARK = re.compile(r'\s*-{1,2}\s*免费使用\s*$')
CHANNEL_BLOCK = re.compile(r'<channel id="([^"]*)"[^>]*>(.*?)</channel>', re.S)
DISPLAY = re.compile(r'<display-name[^>]*>([^<]*)</display-name>')
PROGRAMME = re.compile(r'<programme\s.*?channel="([^"]*)"')
TITLE = re.compile(r'<title[^>]*>(.*?)</title>', re.S)
ORIGIN = []


def diyp_day(gid, date, policy):
    """取一个频道的 diyp 节目单并剥水印。失败返回 []，绝不因为一个频道拖垮整份节目单。

    这里不能走 checker.network.cms()：它要求响应里有 `list`（CMS 内容接口的形状），
    而 diyp 节目单接口返回的是 `epg_data`，会被它当成坏响应拒掉。
    """
    from checker.network import fetch
    url = policy['epg_diyp_upstream'].replace('{id}', gid).replace('{date}', date)
    try:
        payload = json.loads(fetch(url, timeout=15)[0])
    except Exception:
        return []
    day = []
    for item in payload.get('epg_data') or []:
        start, stop = str(item.get('start', '')), str(item.get('end', ''))
        title = WATERMARK.sub('', str(item.get('title', ''))).strip()
        if len(start) == 5 and len(stop) == 5 and title:
            day.append((start.replace(':', '') + '00', stop.replace(':', '') + '00', title))
    return day


def xmltv_date(text):
    found = re.search(r'<programme\s+start="(\d{8})', text)
    return found.group(1) if found else time.strftime('%Y%m%d')


def proven_ids(channels, policy):
    """只有身份核验当场能证明的 id 才允许出现在节目单里；没有就空着，绝不现编。"""
    now = int(time.time())
    age = policy['epg_evidence_max_age_days']
    sources = set(policy['epg_sources'])
    return {c['id']: epg_identity(c, now, age, sources) for c in channels}


def pick_upstream(loaded, gid, name):
    """为这个频道挑一家上游：先精确索引，再逐条比较。

    同一个频道常常两家上游都有（CCTV-1 就是）。这里必须**只认一家**，否则同一频道的
    节目会被输出两遍，播放器里就变成每个节目出现两次。

    挑哪家不是按登记顺序，而是比谁给得更全：先看能覆盖几天，天数一样再看节目条数。
    51zmt 只给一到两天、epg.pw 给七天，按登记顺序挑的话，绝大多数频道会锁死在天数
    少的那家上，多天节目单就名存实亡。频道 id 用的是本仓库自己的 epg_id，换上游不会
    换 id，所以这样挑对用户是透明的。
    """
    want = [w for w in (normalize(gid), normalize(name)) if w]
    best = None
    for up, _text, idx in loaded:
        found = None
        for w in want:
            direct = idx.get('exact', {}).get(w)
            if direct is not None and idx['counts'].get(direct, 0) > 0:
                found = direct
                break
        if found is None:
            for cid, theirs in idx['names'].items():
                if idx['counts'].get(cid, 0) <= 0 or not theirs:
                    continue
                if any(same_channel(w, normalize(theirs)) for w in want):
                    found = cid
                    break
        if found is None:
            continue
        score = (len(idx['cadays'].get(found, ())), idx['counts'].get(found, 0))
        if best is None or score > best[0]:
            best = (score, up, found)
    return (best[1], best[2]) if best else None


def extract_day(text, up, cid, gid, allowed=None):
    """把上游文本里属于 cid 的节目抽出来，频道号换成本仓库的 gid。

    整份 XMLTV 里绝大多数频道只有一天（epg.pw 654 个频道里只有热门台给满七天），
    想再多要一天只能按「频道 + 日期」回查。这里就是回查结果的落地方：格式跟整份
    XMLTV 一样，所以复用同一套抽取规则，也走同一遍水印剥离。

    `allowed` 是这次只要哪几天。**不能省**：实测对多数频道请求 `date=20261005`，
    上游返回的仍然是 10-04 的节目（它根本没有第二天数据，date 参数只对少数频道
    有效）。不过滤的话，这些节目会被当成"补到的第二天"再写一遍，同一个节目在
    播放器里出现两次——那比没有第二天更糟。
    """
    out, keep = [], False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith('<programme'):
            found = PROGRAMME.match(stripped)
            day = re.search(r'start="(\d{8})', stripped)
            keep = bool(found and found.group(1) == cid
                        and (allowed is None or (day and day.group(1) in allowed)))
            if not keep:
                continue
            out.append('    ' + re.sub(r'channel="[^"]*"', 'channel="%s"' % escape(gid),
                                       stripped, count=1))
            continue
        if stripped.startswith('<title'):
            if keep:
                found = TITLE.search(stripped)
                title = WATERMARK.sub('', found.group(1)).strip() if found else ''
                out.append('      <title>%s</title>' % escape(title))
            continue
        if stripped == '</programme>':
            if keep:
                out.append('    </programme>')
                keep = False
            continue
    return out


def top_up(jobs, policy, log=sys.stderr):
    """对覆盖天数不足的频道，按天回查上游补齐。

    返回 (补到的节目行, 真正补到了东西的频道 id)。第二个返回值不是多余的：有的频道
    在整份 XMLTV 里一条节目都没捞到（CGTN、新疆卫视、翡翠台就是），它的全部节目
    都来自这里的回查，调用方据此补一份 `<channel>` 声明，免得 XMLTV 引用未定义的频道。

    这是几百次小请求，所以并发压得很低（3）并且有总量上限——上游是别人的免费
    服务，不能因为我们要多一天节目就把人家打挂。拿不到就少一天，不重试到底。
    """
    from concurrent.futures import ThreadPoolExecutor
    budget = int(policy.get('epg_day_topup_requests', 0) or 0)
    if not jobs or budget <= 0:
        return [], []
    added = []

    def ask(job):
        up, cid, gid, day8 = job
        url = up['day_api'].replace('{id}', str(cid)).replace('{date}', day8)
        try:
            text = epg_sources.retime(epg_sources.fetch(url, timeout=25).decode('utf-8', 'replace'), up)
        except Exception:
            return gid, day8, []
        if os.environ.get('GUIDE_DEBUG'):
            print('DEBUG %s -> %s' % (url, sorted(set(re.findall(r'start="(\d{8})', text)))),
                  file=sys.stderr)
        return gid, day8, extract_day(text, up, cid, gid, allowed={day8})

    asked, hits = jobs[:budget], []
    for gid, day8, lines in ThreadPoolExecutor(max_workers=3).map(ask, asked):
        if lines:
            added.extend(lines)
            hits.append(gid)
    if log:
        got = sum(1 for line in added if line.strip().startswith('<programme'))
        tally = {}
        for job in asked:
            tally[job[3]] = tally.get(job[3], 0) + 1
        print('     day top-up: %d requests %s, %d programmes back'
              % (len(asked), sorted(tally.items()), got), file=log)
        if len(jobs) > budget:
            print('     day top-up capped at %d of %d requests' % (budget, len(jobs)), file=log)
    return added, hits


def wanted_days(collected, count, today):
    """节目单要覆盖哪几天：上游给了几算几，不够就从今天往后补到 count 天。

    上游之间覆盖天数差很多（51zmt 只给一到两天，epg.pw 给七天），所以不能拿任何
    一家当天数标准，只能取并集再补。
    """
    days = sorted(set(collected)) or [today]
    stamp = datetime.strptime(days[0], '%Y%m%d')
    while len(days) < max(1, count):
        stamp += timedelta(days=1)
        value = stamp.strftime('%Y%m%d')
        if value not in days:
            days.append(value)
    return sorted(days)[:max(1, count)] if count else days


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--upstream', default=None, help='local copy of the upstream XMLTV')
    ap.add_argument('--out', default=str(ROOT / 'output/guide.xml.gz'))
    args = ap.parse_args()

    policy = json.loads((ROOT / 'policy/operations.json').read_text())
    channels = json.loads((ROOT / 'registry/channels.json').read_text())
    by_name = {c['name']: c for c in channels}
    proven = {c['id']: gid for c in channels for gid in [proven_ids([c], policy)[c['id']]] if gid}

    listed = epg_sources.upstreams(policy)
    loaded = []
    if args.upstream:
        # 本地文件：只认它一家，用于离线复现和回归测试。
        text = Path(args.upstream).read_text(encoding='utf-8')
        up = listed[0] if listed else epg_sources.normalize_upstream({'name': 'local', 'url': 'local'})
        loaded.append((up, text, epg_sources.index(text, normalize)))
        ORIGIN.append('local:%s' % args.upstream)
    else:
        for up in listed:
            try:
                text, origin = epg_sources.load(up, log=sys.stderr)
                loaded.append((up, text, epg_sources.index(text, normalize)))
                ORIGIN.append('%s:%s' % (up['name'], origin))
            except Exception as exc:
                # 一家拿不到不该让整份节目单塌陷：跳过它，让别的家继续。
                print('     upstream %s skipped: %s' % (up['name'], exc), file=sys.stderr)
                ORIGIN.append('%s:unavailable' % up['name'])
    if not loaded:
        raise RuntimeError('no XMLTV upstream could be read; refusing to emit an empty guide')

    # 为每个已核验频道挑一家上游：上游 id 是各自的内部序号（1..101 / 539631…），
    # 跟本仓库的 CCTV4 毫无关系，只能靠显示名对回来，且一家只能认一个频道一次。
    rename, origin, unmatched = {}, {}, []
    for name in sorted(by_name):
        channel = by_name[name]
        gid = proven.get(channel['id'])
        if not gid:
            continue
        hit = pick_upstream(loaded, gid, name)
        if hit:
            up, cid = hit
            rename[(up['name'], cid)] = gid
            origin[gid] = (up, cid)
        else:
            unmatched.append(name)

    # XMLTV 命中的直接重映射；没命中的（地方/港澳台/付费）回问 diyp 并剥水印。
    # 这样两家 XMLTV 加 diyp 三份数据都用上，谁都不用为去水印放弃频道覆盖。
    channel_lines, programme_lines = [], []
    emitted, programmes, days_seen = set(), 0, set()

    def declare(gid):
        """幂等地声明一个频道。

        除了在 `<channel>` 处调用，输出 programme 前也必须调一次：实测有频道（CGTN、
        新疆卫视、翡翠台）拿得到节目却在上游的 `<channel>` 块里对不上号，只认前者会让
        XMLTV 引用一个没声明过的频道号，播放器按未定义处理，等于白拿。
        """
        if gid in emitted:
            return
        channel_lines.append('  <channel id="%s">' % escape(gid))
        channel_lines.append('    <display-name lang="zh">%s</display-name>' % escape(gid))
        channel_lines.append('  </channel>')
        emitted.add(gid)

    for up, text, idx in loaded:
        days_seen.update(idx['days'])
        keep = False
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith('<channel '):
                found = re.match(r'<channel id="([^"]*)"', stripped)
                gid = rename.get((up['name'], found.group(1))) if found else None
                keep = gid is not None
                if keep:
                    declare(gid)
                continue
            if stripped.startswith('<programme'):
                found = PROGRAMME.match(stripped)
                gid = rename.get((up['name'], found.group(1))) if found else None
                keep = gid is not None
                if not keep:
                    continue
                declare(gid)
                # 时区在 epg_sources.load 里已经归一，这里只换频道 id。
                programme_lines.append('    ' + re.sub(r'channel="[^"]*"',
                                                       'channel="%s"' % escape(gid), stripped, count=1))
                programmes += 1
                continue
            if stripped.startswith('<title'):
                if keep:
                    # 不能按 '<title>' 的长度硬切：上游可能写成 <title lang="zh">，
                    # 那样切出来会带着属性残渣（实测 epg.pw 就是这个写法）。
                    found = TITLE.search(stripped)
                    title = WATERMARK.sub('', found.group(1)).strip() if found else ''
                    programme_lines.append('      <title>%s</title>' % escape(title))
                continue
            if stripped == '</programme>':
                if keep:
                    programme_lines.append('    </programme>')
                continue
            # tv 开闭标签、doctype、注释一律不透传：输出完全由这里生成，不受上游格式漂移影响。

    # 天数取各上游的并集再往后补：51zmt 只给一两天，epg.pw 整份也只有热门台给满七天，
    # 不能拿任何一家当标准。
    today = datetime.now(timezone(timedelta(hours=8))).strftime('%Y%m%d')
    wanted = wanted_days(days_seen, int(policy.get('epg_days', 1) or 1), today)

    # 补齐缺失的天：整份 XMLTV 里多数频道只有一天，按「频道 + 日期」回查才能拿到第二天。
    have = {}
    for line in programme_lines:
        if not line.strip().startswith('<programme'):
            continue
        cid = re.search(r'channel="([^"]*)"', line)
        day = re.search(r'start="(\d{8})', line)
        if cid and day:
            have.setdefault(cid.group(1), set()).add(day.group(1))
    jobs = []
    for gid, (up, cid) in sorted(origin.items()):
        if not up.get('day_api'):
            continue
        for day8 in wanted:
            if day8 not in have.get(gid, set()):
                jobs.append((up, cid, gid, day8))
    if jobs:
        extra, hits = top_up(jobs, policy)
        for gid in hits:
            declare(gid)
        programme_lines.extend(extra)
        programmes += sum(1 for line in extra if line.strip().startswith('<programme'))

    # diyp 兜底：只问 XMLTV 没覆盖的频道，按天取，失败就少一个频道的节目单，不报错。
    fallback = 0
    if unmatched:
        from concurrent.futures import ThreadPoolExecutor
        jobs = [(name, day) for name in unmatched for day in wanted]

        def day_for(job):
            name, day8 = job
            gid = proven[by_name[name]['id']]
            return gid, day8, diyp_day(gid, '%s-%s-%s' % (day8[:4], day8[4:6], day8[6:]), policy)

        with ThreadPoolExecutor(max_workers=3) as pool:
            for gid, day8, day in pool.map(day_for, jobs):
                if not day:
                    continue
                declare(gid)
                for start, stop, title in day:
                    programme_lines.append('    <programme start="%s%s +0800" stop="%s%s +0800" channel="%s">'
                                           % (day8, start, day8, stop, escape(gid)))
                    programme_lines.append('      <title>%s</title>' % escape(title))
                    programme_lines.append('    </programme>')
                    fallback += 1

    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<!DOCTYPE tv SYSTEM "xmltv.dtd">',
           '<tv generator-info-name="WKC guide" source-info-name="%s, watermark stripped">'
           % ', '.join(ORIGIN)]
    out += channel_lines + programme_lines + ['</tv>']
    payload = gzip.compress(('\n'.join(out) + '\n').encode('utf-8'), 9)
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    programmes += fallback

    report = {'checked_at': int(time.time()),
              'upstreams': [u['name'] for u, _t, _i in loaded],
              'source': ORIGIN,
              'upstream_channels': sum(len(i['names']) for _u, _t, i in loaded),
              'xmltv_channels': len(rename),
              'diyp_channels': len(emitted) - len(rename), 'verified_channels': len(proven),
              'programmes': programmes, 'bytes': len(payload),
              'days': wanted,
              'verified_without_guide': sorted({n for n in unmatched
                                                if proven[by_name[n]['id']] not in emitted})}
    (ROOT / 'reports/epg-guide.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print('GUIDE %d channels / %d programmes / %d bytes; %d of %d verified channels covered'
          % (len(emitted), programmes, len(payload), len(emitted), len(proven)))
    print('     xmltv %d + diyp fallback %d; still without a guide: %s'
          % (len(rename), len(emitted) - len(rename),
             ', '.join(report['verified_without_guide'][:12]) or '(none)'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
