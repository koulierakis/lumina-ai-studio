(()=>{
  'use strict';
  const API='https://api.mapbox.com/search/searchbox/v1';
  const CATEGORY={
    restaurant:'restaurant',fast_food:'fast_food',cafe:'coffee',bar:'bar',ice_cream:'ice_cream',bakery:'bakery',
    hotel:'hotel',motel:'motel',guest_house:'guest_house',camp_site:'campground',
    supermarket:'supermarket',convenience:'convenience_store',mall:'shopping_mall',
    pharmacy:'pharmacy',hospital:'hospital',clinic:'clinic',dentist:'dentist',
    fuel:'gas_station',parking:'parking',charging:'charging_station',taxi:'taxi',bus:'bus_station',
    bank:'bank',atm:'atm',police:'police',post:'post_office',gym:'fitness',beach:'beach',museum:'museum',attraction:'tourist_attraction',playground:'playground'
  };
  const FALLBACK_Q={fast_food:'fast food',guest_house:'guest house',camp_site:'camping',convenience:'mini market',mall:'shopping mall',clinic:'medical clinic',fuel:'gas station',charging:'EV charging',bus:'bus stop',post:'post office',gym:'gym',attraction:'tourist attraction'};
  const api=window.LuminaMapboxPlaces=window.LuminaMapboxPlaces||{};
  const rad=v=>v*Math.PI/180;
  const dist=(a,b)=>{const R=6371e3,p1=rad(a.lat),p2=rad(b.lat),dp=rad(b.lat-a.lat),dl=rad(b.lng-a.lng),x=Math.sin(dp/2)**2+Math.cos(p1)*Math.cos(p2)*Math.sin(dl/2)**2;return 2*R*Math.atan2(Math.sqrt(x),Math.sqrt(1-x))};
  function key(){return String(window.__LUMINA_CONFIG__?.mapboxAccessToken||localStorage.getItem('lumina-mapbox-public-token')||'').trim()}
  api.hasKey=()=>!!key();
  api.saveKey=value=>{const v=String(value||'').trim();if(v)localStorage.setItem('lumina-mapbox-public-token',v);else localStorage.removeItem('lumina-mapbox-public-token');return!!v};
  function area(p){return p.full_address||p.place_formatted||p.address||p.context?.place?.name||p.context?.locality?.name||p.context?.neighborhood?.name||'Κοντινή περιοχή'}
  function parse(data,center){const out=[];for(const f of data?.features||[]){const c=f.geometry?.coordinates||[],lng=+c[0],lat=+c[1],p=f.properties||{};if(!Number.isFinite(lat)||!Number.isFinite(lng)||!p.name)continue;out.push({id:p.mapbox_id||f.id||'',name:p.name,lat,lng,address:area(p),distance:dist(center,{lat,lng}),source:'mapbox',categories:p.poi_category_ids||[]})}return out.sort((a,b)=>a.distance-b.distance)}
  async function get(url,timeout=8500){const c=new AbortController(),t=setTimeout(()=>c.abort(),timeout);try{const r=await fetch(url,{cache:'no-store',signal:c.signal,headers:{Accept:'application/json'}});if(!r.ok)throw new Error(`mapbox-${r.status}`);return await r.json()}finally{clearTimeout(t)}}
  async function category(type,center){const token=key();if(!token)throw new Error('missing-mapbox-token');const id=CATEGORY[type]||type;const u=new URL(`${API}/category/${encodeURIComponent(id)}`);u.searchParams.set('access_token',token);u.searchParams.set('language','el');u.searchParams.set('limit','25');u.searchParams.set('proximity',`${center.lng},${center.lat}`);u.searchParams.set('country','GR');u.searchParams.set('types','poi');return parse(await get(u),center)}
  async function forward(type,center){const token=key();if(!token)throw new Error('missing-mapbox-token');const q=FALLBACK_Q[type]||String(type||'').replaceAll('_',' ');const u=new URL(`${API}/forward`);u.searchParams.set('q',q);u.searchParams.set('access_token',token);u.searchParams.set('language','el');u.searchParams.set('limit','10');u.searchParams.set('proximity',`${center.lng},${center.lat}`);u.searchParams.set('country','GR');u.searchParams.set('types','poi');return parse(await get(u),center)}
  api.nearby=async(type,center)=>{try{const items=await category(type,center);if(items.length)return{items,mode:'category'}}catch(e){console.warn('[LUMINA Mapbox category]',type,e)}const items=await forward(type,center);return{items,mode:'forward'}};
})();
