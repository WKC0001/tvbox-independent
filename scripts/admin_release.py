#!/usr/bin/env python3
"""CI-only release administration; isolated identities remain in the registry."""
import argparse,json,re,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
REPO='WKC0001/tvbox-independent'

def main():
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='action',required=True)
    for name in ('promote','rollback'):
        a=sub.add_parser(name);a.add_argument('version')
    sub.add_parser('candidate')
    a=sub.add_parser('quarantine');a.add_argument('kind',choices=['site','route']);a.add_argument('id');a.add_argument('--reason',required=True)
    args=p.parse_args()
    if args.action in ('promote','rollback'):
        if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+',args.version):p.error('Exact version required')
        cmd=['gh','workflow','run','release-tags.yml','--repo',REPO,'--ref','main','-f','action='+args.action,'-f','version='+args.version]
    elif args.action=='candidate':
        cmd=['gh','workflow','run','publish.yml','--repo',REPO,'--ref','main','-f','bump=true']
    else:
        from checker import health
        file=ROOT/('registry/sites.json' if args.kind=='site' else 'registry/routes.json')
        entries=json.loads(file.read_text());target=next((x for x in entries if x['id']==args.id),None)
        if target is None:p.error('Unknown registered id')
        if args.kind=='site':target.setdefault('review',{}).update(quarantined=True,reason=args.reason,checked_at=int(time.time()))
        else:target.update(review='quarantined',quarantine_reason=args.reason)
        file.write_text(json.dumps(entries,ensure_ascii=False,indent=2)+'\n')
        statefile=ROOT/'state/multisite-health.json';state=health.load_state(statefile)
        health.update(state,('site:' if args.kind=='site' else '')+args.id,'global',False,pollution=True,reason=args.reason)
        health.save_state(statefile,state)
        print('Isolated locally. Review and API-push registry/state changes, then run candidate. Existing fixed URLs are immutable; distribute the replacement URL.')
        return
    subprocess.run(cmd,check=True,cwd=ROOT)
    print('GitHub Actions dispatched; completion and CDN verification are still required.')

if __name__=='__main__':main()
