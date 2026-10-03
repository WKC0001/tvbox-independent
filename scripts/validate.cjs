const fs=require('fs'),crypto=require('crypto'),assert=require('assert');
const api=JSON.parse(fs.readFileSync('api.json')),pkg=JSON.parse(fs.readFileSync('package.json')),manifest=JSON.parse(fs.readFileSync('manifest.json'));
assert(api.sites.length===1 && api.sites[0].type===3 && api.sites[0].api==='csp_WkcHome');assert(api.parses.length===0);
const data=api.sites[0].ext.catalog_json,rows=JSON.parse(data);assert(rows.length>0);
const sha=crypto.createHash('sha256').update(data).digest('hex');assert(sha===manifest.catalog_sha256);assert(fs.readFileSync('java/src/com/github/catvod/spider/ApprovedCatalogue.java','utf8').includes(sha));
const ids=new Set(),names=new Set();for(const r of rows){assert(r.approved===true);assert(!ids.has(r.vod_id));assert(!names.has(r.vod_name));ids.add(r.vod_id);names.add(r.vod_name);assert(r.vod_pic.startsWith(`https://cdn.jsdelivr.net/npm/${pkg.name}@${pkg.version}/posters/`));assert(!/伦理|理论片|福利|成人|色情/.test(r.category+r.vod_name));}
for(const [f,hash]of Object.entries(manifest.files))assert(crypto.createHash('sha256').update(fs.readFileSync(f)).digest('hex')===hash,'File hash: '+f);
assert(api.spider.split(';md5;')[1]===crypto.createHash('md5').update(fs.readFileSync('home.jpg')).digest('hex'));console.log('CONTENT_SNAPSHOT_VALIDATED',rows.length);
// Verify the deployed Android DEX too. Source-level JVM tests cannot detect a stale home.jpg.
require('child_process').execFileSync(process.env.PYTHON || 'python3',['scripts/verify_plugin.py'],{stdio:'inherit'});
// 阶段2 硬校验：禁止 @latest；work_id 存在且唯一；封禁注册表域名不得出现在任何下发地址
assert(!/@latest/.test(JSON.stringify(api)),'api.json 含 @latest 引用');
const wids=new Set();for(const r of rows){assert(r.work_id&&/^wkc_w_[0-9a-f]{12}$/.test(r.work_id),'缺 work_id: '+r.vod_name);assert(!wids.has(r.work_id),'重复 work_id: '+r.vod_name);wids.add(r.work_id);}
const blocked=JSON.parse(fs.readFileSync('policy/blocked-sources.json','utf8'));
const bDom=blocked.blocked_providers.flatMap(e=>e.domains.map(d=>d.toLowerCase()));
const uDom=blocked.unverified_providers.flatMap(e=>e.domains.map(d=>d.toLowerCase()));
function hostOf(u){try{return new URL(u).hostname.toLowerCase()}catch(e){return ''}}
for(const r of rows){for(const source of r.vod_play_url.split('$$$'))for(const ep of source.split('#')){const h=hostOf(ep.slice(ep.indexOf('$')+1));assert(h,'非法播放地址');for(const d of bDom)assert(!(h===d||h.endsWith('.'+d)),'批准目录命中封禁域名: '+h);}}
const liveRoutes=fs.readFileSync('live.m3u','utf8').split(/\r?\n/).filter(l=>/^https?:/.test(l));
for(const u of liveRoutes){const h=hostOf(u);for(const d of bDom)assert(!(h===d||h.endsWith('.'+d)),'直播命中封禁域名: '+h);for(const d of uDom)assert(!(h===d||h.endsWith('.'+d)),'直播命中未验证注册表域名: '+h);}

const approvedLive=JSON.parse(fs.readFileSync('input/approved-live.json'));
const allowedLive=new Set(approvedLive.filter(r=>r.frame_review_pass&&r.fresh_probe.ok).map(r=>r.url));
const routes=fs.readFileSync('live.m3u','utf8').split(/\r?\n/).filter(l=>/^https?:/.test(l));assert(routes.length===manifest.live_routes);assert(new Set(routes).size===routes.length);for(const u of routes)assert(allowedLive.has(u),'Unreviewed live route');console.log('LIVE_CONTENT_VALIDATED',manifest.live_channels,routes.length);
