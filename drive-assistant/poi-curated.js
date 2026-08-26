(()=>{
'use strict';
const API='https://api.mapbox.com/search/searchbox/v1/forward';
const GROUPS={
  food:{label:'🍽️ Εστίαση',subtitle:'Φαγητό · καφέ · γλυκό · ποτό',maxRadius:30000,queries:['restaurant','taverna','greek restaurant','seafood restaurant','pizza','pizzeria','italian restaurant','fast food','souvlaki','grill','cafe','coffee','coffee shop','ice cream','gelato','bakery','pastry shop','dessert shop','bar']},
  car:{label:'⛽ Αυτοκίνητο',subtitle:'Καύσιμα · συνεργεία · ελαστικά',maxRadius:60000,queries:['gas station','fuel station','car repair','auto repair','tire shop','tyre shop','auto parts','car wash','EV charging station']},
  health:{label:'🏥 Πρώτες Βοήθειες',subtitle:'Φαρμακεία · νοσοκομεία · κέντρα υγείας',maxRadius:60000,queries:['pharmacy','hospital','health center','medical center','medical clinic','emergency room','emergency department']},
  shopping:{label:'🛍️ Αγορές',subtitle:'Supermarket · εμπορικά · καταστήματα',maxRadius:30000,queries:['supermarket','mini market','grocery store','shopping mall','clothing store','shoe store','electronics store','department store','home goods store','hardware store','convenience store']}
};
const RADII=[3000,10000,30000,60000];
const $=s=>document.querySelector(s);
const drawer=$('#poiDrawer'),cats=$('#poiCategories'),results=$('#poiResults'),title=$('#poiTitle'),back=$('#poiBackBtn');
const token=()=>String(window.__LUMINA_CONFIG__?.mapboxAccessToken||localStorage.getItem('lumina-mapbox-public-token')||'').trim();
const esc=s=>String(s||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const norm=s=>String(s||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLocaleLowerCase('el-GR').replace(/[^a-z0-9α-ω]+/gi,' ').trim();
const rad=v=>v*Math.PI/180;
const distance=(a,b)=>{const R=6371e3,p1=rad(a.lat),p2=rad(b.lat),dp=rad(b.lat-a.lat),dl=rad(b.lng-a.lng),x=Math.sin(dp/2)**2+Math.cos(p1)*Math.cos(p2)*Math.sin(dl/2)**2;return 2*R*Math.atan2(Math.sqrt(x),Math.sqrt(1-x))};
const fd=m=>m<1000?`${Math.round(m)} m`:`${(m/1000).toFixed(1)} km`;
async function gps(){const p=window.LuminaGPS?.getLastFix?.(60000)||window.LuminaGPS?.lastFix;if(Number.isFinite(+p?.lat)&&Number.isFinite(+p?.lng))return{lat:+p.lat,lng:+p.lng,accuracy:p.accuracy||null};if(window.LuminaGPS?.getPosition)return window.LuminaGPS.getPosition({maxAge:60000,timeout:7000});throw new Error('gps-unavailable')}
async function fetchQuery(q,o,key,maxRadius){const u=new URL(API);u.searchParams.set('q',q);u.searchParams.set('access_token',key);u.searchParams.set('language','el');u.searchParams.set('limit','10');u.searchParams.set('proximity',`${o.lng},${o.lat}`);u.searchParams.set('country','GR');u.searchParams.set('types','poi');const c=new AbortController(),t=setTimeout(()=>c.abort(),9000);try{const r=await fetch(u,{cache:'no-store',signal:c.signal,headers:{Accept:'application/json'}});const text=await r.text();let d={};try{d=text?JSON.parse(text):{}}catch{}if(!r.ok){const e=new Error(`HTTP ${r.status}`);e.status=r.status;throw e}return(d.features||[]).map(f=>{const p=f.properties||{},co=f.geometry?.coordinates||[],pt={lat:+co[1],lng:+co[0]};if(!Number.isFinite(pt.lat)||!Number.isFinite(pt.lng)||!p.name)return null;const dist=distance(o,pt);if(dist>maxRadius)return null;return{name:p.name,point:pt,distance:dist,area:p.full_address||p.place_formatted||p.address||'Κοντινή περιοχή'}}).filter(Boolean)}finally{clearTimeout(t)}}
function merge(groups){const out=[];for(const x of groups.flat().filter(Boolean).sort((a,b)=>a.distance-b.distance)){const n=norm(x.name);if(out.some(y=>distance(x.point,y.point)<45||(distance(x.point,y.point)<160&&n&&norm(y.name)===n)))continue;out.push(x)}return out.slice(0,100)}
function root(){if(!cats||!results)return;title.textContent='Σημεία ενδιαφέροντος';back.classList.add('hidden');results.innerHTML='';cats.innerHTML=Object.entries(GROUPS).map(([k,g])=>`<button type="button" class="poi-category" data-curated-group="${k}"><strong>${g.label}</strong><span>${g.subtitle}</span></button>`).join('')}
async function run(k){const g=GROUPS[k],key=token();if(!g||!results)return;title.textContent=g.label.replace(/^\S+\s/,'');back.classList.remove('hidden');cats.innerHTML='';if(!key){results.innerHTML='<div class="poi-loading error">Το Mapbox δεν είναι διαθέσιμο.</div>';return}results.innerHTML='<div class="poi-loading busy"><span class="poi-spinner"></span><strong>Mapbox: βρίσκω όλα τα κοντινά σημεία…</strong></div>';try{const o=await gps();const batches=await Promise.all(g.queries.map(q=>fetchQuery(q,o,key,g.maxRadius).catch(()=>[])));const all=merge(batches);if(!all.length){results.innerHTML=`<div class="poi-loading">Δεν βρέθηκαν σημεία για ${esc(g.label)} έως ${fd(g.maxRadius)}.</div>`;return}let radius=RADII.find(r=>r>=g.maxRadius)||g.maxRadius;for(const r of RADII){if(r>g.maxRadius)break;const count=all.filter(x=>x.distance<=r).length;if(count>=20||r===g.maxRadius){radius=r;break}}const items=all.filter(x=>x.distance<=radius);results.innerHTML=`<div class="poi-loading"><strong>${items.length} κοντινά σημεία</strong><br><small>Mapbox · ${esc(g.label)} · έως ${fd(radius)} · από το κοντινότερο · GPS${o.accuracy?` ±${Math.round(o.accuracy)}m`:''}</small></div>`+items.map((x,i)=>`<article class="poi-result"><div><strong>${i+1}. ${esc(x.name)}</strong><span>${fd(x.distance)} · ${esc(x.area)}</span></div><button type="button" class="poi-route" data-lat="${x.point.lat}" data-lng="${x.point.lng}" data-name="${esc(x.name)}">▶ Έναρξη</button></article>`).join('')}catch(e){results.innerHTML=`<div class="poi-loading error"><strong>Mapbox: ${esc(e?.message||'σφάλμα')}</strong></div>`}}
function open(){drawer?.classList.remove('hidden');root()}
function close(){drawer?.classList.add('hidden')}
document.addEventListener('click',e=>{
  const openBtn=e.target.closest?.('#poiOpenBtn,#navPoiBtn');
  const closeBtn=e.target.closest?.('#poiCloseBtn');
  const backBtn=e.target.closest?.('#poiBackBtn');
  const g=e.target.closest?.('[data-curated-group]');
  if(openBtn){e.preventDefault();e.stopImmediatePropagation();open();return}
  if(closeBtn){e.preventDefault();e.stopImmediatePropagation();close();return}
  if(backBtn){e.preventDefault();e.stopImmediatePropagation();root();return}
  if(g){e.preventDefault();e.stopImmediatePropagation();run(g.dataset.curatedGroup);return}
},true);
window.LuminaCuratedPOI={open,root,run,groups:GROUPS};
})();
