"""Validate actual shipped DEX, source coverage, fixed-version closure and manifest."""
import hashlib,json,re,struct,sys,zlib
from pathlib import Path
from zipfile import ZipFile
ROOT=Path(__file__).resolve().parents[1]


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
    assert len(api['lives'])==1 and api['lives'][0]['url']==base+'live.m3u'
    playlist=(directory/'live.m3u').read_text()
    assert not re.search(r'https?://[^\s]+/(?:huya|douyu|yy)/',playlist,re.I),'Platform carousel reintroduced'
    assert '.fqzone.tv' not in playlist,'Unverified generated EPG ids reintroduced'
    assert '@latest' not in json.dumps(api),'Mixed-version dependencies'
    assert playlist.count('#EXTINF:')>200,'Unexpected television coverage collapse'
    result={'passed':True,'version':manifest['version'],'dex_classes':len(classes),'sites':len(keys),
            'playlist_routes':playlist.count('#EXTINF:'),'files':manifest['files'],'android_app_test':'separate acceptance required'}
    (ROOT/'reports/plugin-verification.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2));return result


if __name__=='__main__':verify(Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/'output')
