(()=>{
'use strict';
const API='https://api.mapbox.com/search/searchbox/v1';
const results=document.querySelector('#poiResults');
const TYPE_HINTS={
 restaurant:['restaurant'],fast_food:['fast food','fast_food'],cafe:['coffee','cafe'],bar:['bar','pub'],ice_cream:['ice cream','ice_cream'],bakery:['bakery'],
 hotel:['hotel','lodging'],motel:['motel','lodging'],guest_house:['guest house','lodging'],camp_site:['campground','camping'],
 supermarket:['supermarket'],convenience:['convenience store','mini market'],mall:['shopping mall','shopping'],
 pharmacy:['pharmacy'],hospital:['hospital'],clinic:['clinic','health services'],dentist:['dentist'],
 fuel:['gas station','fuel'],parking:['parking'],charging:['charging station'],taxi:['taxi'],bus:['bus station','bus stop'],
 bank:['bank'],atm:['atm'],police:['police'],post:['post office'],gym:['fitness','gym'],beach:['beach'],museum:['museum'],attraction:['tourist attraction','attraction'],playground:['playground']
};
let categoryCache=null,seq=0;
const token=()=>String(window.__LUMINA_CONFIG__?.mapboxAccessToken||localStorage.getItem('lumina-mapbox-public-token')||'').trim();
const norm=s=>String(s||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase().replace(/[_-]+/g,' ').replace(/[^a-z0-9α-ω ]+/gi,' ').replace(/\s+/g,' ').trim();
const rad=v=>v*Math.PI/180;
const distance=(a,b)=>{const R=6371e3,p1=rad(a.lat),p2=rad(b.lat),dp=rad(b.lat-a.lat),dl=rad(b.lng-a.lng),x=Math.sin(dp/2)**2+Math.cos(p1)*Math.cos(p2)*Math.sin(dl/2)**2;return 2*R*Math.atan2(Math.sqrt(x),Math.sqrt(1-x))};
const esc=s=>String(s||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fd=m=>m<1000?`${Math.round(m)} m`:`${(m/1000).toFixed(1)} km`;
async function getJSON(url,timeout=9000){const c=new AbortController(),t=setTimeout(()=>c.abort(),timeout);try{const r=await fetch(url,{cache:'no-store',signal:c.signal,headers:{Accept:'application/json'}});if(!r.ok)throw new Error(`Mapbox HTTP ${r.status}`);return await r.json()}finally{clearTimeout(t)}}
async function gps(){const p=window.LuminaGPS?.getLastFix?.(60000)||window.LuminaGPS?.lastFix;if(Number.isFinite(+p?.lat)&&Number.isFinite(+p?.lng))return{lat:+p.lat,lng:+p.lng,accuracy:p.accuracy||null};if(window.LuminaGPS?.getPosition)return window.LuminaGPS.getPosition({maxAge:60000,timeout:7000});throw new Error('gps-unavailable')}
async function categories(key){if(categoryCache)return categoryCache;const u=new URL(`${API}/list/category`);u.searchParams.set('access_token',key);u.searchParams.set('language','en');const d=await getJSON(u);categoryCache=d.listItems||[];return categoryCache}
function chooseCategory(type,list){const hints=(TYPE_HINTS[type]||[type]).map(norm);let best=null,bestScore=-1;for(const c of list){const id=norm(c.canonical_id),name=norm(c.name);for(const h of hints){let score=-1;if(id===h)score=100;else if(name===h)score=95;else if(id.includes(h)||h.includes(id))score=80;else if(name.includes(h)||h.includes(name))score=70;if(score>bestScore){bestScore=score;best=c}}}return bestScore>=70?best:null}
function parse(data,o){return(data.features||[]).map(f=>{const p=f.properties||{},c=f.geometry?.coordinates||[],pt={lat:+c[1],lng:+c[0]};if(!Number.isFinite(pt.lat)||!Number.isFinite(pt.lng)||!p.name)return null;return{name:p.name,point:pt,distance:distance(o,pt),area:p.full_address||p.place_formatted||p.address||'Κοντινή περιοχή'}).filter(Boolean).sort((a,b)=>a.distance-b.distance)}
async function categorySearch(type,o,key){const list=await categories(key),cat=chooseCategory(type,list);if(!cat)return[];const u=new URL(`${API}/category/${encodeURIComponent(cat.canonical_id)}`);u.searchParams.set('access_token',key);u.searchParams.set('language','el');u.searchParams.set('limit','25');u.searchParams.set('proximity',`${o.lng},${o.lat}`);u.searchParams.set('country','GR');return parse(await getJSON(u),o)}
async function forwardSearch(type,o,key){const q=(TYPE_HINTS[type]||[type])[0];const u=new URL(`${API}/forward`);u.searchParams.set('q',q);u.searchParams.set('access_token',key);u.searchParams.set('language','el');u.searchParams.set('limit','10');u.searchParams.set('proximity',`${o.lng},${o.lat}`);u.searchParams.set('country','GR');u.searchParams.set('types','poi');return parse(await getJSON(u),o)}
function render(items,o){if(!results)return;if(!items.length){results.innerHTML='<div class="poi-loading">Το Mapbox απάντησε, αλλά δεν βρέθηκαν κοντινά σημεία αυτής της κατηγορίας.</div>';return}results.innerHTML=`<div class="poi-loading"><strong>${items.length} κοντινά σημεία</strong><br><small>Mapbox · ταξινόμηση από το κοντινότερο · GPS${o.accuracy?` ±${Math.round(o.accuracy)}m`:''}</small></div>`+items.slice(0,25).map((x,i)=>`<article class="poi-result"><div><strong>${i+1}. ${esc(x.name)}</strong><span>${fd(x.distance)} · ${esc(x.area)}</span></div><button type="button" class="poi-route" data-lat="${x.point.lat}" data-lng="${x.point.lng}" data-name="${esc(x.name)}">▶ Έναρξη</button></article>`).join('')}
async function run(type){const id=++seq,key=token();if(!key||!results)return false;results.innerHTML='<div class="poi-loading busy"><span class="poi-spinner"></span><strong>Mapbox: αναζητώ πραγματικά κοντινά σημεία…</strong></div>';try{const o=await gps();let items=[];try{items=await categorySearch(type,o,key)}catch(e){console.warn('[LUMINA Mapbox category]',e)}if(!items.length)items=await forwardSearch(type,o,key);if(id!==seq)return true;render(items,o);return true}catch(e){console.error('[LUMINA Mapbox POI]',e);if(id===seq)results.innerHTML='<div class="poi-loading error">Το Mapbox δεν μπόρεσε να ολοκληρώσει την αναζήτηση. Δεν εμφανίζω παλιά/εφεδρικά αποτελέσματα ως Mapbox.</div>';return true}}
document.addEventListener('click',e=>{const b=e.target.closest?.('[data-poi-type]');if(!b||!token())return;e.preventDefault();e.stopImmediatePropagation();run(b.dataset.poiType)},true);
})();
