const fs=require('fs'),crypto=require('crypto'),assert=require('assert');
const api=JSON.parse(fs.readFileSync('api.json'));
const manifest=JSON.parse(fs.readFileSync('manifest.json'));
const pack=JSON.parse(fs.readFileSync('package.json'));
for(const [file,hash] of Object.entries(manifest.files))assert.strictEqual(crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex'),hash,file);
assert.equal(pack.version,manifest.version);
assert.equal(api.sites[0].api,'csp_WkcHome');
assert.equal(api.sites[0].categories.length,6);
const keys=api.sites.map(s=>s.key);assert.equal(new Set(keys).size,keys.length);assert(keys.every(Boolean));
const own=`https://cdn.jsdelivr.net/npm/${pack.name}@${pack.version}/`;
assert.equal(api.spider.split(';')[0],own+'home.jar');assert.equal(api.lives[0].url,own+'live.m3u');
assert.equal(api.spider.split(';md5;')[1],crypto.createHash('md5').update(fs.readFileSync('home.jar')).digest('hex'));
assert(api.sites.slice(1).every(s=>s.type===1&&/^https?:/.test(s.api)));
const report=JSON.parse(fs.readFileSync('reports/enrichment-report.json'));
assert.equal(report.vod_sites,api.sites.length-1);
assert(report.vod_provider_families>=6);assert.equal(report.missing_cctv.length,0);
let channels=new Set(),routes=new Set();
const text=fs.readFileSync('live.m3u','utf8');let label='';
for(const line of text.split('\n')){
 if(line.startsWith('#EXTINF')){label=line.match(/group-title="([^"]+)"/)[1]+'|'+line.split(',').slice(1).join(',');channels.add(label);}
 if(/^https?:/.test(line)){assert(!routes.has(line),'duplicate live URL');routes.add(line);}
}
assert.equal(new Set(report.live_channel_list.map(x=>x.name)).size,report.live_channels,'duplicate channel names across groups');
assert.equal(channels.size,report.live_channels);assert.equal(routes.size,report.live_routes);
console.log('ARTIFACT_VALIDATION_PASSED',api.sites.length,'sites',channels.size,'channels',routes.size,'routes');
