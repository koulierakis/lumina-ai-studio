import assert from 'node:assert/strict';

const H={'Accept':'application/json','User-Agent':'LUMINA-Drive-production-smoke/1.0'};
const norm=s=>String(s||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLocaleLowerCase('el-GR').replace(/[^a-z0-9α-ω]+/gi,' ').trim();
const stop=new Set(['ο','η','το','τα','της','του','των','σε','στη','στην','στο','και','greece','ελλαδα','ελλαδας']);
function features(q){const n=norm(q),tokens=n.split(' ').filter(t=>t.length>1&&!stop.has(t)),number=(n.match(/\b\d+[a-zα-ω]?\b/i)||[])[0]||null;return{n,tokens,number}}
function safe(place,q){const f=features(q),label=norm(`${place.display_name||''} ${place.name||''}`),matches=f.tokens.filter(t=>label.includes(t)),ratio=f.tokens.length?matches.length/f.tokens.length:0;return(!f.number||new RegExp(`\\b${f.number}\\b`,'i').test(label))&&ratio>=(f.tokens.length>=3?.66:.5)}
async function get(url,timeout=15000){const c=new AbortController(),t=setTimeout(()=>c.abort(),timeout);try{const r=await fetch(url,{headers:H,signal:c.signal});assert.equal(r.ok,true,`${url} -> ${r.status}`);return r.json()}finally{clearTimeout(t)}}

const regression='Εθνικής Αντιστάσεως 21 Τρίκαλα';
const n=new URL('https://nominatim.openstreetmap.org/search');
n.searchParams.set('format','jsonv2');n.searchParams.set('q',regression);n.searchParams.set('countrycodes','gr');n.searchParams.set('limit','10');n.searchParams.set('addressdetails','1');
const results=await get(n);
for(const r of results){const label=norm(r.display_name);if(label.includes('μουσειο αντιδικτατορικης')||label.includes('αθηνα'))assert.equal(safe(r,regression),false,`unsafe Athens result became routable: ${r.display_name}`)}

const k=new URL('https://nominatim.openstreetmap.org/search');
k.searchParams.set('format','jsonv2');k.searchParams.set('q','Κανάλι Πρέβεζας, Ελλάδα');k.searchParams.set('countrycodes','gr');k.searchParams.set('limit','5');
const kanali=await get(k);assert.ok(kanali.length,'Kanali geocoding returned no results');
const lat=Number(kanali[0].lat),lon=Number(kanali[0].lon);assert.ok(Number.isFinite(lat)&&Number.isFinite(lon),'Kanali coordinates invalid');
const q=`[out:json][timeout:20];(nwr(around:10000,${lat},${lon})[amenity=restaurant];nwr(around:10000,${lat},${lon})[amenity=cafe];nwr(around:10000,${lat},${lon})[tourism=hotel];nwr(around:10000,${lat},${lon})[tourism=apartment];nwr(around:10000,${lat},${lon})[amenity=pharmacy];nwr(around:10000,${lat},${lon})[amenity=fuel];);out center tags;`;
let poi=null,last=null;
for(const ep of ['https://overpass-api.de/api/interpreter','https://overpass.kumi.systems/api/interpreter']){try{poi=await get(`${ep}?data=${encodeURIComponent(q)}`,25000);break}catch(e){last=e}}
if(!poi)throw last||new Error('Overpass unavailable');
const named=(poi.elements||[]).filter(e=>e.tags?.name||e.tags?.brand||e.tags?.operator);
assert.ok(named.length>=5,`Kanali live POI smoke found only ${named.length} named places`);
console.log(`PASS address-regression=${results.length} kanali-poi=${named.length}`);
