(() => {
  if (!window.L || !L.tileLayer || L.tileLayer.__luminaFallbackWrapped) return;
  const original = L.tileLayer.bind(L);
  const wrapped = function(url, options={}) {
    const layer = original(url, options);
    if (String(url).includes('tile.openstreetmap.org')) {
      let failures = 0;
      let switched = false;
      layer.on('tileload', () => { failures = 0; });
      layer.on('tileerror', () => {
        failures += 1;
        if (!switched && failures >= 3) {
          switched = true;
          layer.setUrl('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png');
          if (layer.options) {
            layer.options.subdomains = 'abcd';
            layer.options.attribution = '© OpenStreetMap © CARTO';
          }
          const map = window.__luminaDriveMap;
          if (map) {
            map.fire('lumina:mapfallback');
            setTimeout(() => map.invalidateSize(), 60);
          }
        }
      });
    }
    return layer;
  };
  Object.assign(wrapped, L.tileLayer);
  wrapped.__luminaFallbackWrapped = true;
  L.tileLayer = wrapped;

  // Browser-safe, keyless nationwide geocoder used when the primary public
  // OSM geocoders are unavailable/rate-limited. It deliberately does not
  // proximity-bias destination search to the current GPS position.
  const existing = window.LuminaGooglePlaces;
  if (!existing) {
    const inGreece = p => p.lat >= 34.5 && p.lat <= 42.2 && p.lng >= 19 && p.lng <= 30;
    window.LuminaGooglePlaces = {
      hasKey: () => true,
      saveKey: () => false,
      async textSearch(query) {
        const q = String(query || '').trim();
        if (q.length < 3) return [];
        const u = new URL('https://geocode-api.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates');
        u.searchParams.set('SingleLine', q);
        u.searchParams.set('f', 'json');
        u.searchParams.set('countryCode', 'GRC');
        u.searchParams.set('maxLocations', '20');
        u.searchParams.set('outFields', 'Match_addr,LongLabel,PlaceName,Type');
        const c = new AbortController();
        const t = setTimeout(() => c.abort(), 9000);
        try {
          const r = await fetch(u, {signal:c.signal, headers:{Accept:'application/json'}, cache:'no-store'});
          if (!r.ok) throw new Error(`arcgis-${r.status}`);
          const j = await r.json();
          return (j.candidates || []).map(x => ({
            lat:Number(x.location?.y), lng:Number(x.location?.x),
            name:x.attributes?.PlaceName || String(x.address || '').split(',')[0] || 'Προορισμός',
            address:x.attributes?.LongLabel || x.attributes?.Match_addr || x.address || '',
            id:`arcgis:${x.location?.x}:${x.location?.y}`,
            source:'ArcGIS World Geocoder'
          })).filter(x => Number.isFinite(x.lat) && Number.isFinite(x.lng) && inGreece(x));
        } finally { clearTimeout(t); }
      }
    };
  }

  // Remove the duplicate LUMINA word introduced by the older V48 pseudo-label.
  const brandFix = document.createElement('style');
  brandFix.id = 'lumina-v53-brand-fix';
  brandFix.textContent = '.brand h1::before{content:none!important;display:none!important}';
  document.head.appendChild(brandFix);
})();
