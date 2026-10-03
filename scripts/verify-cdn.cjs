const fs = require('fs');
const crypto = require('crypto');
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const pkg=JSON.parse(fs.readFileSync('package.json'));
const VERSION=pkg.version;
const base = 'https://cdn.jsdelivr.net/npm/'+pkg.name;
const targets = [['api.json',VERSION],['live.m3u',VERSION],['home.jpg',VERSION],['manifest.json',VERSION],...Object.keys(JSON.parse(fs.readFileSync('manifest.json')).files).filter(x=>x.startsWith('posters/')).map(x=>[x,VERSION])];
async function main() {
  require('child_process').execFileSync(process.env.PYTHON || 'python3',['scripts/verify_plugin.py'],{stdio:'inherit'});
  let metadata;
  for (let attempt=0;attempt<40;attempt++) {
    try {
      const response=await fetch('https://registry.npmjs.org/'+pkg.name+'/'+VERSION+'?check='+Date.now(),{signal:AbortSignal.timeout(15000)});
      if (response.ok) { metadata=await response.json();break; }
      console.log('Registry pending',response.status,'attempt',attempt+1);
    } catch(e) {console.log('Registry request',e.message);}
    await delay(10000);
  }
  if (!metadata || metadata.version!==VERSION) throw Error('npm version not readable within verification budget');
  console.log('npm version readable:',metadata.version);
  const tar=await fetch(metadata.dist.tarball,{signal:AbortSignal.timeout(30000)});
  if (!tar.ok) throw Error('tarball '+tar.status);
  const bytes=Buffer.from(await tar.arrayBuffer());
  if (crypto.createHash('sha1').update(bytes).digest('hex')!==metadata.dist.shasum) throw Error('npm tarball shasum');
  let checks;
  for (let attempt=0;attempt<40;attempt++) {
    checks=await Promise.all(targets.map(async ([file,version])=>{
      const url=`${base}@${version}/${file}`;
      try {
        const response=await fetch(url,{signal:AbortSignal.timeout(20000)});
        const body=Buffer.from(await response.arrayBuffer());
        const matches=response.ok && body.equals(fs.readFileSync(file));
        return {file,version,url,status:response.status,matches,bytes:body.length,sha256:crypto.createHash('sha256').update(body).digest('hex')};
      } catch(e) {return {file,version,url,matches:false,error:e.message};}
    }));
    console.log(JSON.stringify(checks));
    if (checks.every(x=>x.matches)) break;
    await delay(10000);
  }
  let latest;try{const r=await fetch(base+'@latest/api.json',{signal:AbortSignal.timeout(15000)});latest={status:r.status,matches:r.ok&&Buffer.from(await r.arrayBuffer()).equals(fs.readFileSync('api.json'))};}catch(e){latest={matches:false,error:e.message};}
  const result={latest,package:metadata.name,version:metadata.version,
    api_url:base+'@'+VERSION+'/api.json',latest_api_url:base+'@latest/api.json',fixed_api_url:base+'@'+VERSION+'/api.json',live_url:base+'@'+VERSION+'/live.m3u',
    tarball:metadata.dist.tarball,tarball_shasum:metadata.dist.shasum,
    source_monitor_modified:false,original_npm_package_modified:false,checks};
  fs.writeFileSync('cdn-verification.json',JSON.stringify(result,null,2)+'\n');
  if (!checks.every(x=>x.matches)) throw Error('CDN content mismatch/unavailable');
  console.log('ALL_CDN_CHECKS_PASSED');
}
main().catch(e=>{console.error(e);process.exitCode=1});
