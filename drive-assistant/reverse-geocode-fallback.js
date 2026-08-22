(()=>{
  const roadEl=()=>document.getElementById('roadName');
  const navRoadEl=()=>document.getElementById('navRoad');
  let lastAt=0,lastKey='';
  const setRoad=name=>{if(!name)return;const a=roadEl(),b=navRoadEl();if(a)a.textContent=name;if(b)b.textContent=name;};
  async function nominatim(lat,lng){
    const u=new URL('https://nominatim.openstreetmap.org/reverse');
    u.searchParams.set('format','jsonv2');u.searchParams.set('lat',lat);u.searchParams.set('lon',lng);u.searchParams.set('zoom','18');u.searchParams.set('addressdetails','1');u.searchParams.set('accept-language','el');
    const r=await fetch(u,{headers:{Accept:'application/json'}});if(!r.ok)throw new Error('nominatim');
    const j=await r.json(),a=j.address||{};
    return a.road||a.pedestrian||a.residential||a.footway||a.path||a.neighbourhood||a.suburb||j.name||j.display_name?.split(',')[0]||'';
  }
  async function photon(lat,lng){
    const u=new URL('https://photon.komoot.io/reverse');u.searchParams.set('lat',lat);u.searchParams.set('lon',lng);u.searchParams.set('lang','el');
    const r=await fetch(u,{headers:{Accept:'application/json'}});if(!r.ok)throw new Error('photon');
    const j=await r.json(),p=j.features?.[0]?.properties||{};
    return p.street||p.name||p.district||p.city||p.town||p.village||'';
  }
  async function update(lat,lng){
    const key=`${lat.toFixed(4)},${lng.toFixed(4)}`;if(key===lastKey&&Date.now()-lastAt<30000)return;lastKey=key;lastAt=Date.now();
    try{const n=await nominatim(lat,lng);if(n)return setRoad(n);}catch{}
    try{const n=await photon(lat,lng);if(n)return setRoad(n);}catch{}
  }
  if(!navigator.geolocation)return;
  navigator.geolocation.watchPosition(p=>update(p.coords.latitude,p.coords.longitude),()=>{}, {enableHighAccuracy:true,maximumAge:5000,timeout:15000});
})();