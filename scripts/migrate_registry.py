"""One-time import from the frozen local baseline. No remote configuration reads."""
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from checker.television import parse_m3u, import_registry


def write(path, data):
    (ROOT/path).parent.mkdir(parents=True,exist_ok=True)
    (ROOT/path).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')


def main():
    if (ROOT/'registry/sites.json').exists():raise SystemExit('Registry already imported; refuse to overwrite maintenance edits')
    baseline=json.loads((ROOT/'registry/baseline/api.json').read_text())
    scope=json.loads((ROOT/'policy/migration-scope.json').read_text())
    excluded={s['key']:s['reason'] for s in scope['vod_default_exclusions']}
    sites=[]
    for i,s in enumerate(baseline['sites']):
        sites.append({'id':s['key'],'order':i,'kind':'cms' if s['type']==1 else 'native',
          'status':'excluded' if s['key'] in excluded else 'candidate',
          'reason':excluded.get(s['key'],'awaiting functional and content checks'), 'config':s})
    write('registry/sites.json',sites)
    records=parse_m3u((ROOT/'registry/baseline/live.m3u').read_text(),'source-monitor@0.1.26')
    write('reports/live-migration-raw.json',records)
    channels,routes,ledger=import_registry(records)
    write('registry/channels.json',channels);write('registry/routes.json',routes)
    write('reports/live-migration.json',ledger)
    write('reports/site-migration.json',[{'id':s['id'],'action':s['status'],'reason':s['reason']} for s in sites])
    print(f'Imported {len(sites)} sites, {len(records)} old records -> {len(channels)} channel identities / {len(routes)} routes')


if __name__=='__main__':main()
