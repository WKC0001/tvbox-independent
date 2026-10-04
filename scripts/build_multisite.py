"""Reproducible independent multi-site plugin and fixed-version release builder."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from checker.content import BLOCK,GENRES
from checker.television import playlist,epg_identity
from checker.health import effective

# 聚合里大量上游会在播放中插博彩广告，而播放线路的对外显示名不能改
# （客户端会用当前详情重新核对上游原始 flag），所以提示落在站点名和线路标签上。
NOTICE='⚠勿信广告'


def read(name):return json.loads((ROOT/name).read_text())
def dump(path,obj):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
def run(*args):subprocess.run([str(x) for x in args],cwd=ROOT,check=True)


def dependencies():
    defaults={'JAVA_HOME':'/private/tmp/apktools/jdk-17.0.20.1+1/Contents/Home',
              'D8_JAR':'/private/tmp/apktools/bt/android-14/lib/d8.jar',
              'SMALI_JAR':str(ROOT/'.build-tools/smali-tools.jar'),
              'JSON_JAR':str(ROOT.parents[1]/'enrichment/java/json.jar')}
    d={k:Path(os.environ.get(k,v)) for k,v in defaults.items()}
    for k,v in d.items():
        if not v.exists():raise SystemExit('Missing '+k+': '+str(v))
    expected={'SMALI_JAR':read('policy/build-tools.json')['assembled_sha256'],
              'JSON_JAR':'3cf6cd6892e32e2b4c1c39e0f52f5248a2f5b37646fdfbb79a66b46b618414ed',
              'D8_JAR':'d43c8a94c9b1f1da1a7cc49c32b81e8cee1708b37ee8b530a81a0688222b42c0'}
    for key,sha in expected.items():
        if hashlib.sha256(d[key].read_bytes()).hexdigest()!=sha:raise SystemExit('Pinned dependency checksum mismatch: '+key)
    return d


def plugin(target,sites,deps):
    java=deps['JAVA_HOME']/'bin/java';javac=deps['JAVA_HOME']/'bin/javac'
    # Always reproduce the bridge from the immutable original; never use an unchecked prebuilt repair.
    run(sys.executable,ROOT/'scripts/restore_native_crypto.py','--input',ROOT/'vendor/legacy-clean.jpg','--output',ROOT/'vendor/native-restored.jpg',
        '--java-home',deps['JAVA_HOME'],'--smali-jar',deps['SMALI_JAR'],'--d8-jar',deps['D8_JAR'])
    run(sys.executable,ROOT/'scripts/verify_native_crypto.py','--baseline',ROOT/'vendor/legacy-clean.jpg','--jar',ROOT/'vendor/native-restored.jpg',
        '--java-home',deps['JAVA_HOME'],'--smali-jar',deps['SMALI_JAR'])
    generated=ROOT/'java/generated';generated.mkdir(exist_ok=True)
    # The policy source is shared with Python admission; no separate stale Java regex.
    native=sorted({s['config']['api'].replace('csp_','') for s in sites if s['kind']=='native' and s['status']!='excluded'})
    q=lambda s:json.dumps(s,ensure_ascii=True)
    policy='''package com.github.catvod.spider;
import java.util.regex.Pattern;
final class WkcPolicy {
 static final String[] GENRES={%s};
 static final String[] NATIVE_CLASSES={%s};
 static final Pattern DENY=Pattern.compile(%s,Pattern.CASE_INSENSITIVE);
 static boolean blocked(String s){return DENY.matcher(java.text.Normalizer.normalize(s,java.text.Normalizer.Form.NFKC)).find();}
 static String genre(String s){s=java.text.Normalizer.normalize(s,java.text.Normalizer.Form.NFKC).trim();if(blocked(s))return null;
 %s return null;}
}
''' % (','.join(q(x) for x in GENRES),','.join(q(x) for x in native),q(BLOCK),
       '\n'.join('if(Pattern.compile('+q(v)+',Pattern.CASE_INSENSITIVE).matcher(s).matches())return '+q(k)+';' for k,v in GENRES.items()))
    (generated/'WkcPolicy.java').write_text(policy)
    with tempfile.TemporaryDirectory(prefix='wkc-plugin-') as tmp:
        temp=Path(tmp);classes=temp/'classes';classes.mkdir();dex=temp/'dex';dex.mkdir()
        stubs=temp/'stubs';stubs.mkdir()
        (stubs/'Init.java').write_text('package com.github.catvod.spider; public class Init { public static com.github.catvod.crawler.Spider getSpider(String name)throws Exception {return (com.github.catvod.crawler.Spider)Class.forName(name.replace("Guard","")).newInstance();} }')
        (stubs/'Base64.java').write_text('package android.util; public class Base64 { public static final int URL_SAFE=8,NO_WRAP=2,NO_PADDING=1; public static String encodeToString(byte[] b,int f){return java.util.Base64.getUrlEncoder().withoutPadding().encodeToString(b);} public static byte[] decode(String s,int f){return java.util.Base64.getUrlDecoder().decode(s);} }')
        sources=sorted((ROOT/'java/multisite').glob('*.java'))+list(generated.glob('*.java'))+list(stubs.glob('*.java'))+sorted((ROOT/'java/stubs').rglob('*.java'))+sorted((ROOT/'java/test-multisite').glob('*.java'))
        run(javac,'-encoding','UTF-8','-source','8','-target','8','-cp',deps['JSON_JAR'],'-d',classes,*sources)
        cp=str(classes)+os.pathsep+str(deps['JSON_JAR'])
        run(java,'-cp',cp,'com.github.catvod.spider.MultisiteTest')
        # Persist host-test classes for network integration, but exclude every host stub/test from DEX.
        host=ROOT/'java/test-classes'
        if host.exists():shutil.rmtree(host)
        shutil.copytree(classes,host)
        compiled=[p for p in (classes/'com/github/catvod/spider').glob('Wkc*.class')]
        run(java,'-cp',deps['D8_JAR'],'com.android.tools.r8.D8','--min-api','24','--output',dex,*compiled)
        smali=temp/'smali';new=temp/'new-smali'
        run(java,'-cp',deps['SMALI_JAR'],'com.android.tools.smali.baksmali.Main','d',ROOT/'vendor/native-restored.jpg','-o',smali)
        run(java,'-cp',deps['SMALI_JAR'],'com.android.tools.smali.baksmali.Main','d',dex/'classes.dex','-o',new)
        for p in new.rglob('*.smali'):
            dst=smali/p.relative_to(new);dst.parent.mkdir(exist_ok=True,parents=True);shutil.copyfile(p,dst)
        stable=temp/'stable';stable.mkdir()
        for p in smali.rglob('*.smali'):
            body=p.read_text();descriptor=next(l.split()[-1] for l in body.splitlines() if l.startswith('.class '))
            (stable/(hashlib.sha256(descriptor.encode()).hexdigest()+'.smali')).write_text(body)
        run(java,'-cp',deps['SMALI_JAR'],'com.android.tools.smali.smali.Main','a','-j','1',*sorted(stable.glob('*.smali')),'-o',temp/'classes.dex')
        with zipfile.ZipFile(ROOT/'vendor/native-restored.jpg') as original,zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as result:
            for name in sorted(original.namelist()):
                info=zipfile.ZipInfo(name,(2026,10,4,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED
                result.writestr(info,(temp/'classes.dex').read_bytes() if name=='classes.dex' else original.read(name))


def with_measurements(routes):
    """把实测下载速度比挂到线路上，供 playlist() 排序用。

    单独存 state/live-measured.json、而不是写回 registry/routes.json：
    注册表是可重建的（scripts/migrate_registry.py 会整体重写它），附加字段会在重跑时被冲掉，
    而实测数据是花了几十分钟真测出来的，不该跟着一起丢。
    """
    path=ROOT/'state/live-measured.json'
    if not path.exists():return routes
    data=json.loads(path.read_text()).get('routes',{})
    attached=0
    for r in routes:
        m=data.get(r['id'])
        if m:r['measured']=m;attached+=1
    print('MEASURED',attached,'of',len(routes),'routes carry a throughput measurement')
    return routes


def ad_verdict(site):
    """抽帧 OCR 的结论：clean=扫过且没发现博彩广告；flagged=扫到了；pending=没扫过。

    "没扫过"必须和"干净"区分开——没扫就说干净等于伪造结论，插件会把没扫过的源
    当成无广告排到前面去。所以缺省值是 pending，不是 clean。
    """
    verdict=(site.get('review') or {}).get('ad_scan')
    return verdict if verdict in ('clean','flagged') else 'pending'


def provider_settings(site,audit):
    # label 会进插件，成为播放线路的显示名（`WkcCms.display()`）。
    # 线路是用户唯一能看到"这条是谁"的位置，所以来源名和广告提示都必须在这里带上。
    # ad_scan 与 latency_ms 决定线路顺序：无广告优先，其次接口快的。
    return {'id':site['id'],'api':site['config']['api'],'media_hosts':audit['media_hosts'],
            'label':site['config']['name'],'ad_scan':ad_verdict(site),
            'latency_ms':int(audit.get('latency_ms',0)),
            'reviewed_at':audit['checked_at'],'policy':'normal-film-v1'}


def select(sites,audits,now,health=None,policy=None,native_audit=None):
    active=[];bench=[]
    health=health or {};policy=policy or {}
    max_age=policy.get('provider_evidence_max_age_days',7)*86400
    if native_audit is None:native_audit=read('state/native-audit.json') if (ROOT/'state/native-audit.json').exists() else {}
    for site in sites:
        if site['status']=='excluded':continue
        nets=health.get('site:'+site['id'],{})
        if site.get('review',{}).get('quarantined') or any(v.get('isolated') for v in nets.values()):
            bench.append({'id':site['id'],'name':site['config']['name'],'reason':'quarantined'});continue
        if policy.get('new_provider_requires_review',True) and not site.get('review',{}).get('admitted'):
            bench.append({'id':site['id'],'name':site['config']['name'],'reason':'initial admission review pending'});continue
        if site['kind']=='native':
            evidence=native_audit.get(site['id'],{})
            if evidence.get('accepted') and now-evidence.get('checked_at',0)<max_age:
                cfg={k:v for k,v in site['config'].items() if k not in ('categories','ext','api','type')}
                cfg.update(type=3,api='csp_WkcNative',ext={'id':site['id'],'adapter':site['config']['api'].replace('csp_',''),'original_ext':site['config'].get('ext','')},
                           searchable=1,quickSearch=1,changeable=1,timeout=30)
                active.append((site['order'],cfg))
            else:bench.append({'id':site['id'],'name':site['config']['name'],'reason':evidence.get('reason','native runtime/content acceptance pending')})
            continue
        evidence=audits.get(site['id'],{})
        # Each network retains independent evidence; a CI-only failure does not erase local success.
        passed=[]
        for network,v in evidence.items():
            success=v if v.get('accepted') else v.get('last_success',{})
            rec=nets.get(network,{})
            if (success.get('accepted') and 0<=now-success.get('checked_at',0)<max_age
                and effective(rec,now,max_age) in ('healthy','degraded')):
                passed.append(success)
        if not passed:bench.append({'id':site['id'],'name':site['config']['name'],'reason':'no fresh successful functional/content/media evidence'});continue
        audit=max(passed,key=lambda x:x['checked_at'])
        cfg={k:v for k,v in site['config'].items() if k not in ('categories','ext','api','type')}
        cfg.update(type=3,api='csp_WkcCms',ext=provider_settings(site,audit),searchable=1,quickSearch=1,changeable=1)
        active.append((site['order'],cfg))
    # Stable editorial baseline order; transient latency does not shuffle every release.
    return [v for _,v in sorted(active)],bench


def main():
    sites=read('registry/sites.json');audits=read('state/provider-audit.json');package=read('package.json');now=int(time.time())
    policy=read('policy/operations.json');health=read('state/multisite-health.json')
    active,bench=select(sites,audits,now,health,policy)
    cms_providers=[x for x in active if x['api']=='csp_WkcCms']
    if len(cms_providers)<policy['minimum_dynamic_providers']:raise SystemExit('Too few approved dynamic providers; preserve previous release')
    out=ROOT/'output';out.mkdir(exist_ok=True)
    deps=dependencies();plugin(out/'cfg.jpg',sites,deps)
    base='https://cdn.jsdelivr.net/npm/'+package['name']+'@'+package['version']+'/'
    home={'key':'点我切源','name':'WKC┃片单 '+NOTICE,'type':3,'api':'csp_WkcHome','searchable':1,'quickSearch':1,'changeable':1,
          'ext':{'providers':[x['ext'] for x in cms_providers]}}
    # The player substitutes {id} with each channel's tvg-id and {date} with the day being viewed.
    guide=policy.get('epg_template') or ''
    for token in ('{id}','{date}'):
        if token not in guide:raise SystemExit('EPG template must keep the '+token+' placeholder')
    epg={'now':now,'sources':policy.get('epg_sources') or [],'max_age_days':policy.get('epg_evidence_max_age_days',0)}
    config={'spider':base+'cfg.jpg;md5;'+hashlib.md5((out/'cfg.jpg').read_bytes()).hexdigest(),
            'hosts':[],'logo':'','rules':read('registry/baseline/api.json')['rules'],
            'sites':[home]+active,
            'lives':[{'name':'WKC电视直播','type':0,'url':base+'live.m3u','epg':guide,
                      'playerType':2,'timeout':15}]}
    channels=read('registry/channels.json')
    routes=with_measurements(read('registry/routes.json'))
    text,gaps=playlist(channels,routes,health,
                       network=policy['preferred_live_network'],max_routes=policy['max_live_routes'],epg=epg)
    (out/'live.m3u').write_text(text);dump(out/'api.json',config)
    dump(out/'dc.json',{'urls':[{'url':base+'api.json','name':'WKC 自有聚合'}]})
    dump(ROOT/'reports/live-gaps.json',gaps);dump(ROOT/'reports/bench-sites.json',bench)
    # A channel that plays but has no confirmed guide is a visible gap, never a silent one.
    covered={c['name'] for c in channels if epg_identity(c,now,epg['max_age_days'],set(epg['sources']))}
    epg_gaps=[{'channel_id':c['id'],'name':c['name'],'group':c['group'],'reason':'no source confirmed a guide id'}
              for c in channels if c.get('review')!='excluded' and c['name'] not in covered]
    dump(ROOT/'reports/epg-gaps.json',epg_gaps)
    # One channel can occupy several playlist lines, so count both: lines a player will resolve
    # and the distinct channels behind them. Collapsing these two numbers hides real coverage loss.
    guide_ids=re.findall(r'tvg-id="([^"]*)"',text)
    runtime={'files':{},'version':package['version'],'package':package['name'],'format':'multi-site-v1','site_count':len(config['sites']),
             'channel_count':len(channels),'known_live_gaps':len(gaps),'native_bridge_restored':True,
             'live_routes_total':len(routes),'live_routes_quarantined':sum(1 for r in routes if r.get('review')=='quarantined'),
             'epg_source':sorted(epg['sources']),'epg_max_age_days':epg['max_age_days'],
             'epg_channels_verified':len(covered),'epg_channels_shipped':len(set(guide_ids)),'epg_guide_entries':len(guide_ids),
             'epg_gaps':len(epg_gaps),
             'android_app_acceptance':False,'network_evidence':sorted({n for x in audits.values() for n in x})}
    for name in ('api.json','cfg.jpg','live.m3u','dc.json'):runtime['files'][name]=hashlib.sha256((out/name).read_bytes()).hexdigest()
    dump(out/'manifest.json',runtime)
    # Only this directory is packed by CI. Legacy fixed-catalogue files never enter a new release.
    stage=ROOT/'npmstage'
    if stage.exists():shutil.rmtree(stage)
    stage.mkdir()
    for name in (*runtime['files'],'manifest.json'):shutil.copyfile(out/name,stage/name)
    pkg={**package,'files':list(runtime['files'])+['manifest.json']};dump(stage/'package.json',pkg)
    dump(ROOT/'reports/build-dependencies.json',{k:hashlib.sha256(v.read_bytes()).hexdigest() for k,v in deps.items() if v.is_file()})
    print('BUILT',package['version'],len(config['sites']),'dynamic sites',len(gaps),'live route gaps;',
          runtime['epg_channels_shipped'],'of',runtime['epg_channels_verified'],'verified channels carry a guide',
          f"({runtime['epg_guide_entries']} playlist lines)")


if __name__=='__main__':main()
