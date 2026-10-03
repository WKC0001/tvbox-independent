"""Allocate a monotonic patch version from the npm registry. CI release lock required."""
import json,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];p=ROOT/'package.json';pkg=json.loads(p.read_text())
assert pkg['name']=='wkc0001-tvbox-independent'
with urllib.request.urlopen('https://registry.npmjs.org/'+pkg['name'],timeout=30) as r:metadata=json.load(r)
major,minor,patch=map(int,pkg['version'].split('.'))
versions=[int(v.split('.')[2]) for v in metadata.get('versions',{}) if v.startswith(f'{major}.{minor}.') and v.split('.')[-1].isdigit()]
pkg['version']=f'{major}.{minor}.{max([patch,*versions])+1}'
p.write_text(json.dumps(pkg,ensure_ascii=False,indent=2)+'\n');print('NEW_CANDIDATE',pkg['version'])
