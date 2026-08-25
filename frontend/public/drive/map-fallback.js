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
})();
