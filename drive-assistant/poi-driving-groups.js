(()=>{
'use strict';
const API='https://api.mapbox.com/search/searchbox/v1/forward';
const RADIUS=10000;
const GROUPS={
  food:{label:'🍽️ Εστίαση',subtitle:'Φαγητό · καφέ · γλυκό · ποτό',queries:['restaurant','taverna','pizza','italian restaurant','fast food','souvlaki','cafe','coffee','ice cream','bakery','bar','grill']},
  car:{label:'⛽ Αυτοκίνητο',subtitle:'Καύσιμα · συνεργεία · ελαστικά',queries:['gas station','car repair','tire shop','auto parts','car wash','EV charging station']},
  health:{label:'🏥 Πρώτες Βοήθειες',subtitle:'Φαρμακεία · νοσοκομεία · κέντρα υγείας',queries:['pharmacy','hospital','health center','medical clinic','emergency room']},
  shopping:{label:'🛍️ Αγορές',subtitle:'Supermarket · εμπορικά · καταστήματα',queries:['supermarket','mini market','shopping mall','clothing store','shoe store','electronics store','department store','home goods store','hardware store']}
};
const $=s=>document.querySelector(s);
const drawer=$('#poiDrawer'),cats=$('#poiCategories'),results=$('#poiResults'),title=$('#poiTitle'),back=$('#poiBackBtn');
const token=()=>String(window.__LUMINA_CONFIG__?.mapboxAccessToken||localStorage.getItem('lumina-mapbox-public-token')||'').trim();
const esc=s=>String(s||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const norm=s=>String(s||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLocaleLowerCase('el-GR').replace(/[^a-z0-9α-ω]+/gi,' ').trim();
const rad=v=>v*Math.PI/180;
const distance=(a,b)=>{const R=6371e3,p1=rad(a.lat),p2=rad(b.lat),dp=rad(b.lat-a.lat),dl=rad(b.lng-a.lng),x=Math.sin(dp/2)**2+Math.cos(p1)*Math.cos(p2)*Math.sin(dl/2)**2;return 2*R*Math.atan2(Math.sqrt(x),Math.sqrt(1-x))};
const fd=m=>m<1000?`${Math.round(m)} m`:`${(m/1000).toFixed(1)} km`;
async function gps(){const p=window.LuminaGPS?.getLastFix?.(60000)||window.LuminaGPS?.lastFix;if(Number.isFinite(+p?.lat)&&Number.isFinite(+p?.lng))return{lat:+p.lat,lng:+p.lng,accuracy:p.accuracy||null};if(window.LuminaGPS?.getPosition)return window.LuminaGPS.getPosition({maxAge:60000,timeout:7000});throw new Error('gps-unavailable')}
async function fetchQuery(q,o,key){const u=new URL(API);u.searchParams.set('q',q);u.searchParams.set('access_token',key);u.searchParams.set('language','el');u.searchParams.set('limit','10');u.searchParams.set('proximity',`${o.lng},${o.lat}`);u.searchParams.set('country','GR');u.searchParams.set('types','poi');const c=new AbortController(),t=setTimeout(()=>c.abort(),9000);try{const r=await fetch(u,{cache:'no-store',signal:c.signal,headers:{Accept:'application/json'}});const text=await r.text();let d={};try{d=text?JSON.parse(text):{}}catch{}if(!r.ok){const e=new Error(`HTTP ${r.status}`);e.status=r.status;throw e}return(d.features||[]).map(f=>{const p=f.properties||{},co=f.geometry?.coordinates||[],pt={lat:+co[1],lng:+co[0]};if(!Number.isFinite(pt.lat)||!Number.isFinite(pt.lng)||!p.name)return null;const dist=distance(o,pt);if(dist>RADIUS)return null;return{name:p.name,point:pt,distance:dist,area:p.full_address||p.place_formatted||p.address||'Κοντινή περιοχή'}}).filter(Boolean)}finally{clearTimeout(t)}}
function merge(groups){const out=[];for(const x of groups.flat().filter(Boolean).sort((a,b)=>a.distance-b.distance)){const n=norm(x.name);if(out.some(y=>distance(x.point,y.point)<55||(distance(x.point,y.point)<180&&n&&norm(y.name)===n)))continue;out.push(x)}return out.slice(0,40)}
function renderRoot(){if(!cats||!results)return;title.textContent='Σημεία ενδιαφέροντος';back?.classList.add('hidden');results.innerHTML='';cats.innerHTML=Object.entries(GROUPS).map(([k,g])=>`<button type="button" class="poi-category" data-drive-poi-group="${k}"><strong>${g.label}</strong><span>${g.subtitle}</span></button>`).join('')}
function render(items,o,label){if(!results)return;if(!items.length){results.innerHTML=`<div class="poi-loading">Δεν βρέθηκαν κοντινά σημεία για ${esc(label)}.</div>`;return}results.innerHTML=`<div class="poi-loading"><strong>${items.length} κοντινά σημεία</strong><br><small>Mapbox · ${esc(label)} · από το κοντινότερο · GPS${o.accuracy?` ±${Math.round(o.accuracy)}m`:''}</small></div>`+items.map((x,i)=>`<article class="poi-result"><div><strong>${i+1}. ${esc(x.name)}</strong><span>${fd(x.distance)} · ${esc(x.area)}</span></div><button type="button" class="poi-route" data-lat="${x.point.lat}" data-lng="${x.point.lng}" data-name="${esc(x.name)}">▶ Έναρξη</button></article>`).join('')}
async function run(groupKey){const g=GROUPS[groupKey],key=token();if(!g||!results)return;if(!key){results.innerHTML='<div class="poi-loading error">Το Mapbox δεν είναι διαθέσιμο.</div>';return}title.textContent=g.label.replace(/^\S+\s/,'');back?.classList.remove('hidden');cats.innerHTML='';results.innerHTML='<div class="poi-loading busy"><span class="poi-spinner"></span><strong>Mapbox: βρίσκω τα κοντινότερα σημεία…</strong></div>';try{const o=await gps();const groups=await Promise.all(g.queries.map(q=>fetchQuery(q,o,key).catch(()=>[])));render(merge(groups),o,g.label)}catch(e){results.innerHTML=`<div class="poi-loading error"><strong>Mapbox: ${esc(e?.message||'σφάλμα')}</strong></div>`}}
document.addEventListener('click',e=>{const open=e.target.closest?.('#poiOpenBtn,#navPoiBtn');if(open){setTimeout(renderRoot,0);return}const b=e.target.closest?.('[data-drive-poi-group]');if(!b)return;e.preventDefault();e.stopImmediatePropagation();run(b.dataset.drivePoiGroup)},true);
back?.addEventListener('click',e=>{e.preventDefault();e.stopImmediatePropagation();renderRoot()},true);
window.LuminaDrivingPOI={renderRoot,run};
})();
