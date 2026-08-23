(() => {
  'use strict';

  const SEARCH_ENDPOINT = 'https://nominatim.openstreetmap.org/search';
  const ROUTE_ENDPOINT = 'https://router.project-osrm.org/route/v1/driving';
  const SEARCH_DEBOUNCE_MS = 320;
  const MIN_QUERY_LENGTH = 2;
  const MAX_RESULTS = 8;

  const api = window.LuminaNameNavigation = window.LuminaNameNavigation || {
    map: null,
    searchMarker: null,
    previewRoute: null,
    selected: null,
    lastSearchToken: 0,
    autoStartTimer: null
  };

  const $ = (selector) => document.querySelector(selector);
  const esc = (value = '') => String(value).replace(/[&<>"']/g, (char) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;'
  }[char]));

  function captureLeafletMap() {
    if (!window.L || typeof window.L.map !== 'function' || window.L.map.__luminaNameSearchWrapped) return;
    const originalMap = window.L.map;
    function wrappedMap(...args) {
      const map = originalMap.apply(this, args);
      api.map = map;
      return map;
    }
    Object.assign(wrappedMap, originalMap);
    wrappedMap.__luminaNameSearchWrapped = true;
    window.L.map = wrappedMap;
  }

  captureLeafletMap();

  function setNotice(message) {
    const notice = $('#notice');
    if (notice && message) notice.textContent = message;
  }

  function addressFor(place) {
    const a = place?.address || {};
    const street = [a.road || a.pedestrian || a.footway || a.residential, a.house_number]
      .filter(Boolean)
      .join(' ');
    const locality = a.city || a.town || a.village || a.municipality || a.suburb || a.county;
    const parts = [street, locality, a.state, a.postcode, a.country].filter(Boolean);
    return parts.length ? parts.join(', ') : (place?.display_name || 'Διεύθυνση μη διαθέσιμη');
  }

  function shortName(place) {
    return place?.namedetails?.name ||
      place?.namedetails?.['name:el'] ||
      place?.name ||
      String(place?.display_name || 'Προορισμός').split(',')[0];
  }

  function getPosition(timeout = 5000) {
    return new Promise((resolve, reject) => {
      if (!navigator.geolocation) {
        reject(new Error('Geolocation API unavailable'));
        return;
      }
      navigator.geolocation.getCurrentPosition(
        (p) => resolve({ lat: p.coords.latitude, lng: p.coords.longitude }),
        reject,
        { enableHighAccuracy: true, maximumAge: 15000, timeout }
      );
    });
  }

  async function buildSearchUrl(query) {
    const url = new URL(SEARCH_ENDPOINT);
    url.searchParams.set('format', 'jsonv2');
    url.searchParams.set('q', query);
    url.searchParams.set('limit', String(MAX_RESULTS));
    url.searchParams.set('addressdetails', '1');
    url.searchParams.set('namedetails', '1');
    url.searchParams.set('extratags', '1');
    url.searchParams.set('dedupe', '1');
    url.searchParams.set('accept-language', 'el,en');

    try {
      const pos = await getPosition(2200);
      const latDelta = 1.2;
      const lngDelta = 1.5;
      url.searchParams.set(
        'viewbox',
        `${pos.lng - lngDelta},${pos.lat + latDelta},${pos.lng + lngDelta},${pos.lat - latDelta}`
      );
      url.searchParams.set('bounded', '0');
    } catch {
      // Search still works without location; it just cannot bias results toward the user.
    }
    return url;
  }

  async function fetchPlaces(query, token) {
    const url = await buildSearchUrl(query);
    if (token !== api.lastSearchToken) return [];
    const response = await fetch(url.toString(), {
      headers: { Accept: 'application/json' },
      cache: 'no-store'
    });
    if (!response.ok) throw new Error(`Search HTTP ${response.status}`);
    const data = await response.json();
    return (Array.isArray(data) ? data : []).filter((place) =>
      Number.isFinite(Number(place.lat)) && Number.isFinite(Number(place.lon))
    );
  }

  function ensureResultsPanel() {
    let panel = $('#nameSearchResults');
    if (panel) return panel;
    const row = $('.search-row');
    if (!row) return null;
    panel = document.createElement('section');
    panel.id = 'nameSearchResults';
    panel.className = 'name-search-results hidden pretrip-ui';
    panel.setAttribute('aria-live', 'polite');
    row.insertAdjacentElement('afterend', panel);
    return panel;
  }

  function showMarker(place, openPopup = true) {
    if (!api.map || !window.L) return;
    const lat = Number(place.lat);
    const lng = Number(place.lon);
    if (!Number.isFinite(lat) || !Number.isFinite(lng)) return;

    if (api.searchMarker) {
      try { api.map.removeLayer(api.searchMarker); } catch {}
    }

    api.searchMarker = window.L.circleMarker([lat, lng], {
      radius: 11,
      weight: 4,
      color: '#ffffff',
      fillColor: '#1597e5',
      fillOpacity: 1
    }).addTo(api.map);

    api.searchMarker.bindPopup(
      `<strong>${esc(shortName(place))}</strong><br><span>${esc(addressFor(place))}</span>`
    );
    api.map.setView([lat, lng], Math.max(api.map.getZoom?.() || 15, 16), { animate: true });
    if (openPopup) api.searchMarker.openPopup();
  }

  function renderPlaces(places, query) {
    const panel = ensureResultsPanel();
    if (!panel) return;

    if (!places.length) {
      panel.classList.remove('hidden');
      panel.innerHTML = `<div class="name-search-empty">Δεν βρέθηκε αποτέλεσμα για «${esc(query)}».</div>`;
      return;
    }

    panel.classList.remove('hidden');
    panel.innerHTML = places.map((place, index) => {
      const name = shortName(place);
      const address = addressFor(place);
      return `<article class="name-search-card" data-search-index="${index}">
        <button type="button" class="name-search-main" data-select-search="${index}">
          <strong>${esc(name)}</strong>
          <span><b>Διεύθυνση:</b> ${esc(address)}</span>
        </button>
        <button type="button" class="name-search-start" data-start-search="${index}">▶ Έναρξη</button>
      </article>`;
    }).join('');

    panel.__luminaPlaces = places;

    // Show the best match on the map immediately.
    showMarker(places[0], false);
  }

  async function searchByName(query) {
    const panel = ensureResultsPanel();
    if (!panel) return;
    const cleaned = String(query || '').trim();

    if (cleaned.length < MIN_QUERY_LENGTH) {
      panel.classList.add('hidden');
      panel.innerHTML = '';
      return;
    }

    const token = ++api.lastSearchToken;
    panel.classList.remove('hidden');
    panel.innerHTML = '<div class="name-search-loading">🔎 Αναζήτηση καταστήματος…</div>';

    try {
      const places = await fetchPlaces(cleaned, token);
      if (token !== api.lastSearchToken) return;
      renderPlaces(places, cleaned);
    } catch (error) {
      console.error('[LUMINA name search] search failed', error);
      if (token !== api.lastSearchToken) return;
      panel.innerHTML = '<div class="name-search-empty">Η αναζήτηση δεν απάντησε. Έλεγξε τη σύνδεση και ξαναδοκίμασε.</div>';
    }
  }

  function armBuiltInAutoStart() {
    clearTimeout(api.autoStartTimer);
    const preview = $('#routePreview');
    const startButton = $('#startRouteBtn');
    if (!preview || !startButton) return;

    let finished = false;
    const startWhenReady = () => {
      if (finished || preview.classList.contains('hidden')) return;
      finished = true;
      observer.disconnect();
      startButton.click();
    };

    const observer = new MutationObserver(startWhenReady);
    observer.observe(preview, { attributes: true, attributeFilter: ['class'] });
    startWhenReady();

    api.autoStartTimer = setTimeout(() => {
      observer.disconnect();
      if (!finished) setNotice('Η διαδρομή σχεδιάστηκε. Αν δεν ξεκίνησε αυτόματα, πάτησε «Έναρξη».');
    }, 15000);
  }

  async function drawImmediateRoute(place) {
    if (!api.map || !window.L) return null;

    const origin = await getPosition(7000);
    const destination = { lat: Number(place.lat), lng: Number(place.lon) };
    const url = `${ROUTE_ENDPOINT}/${origin.lng},${origin.lat};${destination.lng},${destination.lat}` +
      '?overview=full&geometries=geojson&steps=true&alternatives=false';

    const response = await fetch(url, { cache: 'no-store' });
    if (!response.ok) throw new Error(`Route HTTP ${response.status}`);
    const data = await response.json();
    const route = data?.routes?.[0];
    if (!route?.geometry?.coordinates?.length) throw new Error('No route geometry');

    if (api.previewRoute) {
      try { api.map.removeLayer(api.previewRoute); } catch {}
    }

    const latLngs = route.geometry.coordinates.map(([lng, lat]) => [lat, lng]);
    api.previewRoute = window.L.polyline(latLngs, {
      weight: 6,
      opacity: 0.9,
      lineCap: 'round',
      lineJoin: 'round'
    }).addTo(api.map);

    const group = window.L.featureGroup([api.previewRoute, api.searchMarker].filter(Boolean));
    try { api.map.fitBounds(group.getBounds().pad(0.12)); } catch {}

    return route;
  }

  async function startNavigation(place) {
    api.selected = place;
    showMarker(place, true);
    setNotice(`Ξεκινώ πλοήγηση προς ${shortName(place)}…`);

    // Draw the route immediately, independently of the existing route preview UI.
    try {
      await drawImmediateRoute(place);
    } catch (error) {
      console.warn('[LUMINA name search] immediate route preview failed', error);
    }

    // Reuse the existing LUMINA routing/guidance engine so voice maneuvers,
    // rerouting, speed awareness and navigation cockpit remain intact.
    const input = $('#destinationInput');
    const routeButton = $('#routeBtn');
    if (!input || !routeButton) {
      setNotice('Ο προορισμός βρέθηκε, αλλά ο μηχανισμός πλοήγησης δεν είναι διαθέσιμος.');
      return;
    }

    input.value = place.display_name || `${shortName(place)}, ${addressFor(place)}`;
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));

    armBuiltInAutoStart();
    routeButton.click();

    const panel = ensureResultsPanel();
    panel?.classList.add('hidden');
  }

  function enhancePoiCards(root = document) {
    root.querySelectorAll?.('.poi-result').forEach((card) => {
      const button = card.querySelector('.poi-route');
      const details = card.querySelector('span');
      if (button && !button.dataset.luminaStartEnhanced) {
        button.dataset.luminaStartEnhanced = '1';
        button.textContent = '▶ Έναρξη';
        button.addEventListener('click', () => armBuiltInAutoStart(), { passive: true });
      }
      if (details && !details.dataset.luminaAddressEnhanced) {
        const text = details.textContent || '';
        const parts = text.split(' · ');
        if (parts.length > 1 && !text.includes('Διεύθυνση:')) {
          details.textContent = `${parts.shift()} · Διεύθυνση: ${parts.join(' · ')}`;
        }
        details.dataset.luminaAddressEnhanced = '1';
      }
    });
  }

  function bindUI() {
    const input = $('#destinationInput');
    const routeButton = $('#routeBtn');
    const panel = ensureResultsPanel();
    if (!input || !panel) return;

    input.placeholder = 'Αναζήτηση με όνομα ή διεύθυνση…';
    input.setAttribute('aria-label', 'Αναζήτηση καταστήματος ή προορισμού με όνομα');
    if (routeButton) routeButton.textContent = 'Αναζήτηση';

    let timer = null;
    input.addEventListener('input', () => {
      clearTimeout(timer);
      timer = setTimeout(() => searchByName(input.value), SEARCH_DEBOUNCE_MS);
    });

    input.addEventListener('focus', () => {
      if (input.value.trim().length >= MIN_QUERY_LENGTH && panel.innerHTML.trim()) {
        panel.classList.remove('hidden');
      }
    });

    document.addEventListener('click', (event) => {
      const selectButton = event.target.closest('[data-select-search]');
      const startButton = event.target.closest('[data-start-search]');

      if (selectButton || startButton) {
        const index = Number((selectButton || startButton).dataset[
          selectButton ? 'selectSearch' : 'startSearch'
        ]);
        const place = panel.__luminaPlaces?.[index];
        if (!place) return;

        api.selected = place;
        showMarker(place, true);

        if (selectButton) {
          input.value = place.display_name || shortName(place);
          return;
        }

        startNavigation(place);
        return;
      }

      if (!event.target.closest('.search-row') && !event.target.closest('#nameSearchResults')) {
        panel.classList.add('hidden');
      }
    });

    const observer = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        for (const node of mutation.addedNodes) {
          if (node.nodeType === 1) enhancePoiCards(node);
        }
      }
    });
    observer.observe(document.body, { childList: true, subtree: true });
    enhancePoiCards();

    window.addEventListener('lumina-map-ready', (event) => {
      if (event.detail?.map) api.map = event.detail.map;
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bindUI, { once: true });
  } else {
    bindUI();
  }
})();
