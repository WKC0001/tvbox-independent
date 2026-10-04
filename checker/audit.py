"""Probe owned registries; discovery is never an input to ordinary builds."""
import argparse
import concurrent.futures as cf
import json
import time
from pathlib import Path
from urllib.parse import urlsplit
from checker import health
from checker.content import allowed_types, safe_item, episodes, norm
from checker.network import cms, media

ROOT=Path(__file__).resolve().parents[1]


def write(path, data):
    p=ROOT/path;p.parent.mkdir(exist_ok=True,parents=True)
    staging=p.with_suffix('.tmp');staging.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n');staging.replace(p)


def cms_audit(site):
    out={'id':site['id'],'checked_at':int(time.time()),'accepted':False,'name':site['config']['name']}
    try:
        url=site['config']['api'];classes,ms=cms(url,ac='list',pg=1)
        types=allowed_types(classes.get('class',[]))
        if not types:raise ValueError('No approved current category ids')
        latest,_=cms(url,ac='detail',pg=1)
        items=list(latest['list'])
        for kind in ('电影','电视剧','动漫'):
            tid=next((k for k,v in types.items() if v['genre']==kind),None)
            if tid:
                listing,_=cms(url,ac='detail',t=tid,pg=1)
                if not listing['list']:
                    # Many MacCMS providers do not expand parent categories.
                    tid=next((k for k,v in types.items() if v['genre']==kind and k!=tid),None)
                    if tid:listing,_=cms(url,ac='detail',t=tid,pg=1)
                items.extend(listing['list'])
        safe=[v for v in items if safe_item(v,types)]
        if not safe:raise ValueError('No metadata-approved dynamic items')
        title=safe[0]['vod_name'];search,_=cms(url,ac='detail',wd=title,pg=1)
        if not any(norm(v.get('vod_name',''))==norm(title) and safe_item(v,types) for v in search['list']):
            raise ValueError('Exact normalized title search failed')
        negative,_=cms(url,ac='detail',wd='WKC_NO_MATCH_71c822da5eff',pg=1)
        if negative['list']:raise ValueError('Search ignored nonmatching keyword')
        details,_=cms(url,ac='detail',ids=','.join(str(v['vod_id']) for v in safe[:3]))
        verified=[v for v in details['list'] if safe_item(v,types)]
        if not verified:raise ValueError('Detail category/content checks failed')
        direct=[]
        for item in safe+verified:
            for flag,ep,link in episodes(item):
                p=urlsplit(link)
                if p.path.lower().endswith(('.m3u8','.mp4')) or 'm3u8' in flag.lower():
                    direct.append((flag,link))
        if not direct:raise ValueError('No direct media route')
        checks=[]
        for flag,link in list(dict.fromkeys(direct))[:5]:
            result=media(link);checks.append({'url':link,**result})
            if result['ok']:break
        if not any(x['ok'] for x in checks):raise ValueError('Media sample failed: '+str(checks[-1].get('reason')))
        out.update(accepted=True,api=url,latency_ms=ms,types=types,
                   media_hosts=sorted({urlsplit(u).hostname for _,u in direct}),
                   blocked_categories=[c for c in classes.get('class',[]) if str(c.get('type_id')) not in types],
                   safe_sample_count=len(safe),blocked_item_count=len(items)-len(safe),sample_title=title,
                   media_checks=checks,verification='metadata + exact search + details + HLS media bytes; not exhaustive visual review')
    except Exception as error:out['reason']=str(error)[:250]
    print('CMS',out['name'],out['accepted'],out.get('reason',''),flush=True)
    return out


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--network',required=True);ap.add_argument('--mode',choices=['cms','live','full','light'],default='full');ap.add_argument('--workers',type=int,default=12)
    args=ap.parse_args();state_path=ROOT/'state/multisite-health.json'
    state=health.load_state(state_path);before=json.loads(json.dumps(state));now=int(time.time())
    report={'network':args.network,'checked_at':now,'sites':[],'routes':[]}
    if args.mode in ('cms','full'):
        sites=json.loads((ROOT/'registry/sites.json').read_text())
        candidates=[s for s in sites if s['kind']=='cms' and s['status']!='excluded']
        # 采集站对突发并发很敏感：实测 8 线程跑 27 个源时有多个返回限流错误页，
        # 而单个重试立刻正常。这里压到 4，宁可慢一点也不要把抖动写成 down。
        with cf.ThreadPoolExecutor(min(args.workers,4)) as ex:report['sites']=list(ex.map(cms_audit,candidates))
        previous=ROOT/'state/provider-audit.json';providers=json.loads(previous.read_text()) if previous.exists() else {}
        for item in report['sites']:
            health.update(state,'site:'+item['id'],args.network,item['accepted'],ts=now,reason=item.get('reason',''))
            old=providers.setdefault(item['id'],{}).get(args.network,{})
            if item['accepted']:item['last_success']={k:v for k,v in item.items() if k!='last_success'}
            elif old.get('last_success'):item['last_success']=old['last_success']
            elif old.get('accepted'):item['last_success']=old
            providers[item['id']][args.network]=item
        write('state/provider-audit.json',providers)
    if args.mode in ('live','full','light'):
        routes=json.loads((ROOT/'registry/routes.json').read_text())
        routes=[r for r in routes if r.get('review')!='quarantined']
        if args.mode=='light':
            # Rotate a deterministic sample so every registered route gets checked over time.
            slot=(now//7200)%12;routes=[r for i,r in enumerate(routes) if i%12==slot]
        def probe(r):return {'id':r['id'],**media(r['url'],r.get('headers',{}))}
        with cf.ThreadPoolExecutor(args.workers) as ex:
            for i,result in enumerate(ex.map(probe,routes),1):
                report['routes'].append(result)
                rec=health.update(state,result['id'],args.network,result['ok'],ts=now,reason=result.get('reason',''))
                if result['ok']:rec['latency_ms']=result['ms']
                if i%50==0:print('LIVE',i,len(routes),'passed',sum(x['ok'] for x in report['routes']),flush=True)
    report['anomaly']=health.batch_anomaly(state,before)
    health.save_state(state_path,state);write('reports/audit-'+args.network+'.json',report)
    print(json.dumps({'sites_passed':sum(x['accepted'] for x in report['sites']),'live_passed':sum(x['ok'] for x in report['routes']),'anomaly':report['anomaly']}))
    if report['anomaly']['flag']:raise SystemExit('BATCH_ANOMALY: preserve previous published release')


if __name__=='__main__':main()
