(() => {
  'use strict';

  const SEARCH_ENDPOINT = 'https://nominatim.openstreetmap.org/search';
  const SEARCH_DEBOUNCE_MS = 300;
  const MIN_QUERY_LENGTH = 2;
  const MAX_RESULTS = 8;

  const api = window.LuminaNameNavigation = window.LuminaNameNavigation || {
    map: null,
    searchMarker: null,
    selected: null,
    lastSearchToken: 0,
    userPosition: null,
    autoStartTimer: null
  };

  const $ = (selector) => document.querySelector(selector);
  const esc = (value = '') => String(value).replace(/[&<>"']/g, (char) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const rad = (v) => v * Math.PI / 180;
  const distanceMeters = (a, b) => {
    if (!a || !b) return null;
    const R = 6371e3;
    const p1 = rad(a.lat), p2 = rad(b.lat), dp = rad(b.lat-a.lat), dl = rad(b.lng-a.lng);
    const x = Math.sin(dp/2)**2 + Math.cos(p1)*Math.cos(p2)*Math.sin(dl/2)**2;
    return 2 * R * Math.atan2(Math.sqrt(x), Math.sqrt(1-x));
  };
  const fmtDistance = (m) => !Number.isFinite(m) ? '' : (m < 1000 ? `${Math.round(m)} m` : `${(m/1000).toFixed(1)} km`);

  function captureLeafletMap() {
    if (!window.L || typeof window.L.map !== 'function' || window.L.map.__luminaNameSearchWrapped) return;
    const originalMap = window.L.map;
    function wrappedMap(...args) {
      const map = originalMap.apply(this, args);
      api.map = map;
      window.dispatchEvent(new CustomEvent('lumina-map-ready', { detail: { map } }));
      return map;
    }
    Object.assign(wrappedMap, originalMap);
    wrappedMap.__luminaNameSearchWrapped = true;
    window.L.map = wrappedMap;
  }
  captureLeafletMap();

  function addressFor(place) {
    const a = place?.address || {};
    const street = [a.road || a.pedestrian || a.footway || a.residential, a.house_number].filter(Boolean).join(' ');
    const locality = a.city || a.town || a.village || a.municipality || a.suburb || a.county;
    const parts = [street, locality, a.state, a.postcode, a.country].filter(Boolean);
    return parts.length ? parts.join(', ') : (place?.display_name || 'Διεύθυνση μη διαθέσιμη');
  }

  function shortName(place) {
    return place?.namedetails?.['name:el'] || place?.namedetails?.name || place?.name || String(place?.display_name || 'Προορισμός').split(',')[0];
  }

  function getPosition(timeout = 5000) {
    return new Promise((resolve, reject) => {
      if (!navigator.geolocation) return reject(new Error('Geolocation unavailable'));
      navigator.geolocation.getCurrentPosition(
        (p) => {
          const pos = { lat: p.coords.latitude, lng: p.coords.longitude };
          api.userPosition = pos;
          resolve(pos);
        },
        reject,
        { enableHighAccuracy: true, maximumAge: 15000, timeout }
      );
    });
  }

  async function fetchPlaces(query, token) {
    const url = new URL(SEARCH_ENDPOINT);
    url.searchParams.set('format','jsonv2');
    url.searchParams.set('q',query);
    url.searchParams.set('limit',String(MAX_RESULTS));
    url.searchParams.set('addressdetails','1');
    url.searchParams.set('namedetails','1');
    url.searchParams.set('extratags','1');
    url.searchParams.set('dedupe','1');
    url.searchParams.set('accept-language','el,en');
    try {
      const p = await getPosition(2200);
      url.searchParams.set('viewbox', `${p.lng-1.5},${p.lat+1.2},${p.lng+1.5},${p.lat-1.2}`);
      url.searchParams.set('bounded','0');
    } catch {}
    if (token !== api.lastSearchToken) return [];
    const response = await fetch(url, { headers:{Accept:'application/json'}, cache:'no-store' });
    if (!response.ok) throw new Error(`Search HTTP ${response.status}`);
    const rows = await response.json();
    return (Array.isArray(rows) ? rows : []).filter(p => Number.isFinite(+p.lat) && Number.isFinite(+p.lon));
  }

  function ensureResultsPanel() {
    let panel = $('#nameSearchResults');
    if (panel) return panel;
    const row = $('.search-row');
    if (!row) return null;
    panel = document.createElement('section');
    panel.id = 'nameSearchResults';
    panel.className = 'name-search-results hidden pretrip-ui';
    panel.setAttribute('aria-live','polite');
    row.insertAdjacentElement('afterend', panel);
    return panel;
  }

  function showMarker(place) {
    if (!api.map || !window.L) return;
    const lat = +place.lat, lng = +place.lon;
    if (!Number.isFinite(lat) || !Number.isFinite(lng)) return;
    if (api.searchMarker) try { api.map.removeLayer(api.searchMarker); } catch {}
    api.searchMarker = window.L.marker([lat,lng]).addTo(api.map)
      .bindPopup(`<strong>${esc(shortName(place))}</strong><br>${esc(addressFor(place))}`);
    api.map.setView([lat,lng], Math.max(api.map.getZoom?.() || 15, 16), {animate:true});
    api.searchMarker.openPopup();
  }

  function renderPlaces(places, query) {
    const panel = ensureResultsPanel();
    if (!panel) return;
    if (!places.length) {
      panel.classList.remove('hidden');
      panel.innerHTML = `<div class="name-search-empty">Δεν βρέθηκε αποτέλεσμα για «${esc(query)}».</div>`;
      return;
    }
    panel.__luminaPlaces = places;
    panel.classList.remove('hidden');
    panel.innerHTML = places.map((place,index) => {
      const point = {lat:+place.lat,lng:+place.lon};
      const d = distanceMeters(api.userPosition, point);
      return `<article class="name-search-card">
        <button type="button" class="name-search-main" data-select-search="${index}">
          <strong>${esc(shortName(place))}</strong>
          <span><b>Διεύθυνση:</b> ${esc(addressFor(place))}</span>
          ${Number.isFinite(d) ? `<span><b>Απόσταση:</b> ${esc(fmtDistance(d))}</span>` : ''}
        </button>
        <button type="button" class="name-search-start" data-start-search="${index}">▶ Έναρξη</button>
      </article>`;
    }).join('');
    showMarker(places[0]);
  }

  async function searchByName(query) {
    const panel = ensureResultsPanel();
    const cleaned = String(query || '').trim();
    if (!panel) return;
    if (cleaned.length < MIN_QUERY_LENGTH) {
      panel.classList.add('hidden');
      panel.innerHTML='';
      return;
    }
    const token = ++api.lastSearchToken;
    panel.classList.remove('hidden');
    panel.innerHTML='<div class="name-search-loading">🔎 Αναζήτηση…</div>';
    try {
      const places = await fetchPlaces(cleaned, token);
      if (token === api.lastSearchToken) renderPlaces(places, cleaned);
    } catch (e) {
      console.error('[LUMINA search]', e);
      if (token === api.lastSearchToken) panel.innerHTML='<div class="name-search-empty">Η αναζήτηση δεν απάντησε. Δοκίμασε ξανά.</div>';
    }
  }

  function armBuiltInAutoStart() {
    clearTimeout(api.autoStartTimer);
    const preview = $('#routePreview');
    const start = $('#startRouteBtn');
    if (!preview || !start) return;
    let done = false;
    const trigger = () => {
      if (!done && !preview.classList.contains('hidden')) {
        done = true;
        observer.disconnect();
        start.click();
      }
    };
    const observer = new MutationObserver(trigger);
    observer.observe(preview,{attributes:true,attributeFilter:['class']});
    trigger();
    api.autoStartTimer = setTimeout(() => observer.disconnect(),15000);
  }

  function startNavigation(place) {
    api.selected = place;
    showMarker(place);
    const input = $('#destinationInput');
    const routeButton = $('#routeBtn');
    if (!input || !routeButton) return;
    input.value = place.display_name || `${shortName(place)}, ${addressFor(place)}`;
    input.dispatchEvent(new Event('change',{bubbles:true}));
    armBuiltInAutoStart();
    routeButton.click();
    ensureResultsPanel()?.classList.add('hidden');
  }

  function enhancePoiCards(root=document) {
    root.querySelectorAll?.('.poi-route').forEach(button => {
      if (button.dataset.luminaStartEnhanced) return;
      button.dataset.luminaStartEnhanced='1';
      button.textContent='▶ Έναρξη';
      button.addEventListener('click', armBuiltInAutoStart, {passive:true});
    });
  }

  function bindUI() {
    const input = $('#destinationInput');
    const routeButton = $('#routeBtn');
    const panel = ensureResultsPanel();
    if (!input || !panel) return;
    input.placeholder='Αναζήτηση με όνομα ή διεύθυνση…';
    input.setAttribute('aria-label','Αναζήτηση με όνομα ή διεύθυνση');
    if (routeButton) routeButton.textContent='Αναζήτηση';
    let timer;
    input.addEventListener('input',()=>{ clearTimeout(timer); timer=setTimeout(()=>searchByName(input.value),SEARCH_DEBOUNCE_MS); });
    document.addEventListener('click',(event)=>{
      const selectButton=event.target.closest('[data-select-search]');
      const startButton=event.target.closest('[data-start-search]');
      if (selectButton || startButton) {
        const button=selectButton || startButton;
        const index=+(selectButton ? button.dataset.selectSearch : button.dataset.startSearch);
        const place=panel.__luminaPlaces?.[index];
        if (!place) return;
        api.selected=place;
        showMarker(place);
        if (selectButton) input.value=place.display_name || shortName(place);
        else startNavigation(place);
        return;
      }
      if (!event.target.closest('.search-row') && !event.target.closest('#nameSearchResults')) panel.classList.add('hidden');
    });
    const observer=new MutationObserver(mutations=>mutations.forEach(m=>m.addedNodes.forEach(n=>{if(n.nodeType===1)enhancePoiCards(n)})));
    observer.observe(document.body,{childList:true,subtree:true});
    enhancePoiCards();
  }

  if (document.readyState==='loading') document.addEventListener('DOMContentLoaded',bindUI,{once:true});
  else bindUI();
})();
