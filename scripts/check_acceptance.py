import json,os,re,urllib.request
from pathlib import Path
v=os.environ['RELEASE_VERSION'];assert re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+',v)
p=Path('reports/acceptance')/(v+'.json');e=json.loads(p.read_text())
assert e.get('mobile_apk') and e.get('tv_apk') and e.get('playback') and e.get('cdn_verified'),'Unaccepted release'
url='https://cdn.jsdelivr.net/npm/wkc0001-tvbox-independent@'+v+'/manifest.json'
with urllib.request.urlopen(url,timeout=30) as r:m=json.load(r)
assert m['version']==v and m['files']==e['files'],'Acceptance is for different resource bytes'
print('Accepted release',v)
