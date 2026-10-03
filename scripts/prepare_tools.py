"""Prepare an exact, independently reproducible smali CLI from pinned upstream jars."""
import concurrent.futures,hashlib,json,time,urllib.request,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def main():
    lock=json.loads((ROOT/'policy/build-tools.json').read_text());folder=ROOT/'.build-tools/deps';folder.mkdir(parents=True,exist_ok=True)
    def obtain(item):
        path=folder/item['name']
        if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest()==item['sha256']:return path
        for attempt in range(3):
            try:
                with urllib.request.urlopen(item['url'],timeout=40) as r:data=r.read()
                if hashlib.sha256(data).hexdigest()!=item['sha256']:raise ValueError('Dependency checksum mismatch: '+item['name'])
                path.write_bytes(data);return path
            except Exception:
                if attempt==2:raise
                time.sleep(2**attempt)
    with concurrent.futures.ThreadPoolExecutor(6) as pool:paths=list(pool.map(obtain,lock['dependencies']))
    members={}
    for path in paths:
        with zipfile.ZipFile(path) as z:
            for name in z.namelist():
                if name.endswith('/') or name.startswith('META-INF/') or name.endswith('module-info.class'):continue
                data=z.read(name)
                if name in members and members[name]!=data:raise ValueError('Conflicting CLI member: '+name)
                members[name]=data
    target=ROOT/'.build-tools/smali-tools.jar'
    with zipfile.ZipFile(target,'w',zipfile.ZIP_STORED) as z:
        for name,data in sorted(members.items()):z.writestr(zipfile.ZipInfo(name,(2026,10,4,0,0,0)),data)
    digest=hashlib.sha256(target.read_bytes()).hexdigest()
    if lock.get('assembled_sha256') and digest!=lock['assembled_sha256']:raise ValueError('Assembled CLI checksum mismatch')
    print('Prepared smali',lock['smali_version'],digest)

if __name__=='__main__':main()
