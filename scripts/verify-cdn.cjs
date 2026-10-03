'use strict';
const fs=require('fs'),crypto=require('crypto'),zlib=require('zlib');
const path=require('path');const root=path.resolve(__dirname,'..');
const pkg=JSON.parse(fs.readFileSync(path.join(root,'package.json')));
const local=path.join(root,'output');const report={package:pkg.name,version:pkg.version,checks:[]};
const sha=b=>crypto.createHash('sha256').update(b).digest('hex');
async function get(url){
 const tries=20,limit=180000,started=Date.now();let last;
 for(let i=0;i<tries;i++){
  try{const r=await fetch(url,{signal:AbortSignal.timeout(30000)});if(!r.ok)throw Error('HTTP '+r.status);return Buffer.from(await r.arrayBuffer());}
  catch(e){
   last=e;
   if(Date.now()-started>limit)break;
   const wait=Math.min(3000*Math.pow(1.3,i),15000);
   console.log(`retry ${i+1}/${tries} in ${Math.round(wait/1000)}s: ${url} (${e.message})`);
   await new Promise(r=>setTimeout(r,wait));
  }
 }
 throw Error('Unreachable after retries: '+url+' ('+(last&&last.message)+')');
}
function tarFiles(buffer){const out={};for(let i=0;i+512<=buffer.length;){const h=buffer.subarray(i,i+512);if(h.every(b=>b===0))break;const name=h.subarray(0,100).toString().split('\0')[0],size=parseInt(h.subarray(124,136).toString().replace(/\0/g,'').trim()||'0',8);if(!Number.isFinite(size))throw Error('Bad tar size');out[name]=buffer.subarray(i+512,i+512+size);i+=512+Math.ceil(size/512)*512;}return out;}
(async()=>{try{
 if(pkg.name!=='wkc0001-tvbox-independent')throw Error('Wrong package');
 const meta=JSON.parse(await get('https://registry.npmjs.org/'+pkg.name+'/'+pkg.version));
 const files=tarFiles(zlib.gunzipSync(await get(meta.dist.tarball)));
 const manifest=JSON.parse(fs.readFileSync(path.join(local,'manifest.json')));
 for(const file of [...Object.keys(manifest.files),'manifest.json']){
  const expected=fs.readFileSync(path.join(local,file));const packed=files['package/'+file];
  if(!packed||!packed.equals(expected))throw Error('Registry bytes mismatch: '+file);
  const url='https://cdn.jsdelivr.net/npm/'+pkg.name+'@'+pkg.version+'/'+file;
  const actual=await get(url);if(!actual.equals(expected))throw Error('CDN bytes mismatch: '+file);
  report.checks.push({file,registry:true,cdn:true,sha256:sha(actual)});console.log('PASS',file);
 }
 report.passed=true;console.log('FIXED_VERSION_REGISTRY_CDN_VERIFIED');
}catch(e){report.passed=false;report.error=String(e);console.error(e);process.exitCode=1;}
finally{fs.writeFileSync(path.join(root,'cdn-verification.json'),JSON.stringify(report,null,2)+'\n');}})();
