(()=>{
  const $=s=>document.querySelector(s);
  const CATEGORIES={
    stay:{label:'Διαμονή',items:[['hotel','🏨 Ξενοδοχεία','tourism','hotel'],['motel','🛏️ Μοτέλ','tourism','motel'],['guest_house','🏡 Ξενώνες','tourism','guest_house'],['camp_site','⛺ Camping','tourism','camp_site']]},
    food:{label:'Φαγητό & Ποτό',items:[['restaurant','🍽️ Εστιατόρια','amenity','restaurant'],['fast_food','🍔 Fast food / Σουβλάκι','amenity','fast_food'],['cafe','☕ Καφέ','amenity','cafe'],['bar','🍸 Bar','amenity','bar'],['ice_cream','🍦 Παγωτό','amenity','ice_cream']]},
    shopping:{label:'Αγορές',items:[['supermarket','🛒 Supermarket','shop','supermarket'],['convenience','🥤 Mini market','shop','convenience'],['bakery','🥖 Φούρνοι','shop','bakery'],['mall','🏬 Εμπορικά κέντρα','shop','mall']]},
    health:{label:'Υγεία',items:[['pharmacy','💊 Φαρμακεία','amenity','pharmacy'],['hospital','🏥 Νοσοκομεία','amenity','hospital'],['clinic','🩺 Κλινικές','amenity','clinic'],['dentist','🦷 Οδοντίατροι','amenity','dentist']]},
    mobility:{label:'Μετακίνηση',items:[['fuel','⛽ Βενζινάδικα','amenity','fuel'],['parking','🅿️ Parking','amenity','parking'],['charging','⚡ Φόρτιση EV','amenity','charging_station'],['taxi','🚕 Taxi','amenity','taxi'],['bus','🚌 Στάσεις λεωφορείου','highway','bus_stop']]},
    services:{label:'Υπηρεσίες',items:[['bank','🏦 Τράπεζες','amenity','bank'],['atm','💶 ATM','amenity','atm'],['police','👮 Αστυνομία','amenity','police'],['post','📮 Ταχυδρομεία','amenity','post_office']]},
    leisure:{label:'Αναψυχή',items:[['gym','🏋️ Γυμναστήρια','leisure','fitness_centre'],['beach','🏖️ Παραλίες','natural','beach'],['museum','🏛️ Μουσεία','tourism','museum'],['attraction','📸 Αξιοθέατα','tourism','attraction'],['playground','🛝 Παιδικές χαρές','leisure','playground']]}
  };
  const OVERPASS_ENDPOINTS=['https://overpass-api.de/api/interpreter','https://overpass.kumi.systems/api/interpreter'];
  const drawer=$('#poiDrawer'),cats=$('#poiCategories'),results=$('#poiResults'),title=$('#poiTitle'),back=$('#poiBackBtn');
  function open(){drawer.classList.remove('hidden');renderCategories()}
  function close(){drawer.classList.add('hidden')}
  function renderCategories(){title.textContent='Σημεία ενδιαφέροντος';back.classList.add('hidden');results.innerHTML='';cats.innerHTML=Object.entries(CATEGORIES).map(([k,v])=>`<button class="poi-category" data-poi-group="${k}"><strong>${v.label}</strong><span>${v.items.length} κατηγορίες</span></button>`).join('');}
  function renderGroup(key){const g=CATEGORIES[key];if(!g)return;title.textContent=g.label;back.classList.remove('hidden');cats.innerHTML=g.items.map(i=>`<button class="poi-item" data-poi-type="${i[0]}" data-k="${i[2]}" data-v="${i[3]}">${i[1]}</button>`).join('');results.innerHTML='';}
  function getPos(){return new Promise((res,rej)=>navigator.geolocation?navigator.geolocation.getCurrentPosition(p=>res({lat:p.coords.latitude,lng:p.coords.longitude,accuracy:p.coords.accuracy}),rej,{enableHighAccuracy:true,maximumAge:4000,timeout:15000}):rej(new Error('geolocation-unavailable')))}
  const esc=s=>String(s||'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
  const rad=v=>v*Math.PI/180;function distance(a,b){const R=6371e3,p1=rad(a.lat),p2=rad(b.lat),dp=rad(b.lat-a.lat),dl=rad(b.lng-a.lng),x=Math.sin(dp/2)**2+Math.cos(p1)*Math.cos(p2)*Math.sin(dl/2)**2;return 2*R*Math.atan2(Math.sqrt(x),Math.sqrt(1-x))}
  const fd=m=>m<1000?`${Math.round(m)} m`:`${(m/1000).toFixed(1)} km`;

  async function fetchOverpass(query){
    let lastError=null;
    for(const endpoint of OVERPASS_ENDPOINTS){
      const controller=new AbortController();
      const timer=setTimeout(()=>controller.abort(),9000);
      try{
        const body=`data=${encodeURIComponent(query)}`;
        const r=await fetch(endpoint,{method:'POST',body,signal:controller.signal,headers:{'Content-Type':'application/x-www-form-urlencoded;charset=UTF-8','Accept':'application/json'}});
        if(!r.ok)throw new Error(`overpass-${r.status}`);
        return await r.json();
      }catch(e){lastError=e;}finally{clearTimeout(timer)}
    }
    throw lastError||new Error('overpass-unavailable');
  }

  function makeQuery(c,k,v,radius){return `[out:json][timeout:12];(node(around:${radius},${c.lat},${c.lng})["${k}"="${v}"];way(around:${radius},${c.lat},${c.lng})["${k}"="${v}"];relation(around:${radius},${c.lat},${c.lng})["${k}"="${v}"];);out center tags 80;`;}

  async function search(k,v){
    results.innerHTML='<div class="poi-loading">Αναζήτηση κοντά σου…</div>';
    try{
      const c=await getPos();
      let j=await fetchOverpass(makeQuery(c,k,v,5000));
      if(!(j.elements||[]).length)j=await fetchOverpass(makeQuery(c,k,v,12000));
      const arr=[],seen=new Set();
      for(const x of (j.elements||[])){
        const p=Number.isFinite(x.lat)?{lat:x.lat,lng:x.lon}:x.center&&Number.isFinite(x.center.lat)?{lat:x.center.lat,lng:x.center.lon}:null;
        if(!p)continue;
        const id=`${x.type}:${x.id}`;if(seen.has(id))continue;seen.add(id);
        const tags=x.tags||{};
        const name=tags.name||tags.brand||tags.operator||'Χωρίς καταχωρημένο όνομα';
        const address=[tags['addr:street'],tags['addr:housenumber'],tags['addr:city']].filter(Boolean).join(' ');
        arr.push({p,d:distance(c,p),name,address});
      }
      arr.sort((a,b)=>a.d-b.d);
      results.innerHTML=arr.length?arr.slice(0,30).map(x=>`<article class="poi-result"><div><strong>${esc(x.name)}</strong><span>${fd(x.d)}${x.address?' · '+esc(x.address):''}</span></div><button class="poi-route" data-lat="${x.p.lat}" data-lng="${x.p.lng}" data-name="${esc(x.name)}">Οδηγίες</button></article>`).join(''):'<div class="poi-loading">Δεν βρέθηκαν καταχωρημένα αποτελέσματα σε ακτίνα 12 km.</div>';
    }catch(e){
      const gpsProblem=e&&(/geolocation|position|permission/i.test(String(e.message||e))||e.code);
      results.innerHTML=`<div class="poi-loading">${gpsProblem?'Δεν ήταν διαθέσιμη η ακριβής θέση GPS.':'Η υπηρεσία κοντινών σημείων δεν απάντησε. Δοκίμασε ξανά σε λίγα δευτερόλεπτα.'}</div>`;
    }
  }

  $('#poiOpenBtn')?.addEventListener('click',open);$('#poiCloseBtn')?.addEventListener('click',close);back?.addEventListener('click',renderCategories);
  cats?.addEventListener('click',e=>{const g=e.target.closest('[data-poi-group]');if(g)return renderGroup(g.dataset.poiGroup);const i=e.target.closest('[data-k]');if(i)search(i.dataset.k,i.dataset.v)});
  results?.addEventListener('click',e=>{if(e.target.closest('.poi-route'))close()});
})();