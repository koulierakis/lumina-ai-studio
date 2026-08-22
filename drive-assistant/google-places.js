(()=>{
  const TYPE_MAP={
    restaurant:['restaurant','cafe','bar','bakery','meal_takeaway'],
    fast_food:['fast_food_restaurant','meal_takeaway','hamburger_restaurant','pizza_restaurant'],
    cafe:['cafe','coffee_shop','bakery'],
    bar:['bar','pub'],
    ice_cream:['ice_cream_shop'],
    hotel:['hotel'],motel:['motel'],guest_house:['guest_house'],camp_site:['campground'],
    supermarket:['supermarket'],convenience:['convenience_store'],bakery:['bakery'],mall:['shopping_mall'],
    pharmacy:['pharmacy'],hospital:['hospital'],clinic:['medical_clinic'],dentist:['dentist'],
    fuel:['gas_station'],parking:['parking'],charging:['electric_vehicle_charging_station'],taxi:['taxi_stand'],bus:['bus_stop'],
    bank:['bank'],atm:['atm'],police:['police'],post:['post_office'],gym:['gym'],beach:['beach'],museum:['museum'],attraction:['tourist_attraction'],playground:['playground']
  };
  const RADII=[1500,3000,6000,12000];
  const bypass=new WeakSet(); let loaderPromise=null, authFailed=false;
  const rad=v=>v*Math.PI/180;
  const dist=(a,b)=>{const R=6371e3,p1=rad(a.lat),p2=rad(b.lat),dp=rad(b.lat-a.lat),dl=rad(b.lng-a.lng),x=Math.sin(dp/2)**2+Math.cos(p1)*Math.cos(p2)*Math.sin(dl/2)**2;return 2*R*Math.atan2(Math.sqrt(x),Math.sqrt(1-x))};
  const fd=m=>m<1000?`${Math.round(m)} m`:`${(m/1000).toFixed(1)} km`;
  const esc=s=>String(s||'').replace(/[&<>'\"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','\"':'&quot;'}[c]));
  const norm=s=>String(s||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase().replace(/[^a-z0-9α-ω]+/gi,' ').trim();
  function getPos(){return new Promise((resolve,reject)=>navigator.geolocation.getCurrentPosition(p=>resolve({lat:p.coords.latitude,lng:p.coords.longitude}),reject,{enableHighAccuracy:true,maximumAge:2500,timeout:15000}))}
  function setStatus(message){const results=document.querySelector('#poiResults');if(results)results.innerHTML=`<div class="poi-loading">${esc(message)}</div>`}
  function loadPlaces(){
    if(window.google?.maps?.importLibrary)return Promise.resolve();
    if(loaderPromise)return loaderPromise;
    const key=window.__LUMINA_CONFIG__?.googleMapsApiKey;
    if(!key)return Promise.reject(new Error('missing-google-key'));
    authFailed=false; window.gm_authFailure=()=>{authFailed=true};
    loaderPromise=new Promise((resolve,reject)=>{
      const cb='__luminaGoogleMapsReady';
      const timer=setTimeout(()=>reject(new Error(authFailed?'google-auth-failed':'google-maps-timeout')),12000);
      window[cb]=()=>{clearTimeout(timer);delete window[cb];if(authFailed)reject(new Error('google-auth-failed'));else resolve()};
      const s=document.createElement('script');
      s.async=true;s.defer=true;s.referrerPolicy='strict-origin-when-cross-origin';
      s.src=`https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(key)}&v=weekly&loading=async&libraries=places&language=el&region=GR&auth_referrer_policy=origin&callback=${cb}`;
      s.onerror=()=>{clearTimeout(timer);reject(new Error('google-maps-load-failed'))};
      document.head.appendChild(s);
    }).catch(err=>{loaderPromise=null;throw err});
    return loaderPromise;
  }
  async function nearby(type,center,radius){
    await loadPlaces();
    const {Place,SearchNearbyRankPreference}=await google.maps.importLibrary('places');
    const types=TYPE_MAP[type]; if(!types)throw new Error('unsupported-google-place-type');
    const raw=[];
    for(const primaryType of types){
      try{
        const {places}=await Place.searchNearby({
          fields:['id','displayName','location','formattedAddress','primaryType'],
          locationRestriction:{center,radius},
          includedPrimaryTypes:[primaryType],
          maxResultCount:20,
          rankPreference:SearchNearbyRankPreference.DISTANCE
        });
        raw.push(...(places||[]));
      }catch(err){console.warn('Google Places type failed',primaryType,err)}
    }
    const seen=[];
    for(const p of raw){
      const lat=typeof p.location?.lat==='function'?p.location.lat():p.location?.lat;
      const lng=typeof p.location?.lng==='function'?p.location.lng():p.location?.lng;
      if(!Number.isFinite(lat)||!Number.isFinite(lng))continue;
      const point={lat,lng},name=p.displayName||'Χωρίς όνομα',address=p.formattedAddress||'',d=dist(center,point),nameKey=norm(name);
      const duplicate=seen.some(x=>(p.id&&x.id===p.id)||(nameKey&&norm(x.name)===nameKey&&dist(point,x.p)<120));
      if(!duplicate)seen.push({id:p.id||'',p:point,d,name,address,source:'google'});
    }
    return seen.sort((a,b)=>a.d-b.d);
  }
  function render(arr,radius){
    const results=document.querySelector('#poiResults');if(!results)return;
    const note=`<div class="poi-loading">Google Places · ${arr.length} σημεία · από το κοντινότερο · ακτίνα ${radius<1000?radius+' m':radius/1000+' km'}</div>`;
    results.innerHTML=note+arr.slice(0,60).map(x=>`<article class="poi-result"><div><strong>${esc(x.name)}</strong><span>${fd(x.d)}${x.address?' · '+esc(x.address):''}</span></div><button class="poi-route" data-lat="${x.p.lat}" data-lng="${x.p.lng}" data-name="${esc(x.name)}">Οδηγίες</button></article>`).join('');
  }
  async function runGoogle(item){
    setStatus('Google Places: σαρώνω όλα τα κοντινά σημεία…');
    const center=await getPos(); let best=[],bestRadius=RADII[0];
    for(const radius of RADII){
      const arr=await nearby(item.dataset.poiType,center,radius);
      if(arr.length>best.length){best=arr;bestRadius=radius}
      if(arr.length>=20)break;
    }
    if(best.length){render(best,bestRadius);return true}
    return false;
  }
  document.querySelector('#poiCategories')?.addEventListener('click',async e=>{
    const item=e.target.closest('[data-poi-type]');
    if(!item||bypass.has(item)){if(item)bypass.delete(item);return}
    if(!window.__LUMINA_CONFIG__?.googleMapsApiKey)return;
    e.preventDefault();e.stopImmediatePropagation();
    try{
      const ok=await runGoogle(item);if(ok)return;
      if(window.google?.maps?.importLibrary){setStatus('Google Places δεν επέστρεψε αποτελέσματα για αυτή την κατηγορία.');return}
    }catch(err){
      console.warn('LUMINA Google Places:',err);
      const msg=String(err?.message||err);
      if(/auth|maps-load|timeout/i.test(msg)){setStatus('Google Places authorization απέτυχε. Έλεγξε billing και website restriction του API key.');return}
    }
    bypass.add(item);item.click();
  },true);
})();