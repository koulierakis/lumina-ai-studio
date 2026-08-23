(()=>{
  'use strict';

  const $=s=>document.querySelector(s);
  const RADIUS_M=6000;
  const OVERPASS_ENDPOINTS=[
    'https://overpass-api.de/api/interpreter',
    'https://overpass.kumi.systems/api/interpreter',
    'https://overpass.nchc.org.tw/api/interpreter'
  ];

  const CATEGORIES={
    stay:{label:'Διαμονή',items:[['hotel','🏨 Ξενοδοχεία','tourism','hotel'],['motel','🛏️ Μοτέλ','tourism','motel'],['guest_house','🏡 Ξενώνες','tourism','guest_house'],['camp_site','⛺ Camping','tourism','camp_site']]},
    food:{label:'Φαγητό & Ποτό',items:[['restaurant','🍽️ Εστιατόρια','amenity','restaurant'],['fast_food','🍔 Fast food / Σουβλάκι','amenity','fast_food'],['cafe','☕ Καφέ','amenity','cafe'],['bar','🍸 Bar','amenity','bar'],['ice_cream','🍦 Παγωτό','amenity','ice_cream']]},
    shopping:{label:'Αγορές',items:[['supermarket','🛒 Supermarket','shop','supermarket'],['convenience','🥤 Mini market','shop','convenience'],['bakery','🥖 Φούρνοι','shop','bakery'],['mall','🏬 Εμπορικά κέντρα','shop','mall']]},
    health:{label:'Υγεία',items:[['pharmacy','💊 Φαρμακεία','amenity','pharmacy'],['hospital','🏥 Νοσοκομεία','amenity','hospital'],['clinic','🩺 Κλινικές','amenity','clinic'],['dentist','🦷 Οδοντίατροι','amenity','dentist']]},
    mobility:{label:'Μετακίνηση',items:[['fuel','⛽ Βενζινάδικα','amenity','fuel'],['parking','🅿️ Parking','amenity','parking'],['charging','⚡ Φόρτιση EV','amenity','charging_station'],['taxi','🚕 Taxi','amenity','taxi'],['bus','🚌 Στάσεις λεωφορείου','highway','bus_stop']]},
    services:{label:'Υπηρεσίες',items:[['bank','🏦 Τράπεζες','amenity','bank'],['atm','💶 ATM','amenity','atm'],['police','👮 Αστυνομία','amenity','police'],['post','📮 Ταχυδρομεία','amenity','post_office']]},
    leisure:{label:'Αναψυχή',items:[['gym','🏋️ Γυμναστήρια','leisure','fitness_centre'],['beach','🏖️ Παραλίες','natural','beach'],['museum','🏛️ Μουσεία','tourism','museum'],['attraction','📸 Αξιοθέατα','tourism','attraction'],['playground','🛝 Παιδικές χαρές','leisure','playground']]}
  };

  const EXTRA_TAGS={
    bar:[['amenity','bar'],['amenity','pub']],
    ice_cream:[['amenity','ice_cream'],['shop','ice_cream']]
  };

  const drawer=$('#poiDrawer');
  const cats=$('#poiCategories');
  const results=$('#poiResults');
  const title=$('#poiTitle');
  const back=$('#poiBackBtn');
  let lastOrigin=null;

  const esc=s=>String(s||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const norm=s=>String(s||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLocaleLowerCase('el-GR').replace(/[^a-z0-9α-ω]+/gi,' ').trim();
  const rad=v=>v*Math.PI/180;

  function distanceMeters(a,b){
    const R=6371e3;
    const p1=rad(a.lat),p2=rad(b.lat),dp=rad(b.lat-a.lat),dl=rad(b.lng-a.lng);
    const x=Math.sin(dp/2)**2+Math.cos(p1)*Math.cos(p2)*Math.sin(dl/2)**2;
    return 2*R*Math.atan2(Math.sqrt(x),Math.sqrt(1-x));
  }

  const distanceKm=m=>`${(m/1000).toFixed(m<1000?2:1)} km`;

  function open(){drawer?.classList.remove('hidden');renderCategories()}
  function close(){drawer?.classList.add('hidden')}

  function renderCategories(){
    if(!title||!back||!cats||!results)return;
    title.textContent='Σημεία ενδιαφέροντος';
    back.classList.add('hidden');
    results.innerHTML='';
    cats.innerHTML=Object.entries(CATEGORIES).map(([key,group])=>`<button class="poi-category" data-poi-group="${key}"><strong>${group.label}</strong><span>${group.items.length} κατηγορίες</span></button>`).join('');
  }

  function renderGroup(key){
    const group=CATEGORIES[key];
    if(!group||!title||!back||!cats||!results)return;
    title.textContent=group.label;
    back.classList.remove('hidden');
    cats.innerHTML=group.items.map(item=>`<button class="poi-item" data-poi-type="${item[0]}" data-k="${item[2]}" data-v="${item[3]}">${item[1]}</button>`).join('');
    results.innerHTML='';
  }

  function getLivePosition(){
    return new Promise((resolve,reject)=>{
      if(!navigator.geolocation)return reject(new Error('geolocation-unavailable'));
      navigator.geolocation.getCurrentPosition(
        p=>resolve({lat:p.coords.latitude,lng:p.coords.longitude,accuracy:p.coords.accuracy}),
        reject,
        {enableHighAccuracy:true,maximumAge:0,timeout:15000}
      );
    });
  }

  function tagsFor(type,k,v){return EXTRA_TAGS[type]||[[k,v]]}

  function buildOverpassQuery(type,k,v,origin){
    const clauses=[];
    for(const [tagKey,tagValue] of tagsFor(type,k,v)){
      for(const element of ['node','way','relation']){
        clauses.push(`${element}(around:${RADIUS_M},${origin.lat},${origin.lng})[\"${tagKey}\"=\"${tagValue}\"];`);
      }
    }
    return `[out:json][timeout:18];(${clauses.join('')});out center tags;`;
  }

  async function fetchOverpass(query){
    let lastError=null;
    for(const endpoint of OVERPASS_ENDPOINTS){
      const controller=new AbortController();
      const timer=setTimeout(()=>controller.abort(),12000);
      try{
        const response=await fetch(endpoint,{
          method:'POST',
          body:`data=${encodeURIComponent(query)}`,
          headers:{'Content-Type':'application/x-www-form-urlencoded;charset=UTF-8','Accept':'application/json'},
          cache:'no-store',
          signal:controller.signal
        });
        if(!response.ok)throw new Error(`overpass-${response.status}`);
        return await response.json();
      }catch(error){
        lastError=error;
      }finally{
        clearTimeout(timer);
      }
    }
    throw lastError||new Error('overpass-unavailable');
  }

  function pointFor(element){
    if(Number.isFinite(element.lat)&&Number.isFinite(element.lon))return{lat:element.lat,lng:element.lon};
    if(Number.isFinite(element.center?.lat)&&Number.isFinite(element.center?.lon))return{lat:element.center.lat,lng:element.center.lon};
    return null;
  }

  function areaLabel(tags){
    const street=[tags['addr:street'],tags['addr:housenumber']].filter(Boolean).join(' ');
    const area=tags['addr:suburb']||tags['addr:place']||tags['addr:city']||tags['addr:town']||tags['addr:village']||tags['is_in:city']||tags['is_in']||'';
    return [street,area].filter(Boolean).join(' · ')||'Κοντινή περιοχή';
  }

  function categoryMatches(type,k,v,tags){
    return tagsFor(type,k,v).some(([tagKey,tagValue])=>tags?.[tagKey]===tagValue);
  }

  function mapElements(data,type,k,v,origin){
    const raw=[];
    const seenOsmIds=new Set();
    for(const element of data.elements||[]){
      const osmKey=`${element.type}:${element.id}`;
      if(seenOsmIds.has(osmKey))continue;
      seenOsmIds.add(osmKey);
      const tags=element.tags||{};
      if(!categoryMatches(type,k,v,tags))continue;
      const point=pointFor(element);
      if(!point)continue;
      const distance=distanceMeters(origin,point);
      if(distance>RADIUS_M)continue;
      const name=tags['name:el']||tags.name||tags.brand||tags.operator||'';
      if(!name)continue;
      raw.push({osmKey,name,point,distance,area:areaLabel(tags)});
    }

    raw.sort((a,b)=>a.distance-b.distance);

    const unique=[];
    for(const item of raw){
      const normalizedName=norm(item.name);
      const duplicate=unique.some(existing=>norm(existing.name)===normalizedName&&distanceMeters(existing.point,item.point)<120);
      if(!duplicate)unique.push(item);
    }
    return unique;
  }

  function renderResults(items){
    if(!results)return;
    if(!items.length){
      results.innerHTML='<div class="poi-loading">Δεν βρέθηκαν καταστήματα κοντά σας. Δοκιμάστε να αυξήσετε την ακτίνα.</div>';
      return;
    }
    results.innerHTML=`<div class="poi-loading">Αποτελέσματα σε πραγματική ακτίνα 6 km από την τρέχουσα θέση σας.</div>${items.slice(0,60).map(item=>`<article class="poi-result"><div><strong>${esc(item.name)}</strong><span>${distanceKm(item.distance)} · ${esc(item.area)}</span></div><button type="button" class="poi-route" data-lat="${item.point.lat}" data-lng="${item.point.lng}" data-name="${esc(item.name)}">Οδηγίες</button></article>`).join('')}`;
  }

  async function search(type,k,v){
    if(!results)return;
    results.innerHTML='<div class="poi-loading">⏳ Εντοπίζω τη θέση σας και αναζητώ κοντινά σημεία…</div>';
    try{
      const origin=await getLivePosition();
      lastOrigin=origin;
      const query=buildOverpassQuery(type,k,v,origin);
      const data=await fetchOverpass(query);
      const items=mapElements(data,type,k,v,origin);
      renderResults(items);
    }catch(error){
      const permissionDenied=error?.code===1;
      results.innerHTML=`<div class="poi-loading">${permissionDenied?'Χρειάζεται άδεια τοποθεσίας για να βρω κοντινά σημεία.':'Δεν ήταν δυνατή η ζωντανή αναζήτηση αυτή τη στιγμή. Δοκιμάστε ξανά.'}</div>`;
    }
  }

  function openGoogleDirections(button){
    const lat=Number(button.dataset.lat),lng=Number(button.dataset.lng);
    if(!lastOrigin||!Number.isFinite(lat)||!Number.isFinite(lng))return;
    const url=new URL('https://www.google.com/maps/dir/');
    url.searchParams.set('api','1');
    url.searchParams.set('origin',`${lastOrigin.lat},${lastOrigin.lng}`);
    url.searchParams.set('destination',`${lat},${lng}`);
    url.searchParams.set('travelmode','driving');
    window.open(url.toString(),'_blank','noopener,noreferrer');
  }

  $('#poiOpenBtn')?.addEventListener('click',open);
  $('#poiCloseBtn')?.addEventListener('click',close);
  back?.addEventListener('click',renderCategories);
  cats?.addEventListener('click',event=>{
    const group=event.target.closest('[data-poi-group]');
    if(group)return renderGroup(group.dataset.poiGroup);
    const item=event.target.closest('[data-k]');
    if(item)search(item.dataset.poiType,item.dataset.k,item.dataset.v);
  });
  results?.addEventListener('click',event=>{
    const button=event.target.closest('.poi-route');
    if(!button)return;
    event.preventDefault();
    event.stopPropagation();
    event.stopImmediatePropagation();
    openGoogleDirections(button);
  },true);
})();