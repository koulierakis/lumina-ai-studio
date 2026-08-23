(()=>{
  'use strict';
  const RADIUS=10000;
  const ENDPOINTS=['https://overpass-api.de/api/interpreter','https://overpass.kumi.systems/api/interpreter'];
  const PHOTON='https://photon.komoot.io/api/';
  const $=s=>document.querySelector(s);
  const results=$('#poiResults');
  const rad=v=>v*Math.PI/180;
  const dist=(a,b)=>{const R=6371e3,p1=rad(a.lat),p2=rad(b.lat),dp=rad(b.lat-a.lat),dl=rad(b.lng-a.lng),x=Math.sin(dp/2)**2+Math.cos(p1)*Math.cos(p2)*Math.sin(dl/2)**2;return 2*R*Math.atan2(Math.sqrt(x),Math.sqrt(1-x))};
  const esc=s=>String(s||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const norm=s=>String(s||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase().replace(/[^a-z0-9α-ω]+/gi,' ').trim();
  const fd=m=>m<1000?`${Math.round(m)} m`:`${(m/1000).toFixed(1)} km`;
  const delay=ms=>new Promise(r=>setTimeout(r,ms));
  const tagsByType={
    restaurant:[['amenity','restaurant'],['amenity','fast_food']],
    fast_food:[['amenity','fast_food'],['amenity','restaurant']],
    cafe:[['amenity','cafe'],['shop','coffee']],
    bar:[['amenity','bar'],['amenity','pub']],
    ice_cream:[['amenity','ice_cream'],['shop','ice_cream']],
    hotel:[['tourism','hotel']],motel:[['tourism','motel']],guest_house:[['tourism','guest_house']],camp_site:[['tourism','camp_site']],
    supermarket:[['shop','supermarket']],convenience:[['shop','convenience']],bakery:[['shop','bakery']],mall:[['shop','mall']],
    pharmacy:[['amenity','pharmacy']],hospital:[['amenity','hospital']],clinic:[['amenity','clinic']],dentist:[['amenity','dentist']],
    fuel:[['amenity','fuel']],parking:[['amenity','parking']],charging:[['amenity','charging_station']],taxi:[['amenity','taxi']],bus:[['highway','bus_stop']],
    bank:[['amenity','bank']],atm:[['amenity','atm']],police:[['amenity','police']],post:[['amenity','post_office']],
    gym:[['leisure','fitness_centre']],beach:[['natural','beach']],museum:[['tourism','museum']],attraction:[['tourism','attraction']],playground:[['leisure','playground']]
  };
  const terms={restaurant:['restaurant','taverna','ταβέρνα','εστιατόριο'],fast_food:['fast food','souvlaki','σουβλάκι'],cafe:['cafe','coffee','καφέ'],bar:['bar','pub'],ice_cream:['ice cream','gelato','παγωτό'],hotel:['hotel'],motel:['motel'],guest_house:['guest house'],camp_site:['camping'],supermarket:['supermarket'],convenience:['mini market'],bakery:['bakery'],mall:['shopping mall'],pharmacy:['pharmacy'],hospital:['hospital'],clinic:['clinic'],dentist:['dentist'],fuel:['fuel'],parking:['parking'],charging:['charging station'],taxi:['taxi'],bus:['bus stop'],bank:['bank'],atm:['atm'],police:['police'],post:['post office'],gym:['gym'],beach:['beach'],museum:['museum'],attraction:['attraction'],playground:['playground']};

  function markerPosition(){
    try{
      const p=window.__luminaCurrentUserMarker?.getLatLng?.();
      if(Number.isFinite(p?.lat)&&Number.isFinite(p?.lng))return{lat:+p.lat,lng:+p.lng,source:'active-map'};
    }catch{}
    return null;
  }
  function oneGpsAttempt(timeout=6500){return new Promise((resolve,reject)=>{
    if(!navigator.geolocation)return reject(new Error('gps-unavailable'));
    navigator.geolocation.getCurrentPosition(p=>{
      const lat=Number(p.coords.latitude),lng=Number(p.coords.longitude);
      if(!Number.isFinite(lat)||!Number.isFinite(lng))return reject(new Error('gps-invalid'));
      resolve({lat,lng,accuracy:Number(p.coords.accuracy)||null,source:'geolocation'});
    },reject,{enableHighAccuracy:true,timeout,maximumAge:15000});
  })}
  async function gps(){
    const cached=markerPosition();
    if(cached)return cached;
    let lastError;
    for(let attempt=1;attempt<=3;attempt++){
      try{return await oneGpsAttempt(5500+attempt*1000)}catch(e){lastError=e;if(attempt<3)await delay(500*attempt)}
    }
    throw lastError||new Error('gps-failed');
  }
  async function json(url,opts={},timeout=10000){const c=new AbortController(),t=setTimeout(()=>c.abort(),timeout);try{const r=await fetch(url,{...opts,signal:c.signal,cache:'no-store'});if(!r.ok)throw new Error(`HTTP ${r.status}`);return await r.json()}finally{clearTimeout(t)}}
  function point(el){if(Number.isFinite(el.lat)&&Number.isFinite(el.lon))return{lat:el.lat,lng:el.lon};if(Number.isFinite(el.center?.lat)&&Number.isFinite(el.center?.lon))return{lat:el.center.lat,lng:el.center.lon};return null}
  function overpassQuery(type,o){const clauses=[];for(const [k,v] of tagsByType[type]||[])for(const kind of ['node','way','relation'])clauses.push(`${kind}(around:${RADIUS},${o.lat},${o.lng})["${k}"="${v}"];`);return`[out:json][timeout:20];(${clauses.join('')});out center tags;`}
  async function overpass(type,o){const q=overpassQuery(type,o);let last;for(const ep of ENDPOINTS){try{const d=await json(`${ep}?data=${encodeURIComponent(q)}`,{headers:{Accept:'application/json'}},12000);return(d.elements||[]).map(el=>{const p=point(el),t=el.tags||{};if(!p)return null;const name=t['name:el']||t.name||t.brand||t.operator;if(!name)return null;return{name,point:p,distance:dist(o,p),area:[t['addr:street'],t['addr:place']||t['addr:city']||t['addr:town']||t['addr:village']].filter(Boolean).join(' · ')||'Κοντινή περιοχή'} }).filter(x=>x&&x.distance<=RADIUS)}catch(e){last=e}}throw last||new Error('overpass')}
  async function photon(type,o){const accepted=new Set((tagsByType[type]||[]).map(([k,v])=>`${k}:${v}`));const out=[];for(const term of (terms[type]||[type]).slice(0,4)){try{const u=new URL(PHOTON);u.searchParams.set('q',term);u.searchParams.set('lat',o.lat);u.searchParams.set('lon',o.lng);u.searchParams.set('limit','50');u.searchParams.set('lang','el');const d=await json(u.toString(),{headers:{Accept:'application/json'}},9000);for(const f of d.features||[]){const p=f.properties||{},c=f.geometry?.coordinates||[],pt={lat:+c[1],lng:+c[0]},key=`${p.osm_key||''}:${p.osm_value||''}`;if(!accepted.has(key)||!Number.isFinite(pt.lat)||!Number.isFinite(pt.lng))continue;const name=p.name||p.street||p.city;if(!name)continue;const distance=dist(o,pt);if(distance>RADIUS)continue;out.push({name,point:pt,distance,area:[p.street,p.city||p.town||p.village].filter(Boolean).join(' · ')||'Κοντινή περιοχή'});}}catch{}}
    return out;
  }
  function merge(items){const seen=new Set(),out=[];for(const x of items.flat().sort((a,b)=>a.distance-b.distance)){const k=`${norm(x.name)}|${x.point.lat.toFixed(4)}|${x.point.lng.toFixed(4)}`;if(seen.has(k))continue;seen.add(k);out.push(x)}return out}
  function render(items){if(!results)return;if(!items.length){results.innerHTML='<div class="poi-loading">Δεν βρέθηκαν επιβεβαιωμένα σημεία κοντά στη θέση σου.</div>';return}results.innerHTML=`<div class="poi-loading">${items.length} σημεία έως 10 km · κοντινότερα πρώτα</div>`+items.slice(0,80).map(x=>`<article class="poi-result"><div><strong>${esc(x.name)}</strong><span>${fd(x.distance)} · ${esc(x.area)}</span></div><button type="button" class="poi-route" data-lat="${x.point.lat}" data-lng="${x.point.lng}" data-name="${esc(x.name)}">▶ Έναρξη</button></article>`).join('')}
  async function run(type){
    if(!results)return;
    results.innerHTML='<div class="poi-loading busy"><span class="poi-spinner"></span><strong>Εντοπίζω τη θέση σου…</strong><small>Χρησιμοποιώ το ενεργό GPS του χάρτη.</small></div>';
    let o;
    try{o=await gps()}catch(e){results.innerHTML='<div class="poi-loading error">Δεν υπάρχει ακόμη αξιόπιστη θέση GPS. Περίμενε λίγα δευτερόλεπτα και ξαναπάτησε.</div>';return}
    results.innerHTML='<div class="poi-loading busy"><span class="poi-spinner"></span><strong>Αναζητώ κοντινά σημεία…</strong><small>Συνδυάζω πολλαπλές ζωντανές πηγές.</small></div>';
    const settled=await Promise.allSettled([overpass(type,o),photon(type,o)]);
    const all=settled.filter(x=>x.status==='fulfilled').map(x=>x.value);
    if(!all.length){results.innerHTML='<div class="poi-loading error">Η θέση GPS είναι σωστή, αλλά οι υπηρεσίες κοντινών σημείων δεν απάντησαν. Δοκίμασε ξανά σε λίγο.</div>';return}
    render(merge(all));
  }
  document.addEventListener('click',e=>{const b=e.target.closest?.('[data-poi-type]');if(!b)return;e.preventDefault();e.stopImmediatePropagation();run(b.dataset.poiType);},true);
})();
