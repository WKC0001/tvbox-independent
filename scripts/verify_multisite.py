"""Validate actual shipped DEX, source coverage, fixed-version closure, guide ids and manifest."""
import hashlib,gzip,json,re,struct,sys,time,zlib
from pathlib import Path
from zipfile import ZipFile
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from checker.television import epg_identity


def dex_classes(data):
    def word(i):return struct.unpack_from('<I',data,i)[0]
    assert data.startswith(b'dex\n') and word(32)==len(data),'Invalid DEX size'
    assert data[12:32]==hashlib.sha1(data[32:]).digest(),'DEX signature mismatch'
    assert word(8)==zlib.adler32(data[12:])&0xffffffff,'DEX checksum mismatch'
    strings=[]
    for i in range(word(56)):
        cursor=word(word(60)+i*4)
        while data[cursor]&128:cursor+=1
        cursor+=1;end=data.index(0,cursor);strings.append(data[cursor:end].decode('utf8','replace'))
    types=[strings[word(word(68)+i*4)] for i in range(word(64))]
    classes={types[word(word(100)+i*32)] for i in range(word(96))}
    return classes,strings


def verify(directory=ROOT/'output'):
    directory=Path(directory);api=json.loads((directory/'api.json').read_text());manifest=json.loads((directory/'manifest.json').read_text())
    base='https://cdn.jsdelivr.net/npm/'+manifest['package']+'@'+manifest['version']+'/'
    assert manifest['package']=='wkc0001-tvbox-independent','Wrong package'
    assert api['spider'].split(';md5;')[0]==base+'cfg.jpg'
    assert api['spider'].split(';md5;')[-1]==hashlib.md5((directory/'cfg.jpg').read_bytes()).hexdigest()
    for name,digest in manifest['files'].items():assert hashlib.sha256((directory/name).read_bytes()).hexdigest()==digest,name
    with ZipFile(directory/'cfg.jpg') as z:
        assert z.testzip() is None;classes,strings=dex_classes(z.read('classes.dex'))
        with ZipFile(ROOT/'vendor/legacy-clean.jpg') as baseline:
            # 旧适配器继续保留：静态可达性裁剪实测只能剔掉 212 个（−10%），
            # 不值得为此砍掉历史适配器的兼容面，所以维持"一个都不能少"。
            originals,_=dex_classes(baseline.read('classes.dex'));assert originals<=classes,'Old adapter class removed'
            for name in baseline.namelist():
                if name!='classes.dex':assert baseline.read(name)==z.read(name),'Bundled resource changed: '+name
    required={'Lcom/github/catvod/spider/'+s+';' for s in ('HideUtils','CryptoBridge','WkcHome','WkcCms','WkcNative','WkcNet','WkcPolicy')}
    assert required<=classes,'Missing actual class definitions'
    assert not any(x.startswith(('Landroid/','Lcom/github/catvod/crawler/')) or 'MultisiteTest' in x for x in classes),'Compiler stubs or tests shipped'
    assert api['sites'][0]['key']=='点我切源' and api['sites'][0]['api']=='csp_WkcHome'
    keys=[s['key'] for s in api['sites']];assert len(keys)==len(set(keys))
    denied={s['key'] for s in json.loads((ROOT/'policy/migration-scope.json').read_text())['vod_default_exclusions']}
    assert not denied.intersection(keys),'Excluded site reintroduced'
    for site in api['sites']:
        assert all(site.get(k)==1 for k in ('searchable','quickSearch','changeable'))
        assert site['type']==3 and site['api'] in ('csp_WkcHome','csp_WkcCms','csp_WkcNative'),'Content-policy bypass'
        assert 'Lcom/github/catvod/spider/'+site['api'].replace('csp_','')+';' in classes
        # 线路的先后顺序由这两个字段决定。缺 ad_scan 会被插件当成 pending（没扫过），
        # 所以这里要卡的是取值合法：一旦能写出别的值，"没扫过"就可能被误当成"确认干净"。
        ranks=[]
        if site['api']=='csp_WkcHome':ranks=list((site.get('ext') or {}).get('providers') or [])
        elif site['api']=='csp_WkcCms':ranks=[site.get('ext') or {}]
        for provider in ranks:
            assert provider.get('ad_scan') in ('clean','pending','flagged'),'Unusable ad verdict: '+str(provider.get('ad_scan'))
            assert isinstance(provider.get('latency_ms'),int) and provider['latency_ms']>=0,'Unusable latency: '+str(provider.get('latency_ms'))
    assert len(api['lives'])==1 and api['lives'][0]['url']==base+'live.m3u'
    playlist=(directory/'live.m3u').read_text()
    assert not re.search(r'https?://[^\s]+/(?:huya|douyu|yy)/',playlist,re.I),'Platform carousel reintroduced'
    assert '.fqzone.tv' not in playlist,'Unverified generated EPG ids reintroduced'
    assert '@latest' not in json.dumps(api),'Mixed-version dependencies'
    assert playlist.count('#EXTINF:')>200,'Unexpected television coverage collapse'
    # A route that was proven to answer with someone else's channel must not be handed to a player
    # through any path, and the count of those routes has to be visible in the published metadata.
    routes=json.loads((ROOT/'registry/routes.json').read_text())
    withheld={r['url'] for r in routes if r.get('review')=='quarantined'}
    assert not withheld.intersection({line.split('|')[0] for line in playlist.splitlines() if '://' in line}),\
        'Quarantined live route reached the playlist'
    assert manifest['live_routes_total']==len(routes),'Manifest route total disagrees with the registry'
    assert manifest['live_routes_quarantined']==len(withheld),'Manifest quarantine count disagrees with the registry'
    # Re-check every shipped guide id the way the player will consume it: the id must be exactly
    # what the registry plus the source policy can prove right now, so a stale or invented id fails.
    policy=json.loads((ROOT/'policy/operations.json').read_text())
    guide=policy['epg_template'];age=policy['epg_evidence_max_age_days'];sources=set(policy['epg_sources'])
    xmltv=policy.get('epg_guide_mode')=='xmltv'
    assert api['lives'][0].get('epg')==(base+guide if xmltv else guide),'Live EPG target missing or changed'
    if not xmltv:
        for token in ('{id}','{date}'):assert token in guide,'EPG template lost the '+token+' placeholder'
    guide_channels=set()
    if xmltv:
        # 自有节目单必须真实存在、不带上游水印，并且覆盖播放列表里承诺的每一个 tvg-id。
        blob=gzip.decompress((directory/'guide.xml.gz').read_bytes()).decode('utf-8','replace')
        assert '免费使用' not in blob,'EPG watermark reintroduced'
        assert '<programme' in blob,'Shipped guide carries no programme'
        guide_channels=set(re.findall(r'<channel id="([^"]*)"',blob))
        assert manifest.get('epg_guide_channels')==len(guide_channels),'Manifest guide channel count disagrees with the shipped guide'
        assert set(re.findall(r'tvg-id="([^"]*)"',playlist))<=guide_channels,'Playlist promises a guide id the shipped XMLTV does not contain'
    assert 'tvg-id=""' not in playlist,'Empty guide id emitted'
    registry=json.loads((ROOT/'registry/channels.json').read_text())
    channels={c['name']:c for c in registry};now=int(time.time())
    def proven(channel):return epg_identity(channel,now,age,sources)
    shipped=set();entries=0
    for line in playlist.splitlines():
        if not line.startswith('#EXTINF:'):continue
        attrs=dict(re.findall(r'([\w-]+)="([^"]*)"',line))
        channel=channels.get(attrs.get('tvg-name',''))
        assert channel is not None,'Playlist entry has no registry channel: '+line
        expected=proven(channel)
        # XMLTV 模式下节目单里没有的 id 不发：登记了但播放器找不到，等于没有节目单。
        if xmltv and expected not in guide_channels:expected=''
        assert attrs.get('tvg-id','')==expected,'Shipped guide id disagrees with the verified registry: '+line
        if expected:shipped.add(expected);entries+=1
    verified={proven(c) for c in registry if proven(c)}
    assert manifest['epg_guide_entries']==entries,'Manifest guide entry count disagrees with the shipped playlist'
    assert manifest['epg_channels_shipped']==len(shipped & guide_channels if xmltv else shipped),'Manifest shipped guide count disagrees with the shipped playlist'
    assert manifest['epg_channels_verified']==len(verified),'Verified guide count disagrees with the registry'
    assert manifest['epg_gaps']==sum(1 for c in registry if c.get('review')!='excluded' and not proven(c)),'Guide gap count disagrees with the registry'
    assert shipped<=verified,'A shipped guide id is absent from the verified registry'
    result={'passed':True,'version':manifest['version'],'dex_classes':len(classes),'sites':len(keys),
            'playlist_routes':playlist.count('#EXTINF:'),'epg_channels_shipped':len(shipped),
            'epg_guide_entries':entries,'epg_channels_verified':manifest['epg_channels_verified'],
            'epg_gaps':manifest['epg_gaps'],'files':manifest['files'],'android_app_test':'separate acceptance required'}
    (ROOT/'reports/plugin-verification.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2));return result


if __name__=='__main__':verify(Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/'output')
