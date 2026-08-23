(()=>{
  'use strict';

  const $=s=>document.querySelector(s);
  const RADIUS_M=6000;
  const PRIMARY_OVERPASS='https://overpass-api.de/api/interpreter';
  const FALLBACK_OVERPASS=['https://overpass.kumi.systems/api/interpreter','https://overpass.nchc.org.tw/api/interpreter'];
  const NOMINATIM='https://nominatim.openstreetmap.org/search';

  const CATEGORIES={
    stay:{label:'Διαμονή',items:[['hotel','🏨 Ξενοδοχεία','tourism','hotel'],['motel','🛏️ Μοτέλ','tourism','motel'],['guest_house','🏡 Ξενώνες','tourism','guest_house'],['camp_site','⛺ Camping','tourism','camp_site']]},
    food:{label:'Φαγητό & Ποτό',items:[['restaurant','🍽️ Εστιατόρια','amenity','restaurant'],['fast_food','🍔 Fast food / Σουβλάκι','amenity','fast_food'],['cafe','☕ Καφέ','amenity','cafe'],['bar','🍸 Bar','amenity','bar'],['ice_cream','🍦 Παγωτό','amenity','ice_cream']]},
    shopping:{label:'Αγορές',items:[['supermarket','🛒 Supermarket','shop','supermarket'],['convenience','🥤 Mini market','shop','convenience'],['bakery','🥖 Φούρνοι','shop','bakery'],['mall','🏬 Εμπορικά κέντρα','shop','mall']]},
    health:{label:'Υγεία',items:[['pharmacy','💊 Φαρμακεία','amenity','pharmacy'],['hospital','🏥 Νοσοκομεία','amenity','hospital'],['clinic','🩺 Κλινικές','amenity','clinic'],['dentist','🦷 Οδοντίατροι','amenity','dentist']]},
    mobility:{label:'Μετακίνηση',items:[['fuel','⛽ Βενζινάδικα','amenity','fuel'],['parking','🅿️ Parking','amenity','parking'],['charging','⚡ Φόρτιση EV','amenity','charging_station'],['taxi','🚕 Taxi','amenity','taxi'],['bus','🚌 Στάσεις λεωφορείου','highway','bus_stop']]},
    services:{label:'Υπηρεσίες',items:[['bank','🏦 Τράπεζες','amenity','bank'],['atm','💶 ATM','amenity','atm'],['police','👮 Αστυνομία','amenity','police'],['post','📮 Ταχυδρομεία','amenity','post_office']]},
    leisure:{label:'Αναψυχή',items:[['gym','🏋️ Γυμναστήρια','leisure','fitness_centre'],['beach','🏖️ Παραλίες','natural','beach'],['museum','🏛️ Μουσεία','tourism','museum'],['attraction','📸 Αξιοθέατα','tourism','attraction'],['playground','🛝 Παιδικές χαρές','leisure','playground']]}
  };

  const EXTRA_TAGS={bar:[['amenity','bar'],['amenity','pub']],ice_cream:[['amenity','ice_cream'],['shop','ice_cream']]};
  const SEARCH_TERMS={restaurant:'restaurant',fast_food:'fast food',cafe:'cafe',bar:'bar',ice_cream:'ice cream',hotel:'hotel',motel:'motel',guest_house:'guest house',camp_site:'camping',supermarket:'supermarket',convenience:'mini market',bakery:'bakery',mall:'shopping mall',pharmacy:'pharmacy',hospital:'hospital',clinic:'clinic',dentist:'dentist',fuel:'fuel',parking:'parking',charging:'charging station',taxi:'taxi',bus:'bus stop',bank:'bank',atm:'atm',police:'police',post:'post office',gym:'gym',beach:'beach',museum:'museum',attraction:'attraction',playground:'playground'};

  const drawer=$('#poiDrawer'),cats=$('#poiCategories'),results=$('#poiResults'),title=$('#poiTitle'),back=$('#poiBackBtn');
  let lastOrigin=null;

  const esc=s=>String(s||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const norm=s=>String(s||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLocaleLowerCase('el-GR').replace(/[^a-z0-9α-ω]+/gi,' ').trim();
  const rad=v=>v*Math.PI/180;
  const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));

  function distanceMeters(a,b){const R=6371e3,p1=rad(a.lat),p2=rad(b.lat),dp=rad(b.lat-a.lat),dl=rad(b.lng-a.lng),x=Math.sin(dp/2)**2+Math.cos(p1)*Math.cos(p2)*Math.sin(dl/2)**2;return 2*R*Math.atan2(Math.sqrt(x),Math.sqrt(1-x))}
  const distanceKm=m=>`${(m/1000).toFixed(m<1000?2:1)} km`;

  function open(){drawer?.classList.remove('hidden');renderCategories()}
  function close(){drawer?.classList.add('hidden')}
  function renderCategories(){if(!title||!back||!cats||!results)return;title.textContent='Σημεία ενδιαφέροντος';back.classList.add('hidden');results.innerHTML='';cats.innerHTML=Object.entries(CATEGORIES).map(([key,group])=>`<button class="poi-category" data-poi-group="${key}"><strong>${group.label}</strong><span>${group.items.length} κατηγορίες</span></button>`).join('')}
  function renderGroup(key){const group=CATEGORIES[key];if(!group||!title||!back||!cats||!results)return;title.textContent=group.label;back.classList.remove('hidden');cats.innerHTML=group.items.map(item=>`<button class="poi-item" data-poi-type="${item[0]}" data-k="${item[2]}" data-v="${item[3]}">${item[1]}</button>`).join('');results.innerHTML=''}

  function getLivePosition(){
    return new Promise((resolve,reject)=>{
      if(!navigator.geolocation){
        const error=new Error('Geolocation API unavailable');
        error.kind='gps-unavailable';
        console.error('[LUMINA Nearby] Geolocation unavailable',error);
        reject(error);
        return;
      }
      navigator.geolocation.getCurrentPosition(
        position=>{
          const lat=Number(position.coords.latitude),lng=Number(position.coords.longitude);
          if(!Number.isFinite(lat)||!Number.isFinite(lng)){
            const error=new Error('Invalid GPS coordinates');
            error.kind='gps-invalid';
            console.error('[LUMINA Nearby] Invalid GPS coordinates',position.coords);
            reject(error);
            return;
          }
          resolve({lat,lng,accuracy:Number(position.coords.accuracy)||null});
        },
        error=>{
          console.error('[LUMINA Nearby] GPS error', {code:error?.code,message:error?.message});
          reject(error);
        },
        {enableHighAccuracy:true,timeout:5000,maximumAge:0}
      );
    });
  }

  function tagsFor(type,k,v){return EXTRA_TAGS[type]||[[k,v]]}
  function buildOverpassQuery(type,k,v,origin){
    const clauses=[];
    for(const [tagKey,tagValue] of tagsFor(type,k,v))for(const element of ['node','way','relation'])clauses.push(`${element}(around:${RADIUS_M},${origin.lat},${origin.lng})[\"${tagKey}\"=\"${tagValue}\"];`);
    return `[out:json][timeout:18];(${clauses.join('')});out center tags;`;
  }

  async function fetchJson(url,{timeout=10000,...options}={}){
    const controller=new AbortController();
    const timer=setTimeout(()=>controller.abort(),timeout);
    try{
      const response=await fetch(url,{...options,signal:controller.signal,cache:'no-store'});
      if(!response.ok)throw new Error(`HTTP ${response.status}`);
      return await response.json();
    }finally{clearTimeout(timer)}
  }

  async function fetchOverpassEndpoint(endpoint,query){
    const url=`${endpoint}?data=${encodeURIComponent(query)}`;
    return fetchJson(url,{timeout:11000,headers:{Accept:'application/json'},mode:'cors'});
  }

  async function fetchOverpass(query){
    const endpoints=[PRIMARY_OVERPASS,...FALLBACK_OVERPASS];
    let lastError=null;
    for(const endpoint of endpoints){
      for(let attempt=1;attempt<=2;attempt++){
        try{return await fetchOverpassEndpoint(endpoint,query)}
        catch(error){
          lastError=error;
          console.error(`[LUMINA Nearby] Overpass ${endpoint} attempt ${attempt}/2 failed`,error);
          if(attempt===1)await delay(450);
        }
      }
    }
    const error=lastError||new Error('All Overpass endpoints failed');
    error.kind='overpass-failed';
    throw error;
  }

  function pointFor(element){if(Number.isFinite(element.lat)&&Number.isFinite(element.lon))return{lat:element.lat,lng:element.lon};if(Number.isFinite(element.center?.lat)&&Number.isFinite(element.center?.lon))return{lat:element.center.lat,lng:element.center.lon};return null}
  function areaLabel(tags){const street=[tags['addr:street'],tags['addr:housenumber']].filter(Boolean).join(' '),area=tags['addr:suburb']||tags['addr:place']||tags['addr:city']||tags['addr:town']||tags['addr:village']||tags['is_in:city']||tags['is_in']||'';return[street,area].filter(Boolean).join(' · ')||'Κοντινή περιοχή'}
  function categoryMatches(type,k,v,tags){return tagsFor(type,k,v).some(([tagKey,tagValue])=>tags?.[tagKey]===tagValue)}

  function dedupe(items){
    const unique=[];
    for(const item of items.sort((a,b)=>a.distance-b.distance)){
      const duplicate=unique.some(existing=>norm(existing.name)===norm(item.name)&&distanceMeters(existing.point,item.point)<120);
      if(!duplicate)unique.push(item);
    }
    return unique;
  }

  function mapOverpassElements(data,type,k,v,origin){
    const raw=[],seenOsmIds=new Set();
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
      raw.push({name,point,distance,area:areaLabel(tags),source:'OpenStreetMap'});
    }
    return dedupe(raw);
  }

  function viewbox(origin){
    const latDelta=RADIUS_M/111320;
    const lonDelta=RADIUS_M/(111320*Math.max(.3,Math.cos(rad(origin.lat))));
    return `${origin.lng-lonDelta},${origin.lat+latDelta},${origin.lng+lonDelta},${origin.lat-latDelta}`;
  }

  async function fetchNominatimFallback(type,origin){
    const term=SEARCH_TERMS[type]||type;
    const url=new URL(NOMINATIM);
    url.searchParams.set('format','jsonv2');
    url.searchParams.set('q',term);
    url.searchParams.set('countrycodes','gr');
    url.searchParams.set('limit','50');
    url.searchParams.set('addressdetails','1');
    url.searchParams.set('bounded','1');
    url.searchParams.set('viewbox',viewbox(origin));
    url.searchParams.set('accept-language','el');
    const data=await fetchJson(url.toString(),{timeout:9000,headers:{Accept:'application/json'}});
    const items=[];
    for(const entry of data||[]){
      const point={lat:Number(entry.lat),lng:Number(entry.lon)};
      if(!Number.isFinite(point.lat)||!Number.isFinite(point.lng))continue;
      const distance=distanceMeters(origin,point);
      if(distance>RADIUS_M)continue;
      const name=entry.namedetails?.name||entry.name||String(entry.display_name||'').split(',')[0];
      if(!name)continue;
      const address=entry.address||{};
      const area=[address.road,address.house_number,address.village||address.town||address.city||address.municipality].filter(Boolean).join(' · ')||'Κοντινή περιοχή';
      items.push({name,point,distance,area,source:'Nominatim'});
    }
    return dedupe(items);
  }

  function renderResults(items,sourceLabel='Ζωντανά αποτελέσματα'){
    if(!results)return;
    if(!items.length){results.innerHTML='<div class="poi-loading">Δεν βρέθηκαν καταστήματα κοντά σας. Δοκιμάστε να αυξήσετε την ακτίνα.</div>';return}
    results.innerHTML=`<div class="poi-loading">${sourceLabel} έως 6 km από το GPS σας.</div>${items.slice(0,60).map(item=>`<article class="poi-result"><div><strong>${esc(item.name)}</strong><span>${distanceKm(item.distance)} · ${esc(item.area)}</span></div><button type="button" class="poi-route" data-lat="${item.point.lat}" data-lng="${item.point.lng}">Οδηγίες</button></article>`).join('')}`;
  }

  async function search(type,k,v){
    if(!results)return;
    results.innerHTML='<div class="poi-loading">⏳ Παίρνω την τρέχουσα θέση GPS και αναζητώ ζωντανά…</div>';
    let origin;
    try{
      origin=await getLivePosition();
      lastOrigin=origin;
    }catch(error){
      const msg=error?.code===1?'Χρειάζεται άδεια τοποθεσίας για να βρω κοντινά σημεία.':error?.code===3?'Το GPS δεν απάντησε μέσα σε 5 δευτερόλεπτα. Δοκιμάστε ξανά.':'Δεν μπόρεσα να πάρω έγκυρη θέση GPS.';
      results.innerHTML=`<div class="poi-loading">${msg}</div>`;
      return;
    }

    const query=buildOverpassQuery(type,k,v,origin);
    try{
      const data=await fetchOverpass(query);
      renderResults(mapOverpassElements(data,type,k,v,origin));
      return;
    }catch(overpassError){
      console.error('[LUMINA Nearby] Overpass exhausted, switching to live Nominatim fallback',overpassError);
    }

    try{
      const fallbackItems=await fetchNominatimFallback(type,origin);
      renderResults(fallbackItems,'Εναλλακτικά ζωντανά αποτελέσματα');
    }catch(fallbackError){
      console.error('[LUMINA Nearby] All live providers failed',fallbackError);
      results.innerHTML='<div class="poi-loading">Οι δημόσιες υπηρεσίες κοντινών σημείων δεν απάντησαν αυτή τη στιγμή. Η θέση GPS λήφθηκε κανονικά· δοκιμάστε ξανά σε λίγο.</div>';
    }
  }

  function openGoogleDirections(button){const lat=Number(button.dataset.lat),lng=Number(button.dataset.lng);if(!lastOrigin||!Number.isFinite(lat)||!Number.isFinite(lng))return;const url=new URL('https://www.google.com/maps/dir/');url.searchParams.set('api','1');url.searchParams.set('origin',`${lastOrigin.lat},${lastOrigin.lng}`);url.searchParams.set('destination',`${lat},${lng}`);url.searchParams.set('travelmode','driving');window.open(url.toString(),'_blank','noopener,noreferrer')}

  $('#poiOpenBtn')?.addEventListener('click',open);
  $('#poiCloseBtn')?.addEventListener('click',close);
  back?.addEventListener('click',renderCategories);
  cats?.addEventListener('click',event=>{const group=event.target.closest('[data-poi-group]');if(group)return renderGroup(group.dataset.poiGroup);const item=event.target.closest('[data-k]');if(item)search(item.dataset.poiType,item.dataset.k,item.dataset.v)});
  results?.addEventListener('click',event=>{const button=event.target.closest('.poi-route');if(!button)return;event.preventDefault();openGoogleDirections(button)},true);
})();