# -*- coding: utf-8 -*-
"""Stage-6 maintenance: light/full health checks with persistent state.

Modes:
  light  — probe released config closure (api.json/live.m3u/home.jpg) + a
           sample of live routes; records evidence into state/health.json
  full   — probe ALL approved live routes, update per-route health state via
           checker/health.py state machine (degraded -> down on 2 consecutive
           failures, recovery needs 2 successes >=10min apart), persist
           state/health.json and write reports/maintenance-<ts>.json

Exit code: 0 normally; 2 when the RELEASE CLOSURE is broken (light mode) —
route health findings are data, not failures.
"""
import concurrent.futures as cf,json,sys,time
from pathlib import Path
from urllib.parse import urljoin
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from checker import health
from catalog.ids import route_id
import urllib.request
UA={'User-Agent':'okhttp/3.15'}
STATE=ROOT/'state/health.json'

def hls_ok(url,timeout=10,seg=True):
    try:
        with urllib.request.urlopen(urllib.request.Request(url,headers=UA),timeout=timeout) as r:
            body=r.read(262144).decode('utf-8','ignore')
        if '#EXTM3U' not in body:return False
        if not seg:return True
        s=next((l.strip() for l in body.splitlines() if l.strip() and not l.startswith('#')),None)
        if not s:return False
        with urllib.request.urlopen(urllib.request.Request(urljoin(url,s),headers=UA),timeout=timeout) as r:
            return len(r.read(131072))>=4096
    except Exception:
        return False

def main():
    mode=sys.argv[1] if len(sys.argv)>1 else 'light'
    prev=health.load_state(STATE)
    state=json.loads(json.dumps(prev))
    pkg=json.loads((ROOT/'package.json').read_text())
    base=f"https://cdn.jsdelivr.net/npm/{pkg['name']}@{pkg['version']}/"
    findings={'mode':mode,'at':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
              'release':pkg['version'],'release_closure':{},'routes':{}}
    for f in ('api.json','live.m3u','home.jpg'):
        try:
            with urllib.request.urlopen(urllib.request.Request(base+f,headers=UA),timeout=15) as r:
                n=len(r.read(8_000_000));okc=r.getcode()==200 and n>500
        except Exception:
            okc=False
        findings['release_closure'][f]=okc
    live=json.loads((ROOT/'input/approved-live.json').read_text())
    targets=live if mode=='full' else live[::max(1,len(live)//8)][:8]
    def probe_route(e):
        return e,hls_ok(e['url'])
    with cf.ThreadPoolExecutor(10) as ex:
        for e,okc in ex.map(probe_route,targets):
            rid=route_id(e['url'])
            rec=health.update(state,rid,'default',okc,reason='' if okc else 'maintenance probe failed')
            findings['routes'][rid]={'channel':e['name'],'ok':okc,'state':health.effective(rec)}
    anomaly=health.batch_anomaly(state,prev)
    findings['batch_anomaly']=anomaly
    health.save_state(STATE,state)
    down=[v for v in findings['routes'].values() if v['state']=='down']
    findings['summary']={'probed':len(findings['routes']),'down':len(down),
                         'closure_ok':all(findings['release_closure'].values()),
                         'batch_anomaly_flag':anomaly['flag']}
    if not (ROOT/'reports').exists():(ROOT/'reports').mkdir()
    (ROOT/'reports'/f"maintenance-{time.strftime('%Y%m%d-%H%M%S')}.json").write_text(
        json.dumps(findings,ensure_ascii=False,indent=1)+'\n')
    print(json.dumps(findings['summary'],ensure_ascii=False))
    if mode=='light' and not findings['summary']['closure_ok']:
        sys.exit(2)
    if mode=='full' and anomaly['flag']:
        print('[maintenance] 批量异常：健康线路骤降>30%，停止自动发布与删除（人工介入）')
        sys.exit(3)
if __name__=='__main__':main()
