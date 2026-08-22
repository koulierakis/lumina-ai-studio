(()=>{
  const TYPE_MAP={
    restaurant:'restaurant',fast_food:'fast_food_restaurant',cafe:'cafe',bar:'bar',ice_cream:'ice_cream_shop',
    hotel:'hotel',motel:'motel',guest_house:'guest_house',camp_site:'campground',
    supermarket:'supermarket',convenience:'convenience_store',bakery:'bakery',mall:'shopping_mall',
    pharmacy:'pharmacy',hospital:'hospital',clinic:'medical_clinic',dentist:'dentist',
    fuel:'gas_station',parking:'parking',charging:'electric_vehicle_charging_station',taxi:'taxi_stand',bus:'bus_stop',
    bank:'bank',atm:'atm',police:'police',post:'post_office',gym:'gym',beach:'beach',museum:'museum',attraction:'tourist_attraction',playground:'playground'
  };
  const RADII=[1500,3000,6000,12000];
  const bypass=new WeakSet();
  let loaderPromise=null;
  const rad=v=>v*Math.PI/180;
  const dist=(a,b)=>{const R=6371e3,p1=rad(a.lat),p2=rad(b.lat),dp=rad(b.lat-a.lat),dl=rad(b.lng-a.lng),x=Math.sin(dp/2)**2+Math.cos(p1)*Math.cos(p2)*Math.sin(dl/2)**2;return 2*R*Math.atan2(Math.sqrt(x),Math.sqrt(1-x))};
  const fd=m=>m<1000?`${Math.round(m)} m`:`${(m/1000).toFixed(1)} km`;
  const esc=s=>String(s||'').replace(/[&<>'\"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','\"':'&quot;'}[c]));
  function getPos(){return new Promise((resolve,reject)=>navigator.geolocation.getCurrentPosition(p=>resolve({lat:p.coords.latitude,lng:p.coords.longitude}),reject,{enableHighAccuracy:true,maximumAge:2500,timeout:15000}))}
  function loadPlaces(){
    if(window.google?.maps?.importLibrary)return Promise.resolve();
    if(loaderPromise)return loaderPromise;
    const key=window.__LUMINA_CONFIG__?.googleMapsApiKey;
    if(!key)return Promise.reject(new Error('missing-google-key'));
    loaderPromise=new Promise((resolve,reject)=>{
      const cb='__luminaGoogleMapsReady';
      window[cb]=()=>{delete window[cb];resolve()};
      const s=document.createElement('script');
      s.async=true;s.defer=true;
      s.src=`https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(key)}&v=weekly&loading=async&libraries=places&language=el&region=GR&callback=${cb}`;
      s.onerror=()=>reject(new Error('google-maps-load-failed'));
      document.head.appendChild(s);
    });
    return loaderPromise;
  }
  async function nearby(type,center,radius){
    await loadPlaces();
    const {Place,SearchNearbyRankPreference}=await google.maps.importLibrary('places');
    const primary=TYPE_MAP[type];
    if(!primary)throw new Error('unsupported-google-place-type');
    const {places}=await Place.searchNearby({
      fields:['displayName','location','formattedAddress','primaryType'],
      locationRestriction:{center,radius},
      includedPrimaryTypes:[primary],
      maxResultCount:20,
      rankPreference:SearchNearbyRankPreference.DISTANCE
    });
    return (places||[]).map(p=>{
      const lat=typeof p.location?.lat==='function'?p.location.lat():p.location?.lat;
      const lng=typeof p.location?.lng==='function'?p.location.lng():p.location?.lng;
      if(!Number.isFinite(lat)||!Number.isFinite(lng))return null;
      const point={lat,lng};
      return {p:point,d:dist(center,point),name:p.displayName||'Χωρίς όνομα',address:p.formattedAddress||'',source:'google'};
    }).filter(Boolean).sort((a,b)=>a.d-b.d);
  }
  function render(arr,radius){
    const results=document.querySelector('#poiResults'); if(!results)return;
    const note=`<div class="poi-loading">Google Places · από το κοντινότερο · ακτίνα ${radius<1000?radius+' m':radius/1000+' km'}</div>`;
    results.innerHTML=note+arr.slice(0,40).map(x=>`<article class="poi-result"><div><strong>${esc(x.name)}</strong><span>${fd(x.d)}${x.address?' · '+esc(x.address):''}</span></div><button class="poi-route" data-lat="${x.p.lat}" data-lng="${x.p.lng}" data-name="${esc(x.name)}">Οδηγίες</button></article>`).join('');
  }
  async function runGoogle(item){
    const results=document.querySelector('#poiResults'); if(results)results.innerHTML='<div class="poi-loading">Google Places: βρίσκω τα κοντινότερα σημεία…</div>';
    const center=await getPos();
    for(const radius of RADII){
      const arr=await nearby(item.dataset.poiType,center,radius);
      if(arr.length){render(arr,radius);return true;}
    }
    return false;
  }
  document.querySelector('#poiCategories')?.addEventListener('click',async e=>{
    const item=e.target.closest('[data-poi-type]');
    if(!item||bypass.has(item)){if(item)bypass.delete(item);return}
    if(!window.__LUMINA_CONFIG__?.googleMapsApiKey)return;
    e.preventDefault();e.stopImmediatePropagation();
    try{
      const ok=await runGoogle(item);
      if(ok)return;
    }catch(err){console.warn('LUMINA Google Places fallback:',err)}
    bypass.add(item);item.click();
  },true);
})();