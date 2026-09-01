(()=>{
  'use strict';
  const TYPE_MAP={
    restaurant:['restaurant','cafe','bar','bakery','meal_takeaway'],
    fast_food:['fast_food_restaurant','meal_takeaway','hamburger_restaurant','pizza_restaurant'],
    cafe:['cafe','coffee_shop','bakery'],bar:['bar','pub'],ice_cream:['ice_cream_shop'],
    hotel:['hotel','lodging'],motel:['motel'],guest_house:['guest_house'],camp_site:['campground'],
    supermarket:['supermarket'],convenience:['convenience_store'],bakery:['bakery'],mall:['shopping_mall'],
    pharmacy:['pharmacy'],hospital:['hospital'],clinic:['medical_clinic'],dentist:['dentist'],
    fuel:['gas_station'],parking:['parking'],charging:['electric_vehicle_charging_station'],taxi:['taxi_stand'],bus:['bus_stop'],
    bank:['bank'],atm:['atm'],police:['police'],post:['post_office'],gym:['gym'],beach:['beach'],museum:['museum'],attraction:['tourist_attraction'],playground:['playground']
  };
  const RADII=[750,1500,3000,6000,12000];
  let loaderPromise=null,authFailed=false;
  const api=window.LuminaGooglePlaces=window.LuminaGooglePlaces||{};
  const rad=v=>v*Math.PI/180;
  const dist=(a,b)=>{const R=6371e3,p1=rad(a.lat),p2=rad(b.lat),dp=rad(b.lat-a.lat),dl=rad(b.lng-a.lng),x=Math.sin(dp/2)**2+Math.cos(p1)*Math.cos(p2)*Math.sin(dl/2)**2;return 2*R*Math.atan2(Math.sqrt(x),Math.sqrt(1-x))};
  const norm=s=>String(s||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLocaleLowerCase('el-GR').replace(/[^a-z0-9α-ω]+/gi,' ').trim();
  const inGreece=p=>p.lat>=34.5&&p.lat<=42.2&&p.lng>=19.0&&p.lng<=30.0;
  function key(){return String(window.__LUMINA_CONFIG__?.googleMapsApiKey||localStorage.getItem('lumina-google-maps-api-key')||'').trim()}
  api.hasKey=()=>!!key();
  api.saveKey=value=>{const v=String(value||'').trim();if(v)localStorage.setItem('lumina-google-maps-api-key',v);else localStorage.removeItem('lumina-google-maps-api-key');loaderPromise=null;return!!v};
  function currentPos(){const f=window.LuminaGPS?.getLastFix?.(60000);if(f&&Number.isFinite(+f.lat)&&Number.isFinite(+f.lng))return{lat:+f.lat,lng:+f.lng};return null}
  async function loadPlaces(){
    if(window.google?.maps?.importLibrary)return;
    if(loaderPromise)return loaderPromise;
    const k=key();if(!k)throw new Error('missing-google-key');
    authFailed=false;window.gm_authFailure=()=>{authFailed=true};
    loaderPromise=new Promise((resolve,reject)=>{
      const cb='__luminaGoogleMapsReady';
      const timer=setTimeout(()=>reject(new Error(authFailed?'google-auth-failed':'google-maps-timeout')),15000);
      window[cb]=()=>{clearTimeout(timer);delete window[cb];authFailed?reject(new Error('google-auth-failed')):resolve()};
      const s=document.createElement('script');s.async=true;s.defer=true;s.referrerPolicy='strict-origin-when-cross-origin';
      s.src=`https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(k)}&v=weekly&loading=async&libraries=places&language=el&region=GR&auth_referrer_policy=origin&callback=${cb}`;
      s.onerror=()=>{clearTimeout(timer);reject(new Error('google-maps-load-failed'))};document.head.appendChild(s);
    }).catch(e=>{loaderPromise=null;throw e});
    return loaderPromise;
  }
  api.load=loadPlaces;
  api.textSearch=async(query,origin=currentPos())=>{
    await loadPlaces();const {Place}=await google.maps.importLibrary('places');
    const request={textQuery:String(query||'').trim(),fields:['id','displayName','location','formattedAddress','primaryType'],maxResultCount:20,language:'el',region:'GR'};
    // A null origin deliberately disables proximity bias. This is used for nationwide
    // destination searches so a shop/address in another Greek city is not hidden by GPS.
    if(origin)request.locationBias={center:origin,radius:50000};
    const {places}=await Place.searchByText(request);const out=[];
    for(const p of places||[]){const lat=typeof p.location?.lat==='function'?p.location.lat():p.location?.lat,lng=typeof p.location?.lng==='function'?p.location.lng():p.location?.lng;if(!Number.isFinite(lat)||!Number.isFinite(lng)||!inGreece({lat,lng}))continue;out.push({lat,lng,name:p.displayName||'Προορισμός',address:p.formattedAddress||'',id:p.id||'',source:'google',distance:origin?dist(origin,{lat,lng}):null})}
    return origin?out.sort((a,b)=>(a.distance??Infinity)-(b.distance??Infinity)):out;
  };
  api.nearby=async(type,center,radius=3000)=>{
    await loadPlaces();const {Place,SearchNearbyRankPreference}=await google.maps.importLibrary('places');const types=TYPE_MAP[type];if(!types)throw new Error('unsupported-google-place-type');
    const raw=[];for(const primaryType of types){try{const {places}=await Place.searchNearby({fields:['id','displayName','location','formattedAddress','primaryType'],locationRestriction:{center,radius},includedPrimaryTypes:[primaryType],maxResultCount:20,rankPreference:SearchNearbyRankPreference.DISTANCE});raw.push(...(places||[]))}catch(e){console.warn('[LUMINA Google Nearby]',primaryType,e)}}
    const out=[];for(const p of raw){const lat=typeof p.location?.lat==='function'?p.location.lat():p.location?.lat,lng=typeof p.location?.lng==='function'?p.location.lng():p.location?.lng;if(!Number.isFinite(lat)||!Number.isFinite(lng))continue;const item={id:p.id||'',lat,lng,name:p.displayName||'Χωρίς όνομα',address:p.formattedAddress||'',distance:dist(center,{lat,lng}),source:'google'};const duplicate=out.some(x=>(item.id&&x.id===item.id)||(norm(x.name)===norm(item.name)&&dist({lat:x.lat,lng:x.lng},{lat:item.lat,lng:item.lng})<120));if(!duplicate)out.push(item)}
    return out.sort((a,b)=>a.distance-b.distance);
  };
  api.nearbyProgressive=async(type,center)=>{let all=[],used=RADII[0];for(const radius of RADII){const arr=await api.nearby(type,center,radius);for(const item of arr){if(!all.some(x=>(item.id&&x.id===item.id)||(norm(x.name)===norm(item.name)&&dist({lat:x.lat,lng:x.lng},{lat:item.lat,lng:item.lng})<120)))all.push(item)}all.sort((a,b)=>a.distance-b.distance);used=radius;if(all.length>=12)break}return{items:all,radius:used}};
})();