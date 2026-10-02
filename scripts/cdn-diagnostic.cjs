const fs=require('fs'),crypto=require('crypto');
async function main(){
 const urls=[
 'https://purge.jsdelivr.net/npm/wkc0001-tvbox-independent@latest/api.json',
 'https://data.jsdelivr.com/v1/package/npm/wkc0001-tvbox-independent',
 'https://cdn.jsdelivr.net/npm/wkc0001-tvbox@0.1.18/cfg.jpg',
 'https://cdn.jsdelivr.net/npm/wkc0001-tvbox-independent@0.2.1/home.jar',
 'https://cdn.jsdelivr.net/npm/wkc0001-tvbox-independent@latest/api.json?version=0.2.1'];
 const rows=await Promise.all(urls.map(async url=>{try{
 const r=await fetch(url,{signal:AbortSignal.timeout(15000)});const b=Buffer.from(await r.arrayBuffer());
 return {url,status:r.status,headers:Object.fromEntries(r.headers),bytes:b.length,sha256:crypto.createHash('sha256').update(b).digest('hex'),body:r.ok&&url.endsWith('cfg.jpg')?'binary omitted':b.toString('utf8').slice(0,1300)};
 }catch(e){return {url,error:e.message};}}));fs.writeFileSync('cdn-diagnostic.json',JSON.stringify(rows,null,2));console.log(JSON.stringify(rows));
}main();
