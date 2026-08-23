(() => {
  'use strict';

  const NOMINATIM = 'https://nominatim.openstreetmap.org/search';
  const PHOTON = 'https://photon.komoot.io/api/';
  const SEARCH_DEBOUNCE_MS = 450;
  const MIN_QUERY_LENGTH = 3;
  const MAX_RESULTS = 10;

  const api = window.LuminaNameNavigation = window.LuminaNameNavigation || {
    map: null,
    searchMarker: null,
    selected: null,
    lastSearchToken: 0,
    userPosition: null,
    autoStartTimer: null
  };

  const $ = s => document.querySelector(s);
  const esc = (v = '') => String(v).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const norm = s => String(s || '').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLocaleLowerCase('el-GR').replace(/[^a-z0-9α-ω]+/gi,' ').trim();
  const rad = v => v * Math.PI / 180;
  const distanceMeters = (a,b) => {
    if (!a || !b) return null;
    const R=6371e3,p1=rad(a.lat),p2=rad(b.lat),dp=rad(b.lat-a.lat),dl=rad(b.lng-a.lng);
    const x=Math.sin(dp/2)**2+Math.cos(p1)*Math.cos(p2)*Math.sin(dl/2)**2;
    return 2*R*Math.atan2(Math.sqrt(x),Math.sqrt(1-x));
  };
  const fmtDistance = m => !Number.isFinite(m) ? '' : (m < 1000 ? `${Math.round(m)} m` : `${(m/1000).toFixed(1)} km`);

  function captureLeafletMap(){
    if(!window.L || typeof window.L.map !== 'function' || window.L.map.__luminaNameSearchWrapped) return;
    const original = window.L.map;
    function wrapped(...args){
      const map = original.apply(this,args);
      api.map = map;
      window.dispatchEvent(new CustomEvent('lumina-map-ready',{detail:{map}}));
      return map;
    }
    Object.assign(wrapped,original);
    wrapped.__luminaNameSearchWrapped=true;
    window.L.map=wrapped;
  }
  captureLeafletMap();

  function currentMapPosition(){
    try {
      const marker = window.__luminaCurrentUserMarker;
      const ll = marker?.getLatLng?.();
      if (Number.isFinite(ll?.lat) && Number.isFinite(ll?.lng)) {
        api.userPosition={lat:ll.lat,lng:ll.lng};
        return api.userPosition;
      }
    } catch {}
    return api.userPosition;
  }

  function getPosition(timeout=3500){
    const existing=currentMapPosition();
    if(existing) return Promise.resolve(existing);
    return new Promise((resolve,reject)=>{
      if(!navigator.geolocation) return reject(new Error('Geolocation unavailable'));
      navigator.geolocation.getCurrentPosition(p=>{
        const pos={lat:p.coords.latitude,lng:p.coords.longitude};
        api.userPosition=pos;
        resolve(pos);
      },reject,{enableHighAccuracy:true,maximumAge:15000,timeout});
    });
  }

  function addressFor(place){
    if(place.__photonAddress) return place.__photonAddress;
    const a=place?.address||{};
    const street=[a.road||a.pedestrian||a.footway||a.residential,a.house_number].filter(Boolean).join(' ');
    const locality=a.city||a.town||a.village||a.municipality||a.suburb||a.county;
    const parts=[street,locality,a.state,a.postcode,a.country].filter(Boolean);
    return parts.length?parts.join(', '):(place?.display_name||'Διεύθυνση μη διαθέσιμη');
  }

  function shortName(place){
    return place?.namedetails?.['name:el']||place?.namedetails?.name||place?.name||String(place?.display_name||'Προορισμός').split(',')[0];
  }

  async function fetchJson(url,timeout=9000){
    const controller=new AbortController();
    const timer=setTimeout(()=>controller.abort(),timeout);
    try{
      const r=await fetch(url,{headers:{Accept:'application/json'},cache:'no-store',signal:controller.signal});
      if(!r.ok) throw new Error(`HTTP ${r.status}`);
      return await r.json();
    } finally { clearTimeout(timer); }
  }

  async function nominatim(query){
    const variants=[query];
    if(!/ελλαδ|greece/i.test(query)) variants.push(`${query}, Ελλάδα`);
    let lastError=null;
    for(const q of variants){
      try{
        const url=new URL(NOMINATIM);
        url.searchParams.set('format','jsonv2');
        url.searchParams.set('q',q);
        url.searchParams.set('countrycodes','gr');
        url.searchParams.set('limit',String(MAX_RESULTS));
        url.searchParams.set('addressdetails','1');
        url.searchParams.set('namedetails','1');
        url.searchParams.set('extratags','1');
        url.searchParams.set('dedupe','1');
        url.searchParams.set('accept-language','el,en');
        const rows=await fetchJson(url.toString());
        if(Array.isArray(rows)&&rows.length) return rows.filter(p=>Number.isFinite(+p.lat)&&Number.isFinite(+p.lon));
      }catch(e){lastError=e;}
    }
    if(lastError) throw lastError;
    return [];
  }

  async function photon(query){
    const url=new URL(PHOTON);
    url.searchParams.set('q',query);
    url.searchParams.set('limit',String(MAX_RESULTS));
    url.searchParams.set('lang','el');
    const p=currentMapPosition();
    if(p){url.searchParams.set('lat',String(p.lat));url.searchParams.set('lon',String(p.lng));}
    const data=await fetchJson(url.toString());
    return (data.features||[]).map(f=>{
      const pr=f.properties||{},c=f.geometry?.coordinates||[];
      const lat=+c[1],lon=+c[0];
      if(!Number.isFinite(lat)||!Number.isFinite(lon)) return null;
      const street=[pr.street,pr.housenumber].filter(Boolean).join(' ');
      const locality=pr.city||pr.town||pr.village||pr.county||pr.state;
      const address=[street,locality,pr.state,pr.postcode,pr.country].filter(Boolean).join(', ');
      return {
        lat:String(lat),lon:String(lon),
        name:pr.name||street||locality||'Προορισμός',
        display_name:[pr.name||street,locality,pr.state,pr.country].filter(Boolean).join(', '),
        __photonAddress:address,
        __source:'Photon'
      };
    }).filter(Boolean);
  }

  function score(place,query){
    const q=norm(query),label=norm(`${shortName(place)} ${addressFor(place)} ${place.display_name||''}`);
    let s=0;
    const tokens=q.split(' ').filter(Boolean);
    for(const t of tokens) if(label.includes(t)) s+=8;
    if(label.includes(q)) s+=30;
    const qNumber=(q.match(/\b\d+[a-zα-ω]?\b/i)||[])[0];
    if(qNumber&&label.includes(qNumber)) s+=25;
    return s;
  }

  function mergeAndRank(groups,query){
    const seen=new Set(),out=[];
    for(const p of groups.flat()){
      const lat=+p.lat,lng=+p.lon;
      if(!Number.isFinite(lat)||!Number.isFinite(lng)) continue;
      const key=`${lat.toFixed(5)}|${lng.toFixed(5)}|${norm(shortName(p))}`;
      if(seen.has(key)) continue;
      seen.add(key);
      out.push(p);
    }
    out.sort((a,b)=>score(b,query)-score(a,query));
    return out.slice(0,MAX_RESULTS);
  }

  async function fetchPlaces(query,token){
    await getPosition().catch(()=>null);
    const settled=await Promise.allSettled([nominatim(query),photon(query)]);
    if(token!==api.lastSearchToken) return [];
    const ok=settled.filter(x=>x.status==='fulfilled').map(x=>x.value);
    if(!ok.length) throw (settled.find(x=>x.status==='rejected')?.reason||new Error('All search providers failed'));
    return mergeAndRank(ok,query);
  }

  function ensureResultsPanel(){
    let panel=$('#nameSearchResults');
    if(panel) return panel;
    const row=$('.search-row');
    if(!row) return null;
    panel=document.createElement('section');
    panel.id='nameSearchResults';
    panel.className='name-search-results hidden pretrip-ui';
    panel.setAttribute('aria-live','polite');
    row.insertAdjacentElement('afterend',panel);
    return panel;
  }

  function showMarker(place){
    if(!api.map||!window.L) return;
    const lat=+place.lat,lng=+place.lon;
    if(!Number.isFinite(lat)||!Number.isFinite(lng)) return;
    if(api.searchMarker) try{api.map.removeLayer(api.searchMarker)}catch{}
    api.searchMarker=window.L.marker([lat,lng]).addTo(api.map).bindPopup(`<strong>${esc(shortName(place))}</strong><br>${esc(addressFor(place))}`);
    api.map.setView([lat,lng],Math.max(api.map.getZoom?.()||15,16),{animate:true});
    api.searchMarker.openPopup();
  }

  function renderPlaces(places,query){
    const panel=ensureResultsPanel();
    if(!panel) return;
    if(!places.length){
      panel.__luminaPlaces=[];
      panel.classList.remove('hidden');
      panel.innerHTML=`<div class="name-search-empty">Δεν βρέθηκε ασφαλές αποτέλεσμα για «${esc(query)}». Πρόσθεσε πόλη ή ΤΚ.</div>`;
      return;
    }
    panel.__luminaPlaces=places;
    panel.classList.remove('hidden');
    panel.innerHTML=places.map((place,index)=>{
      const point={lat:+place.lat,lng:+place.lon};
      const d=distanceMeters(currentMapPosition(),point);
      return `<article class="name-search-card">
        <button type="button" class="name-search-main" data-select-search="${index}">
          <strong>${esc(shortName(place))}</strong>
          <span><b>Διεύθυνση:</b> ${esc(addressFor(place))}</span>
          ${Number.isFinite(d)?`<span><b>Απόσταση:</b> ${esc(fmtDistance(d))}</span>`:''}
        </button>
        <button type="button" class="name-search-start" data-start-search="${index}">▶ Έναρξη</button>
      </article>`;
    }).join('');
  }

  async function searchByName(query){
    const panel=ensureResultsPanel(),cleaned=String(query||'').trim();
    if(!panel) return;
    api.selected=null;
    if(cleaned.length<MIN_QUERY_LENGTH){panel.classList.add('hidden');panel.innerHTML='';return;}
    const token=++api.lastSearchToken;
    panel.classList.remove('hidden');
    panel.innerHTML='<div class="name-search-loading"><span class="search-spinner"></span> Αναζητώ διεύθυνση…</div>';
    try{
      const places=await fetchPlaces(cleaned,token);
      if(token===api.lastSearchToken) renderPlaces(places,cleaned);
    }catch(e){
      console.error('[LUMINA search]',e);
      if(token===api.lastSearchToken) panel.innerHTML='<div class="name-search-empty">Η υπηρεσία αναζήτησης δεν απάντησε. Δοκίμασε ξανά σε λίγα δευτερόλεπτα.</div>';
    }
  }

  function armBuiltInAutoStart(){
    clearTimeout(api.autoStartTimer);
    const preview=$('#routePreview'),start=$('#startRouteBtn');
    if(!preview||!start) return;
    let done=false;
    const trigger=()=>{if(!done&&!preview.classList.contains('hidden')){done=true;observer.disconnect();start.click();}};
    const observer=new MutationObserver(trigger);
    observer.observe(preview,{attributes:true,attributeFilter:['class']});
    trigger();
    api.autoStartTimer=setTimeout(()=>observer.disconnect(),15000);
  }

  function startNavigation(place){
    api.selected=place;
    showMarker(place);
    const input=$('#destinationInput'),routeButton=$('#routeBtn');
    if(!input||!routeButton) return;
    input.value=place.display_name||`${shortName(place)}, ${addressFor(place)}`;
    input.dispatchEvent(new Event('change',{bubbles:true}));
    ensureResultsPanel()?.classList.add('hidden');
    armBuiltInAutoStart();
    routeButton.dataset.luminaConfirmed='1';
    routeButton.click();
    delete routeButton.dataset.luminaConfirmed;
  }

  function enhancePoiCards(root=document){
    root.querySelectorAll?.('.poi-route').forEach(button=>{
      if(button.dataset.luminaStartEnhanced) return;
      button.dataset.luminaStartEnhanced='1';
      button.textContent='▶ Έναρξη';
      button.addEventListener('click',armBuiltInAutoStart,{passive:true});
    });
  }

  function bindUI(){
    const input=$('#destinationInput'),routeButton=$('#routeBtn'),panel=ensureResultsPanel();
    if(!input||!panel) return;
    input.placeholder='Αναζήτηση με όνομα ή διεύθυνση…';
    input.setAttribute('aria-label','Αναζήτηση με όνομα ή διεύθυνση');
    if(routeButton) routeButton.textContent='Αναζήτηση';
    let timer;
    input.addEventListener('input',()=>{clearTimeout(timer);timer=setTimeout(()=>searchByName(input.value),SEARCH_DEBOUNCE_MS);});
    routeButton?.addEventListener('click',event=>{
      if(routeButton.dataset.luminaConfirmed==='1') return;
      event.preventDefault();
      event.stopImmediatePropagation();
      searchByName(input.value);
    },true);
    document.addEventListener('click',event=>{
      const selectButton=event.target.closest('[data-select-search]');
      const startButton=event.target.closest('[data-start-search]');
      if(selectButton||startButton){
        const button=selectButton||startButton;
        const index=+(selectButton?button.dataset.selectSearch:button.dataset.startSearch);
        const place=panel.__luminaPlaces?.[index];
        if(!place) return;
        api.selected=place;
        showMarker(place);
        input.value=place.display_name||`${shortName(place)}, ${addressFor(place)}`;
        if(startButton) startNavigation(place);
        return;
      }
      if(!event.target.closest('.search-row')&&!event.target.closest('#nameSearchResults')) panel.classList.add('hidden');
    });
    const observer=new MutationObserver(ms=>ms.forEach(m=>m.addedNodes.forEach(n=>{if(n.nodeType===1)enhancePoiCards(n)})));
    observer.observe(document.body,{childList:true,subtree:true});
    enhancePoiCards();
  }

  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',bindUI,{once:true});
  else bindUI();
})();
