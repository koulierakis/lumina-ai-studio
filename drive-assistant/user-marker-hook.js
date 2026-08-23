(() => {
  if (!window.L || !L.circleMarker || L.circleMarker.__luminaWrapped) return;
  const original = L.circleMarker.bind(L);
  const sync = (latlng) => {
    const lat = Number(Array.isArray(latlng) ? latlng[0] : latlng?.lat);
    const lng = Number(Array.isArray(latlng) ? latlng[1] : latlng?.lng);
    if (!Number.isFinite(lat) || !Number.isFinite(lng) || !window.LuminaGPS) return;
    const previous = window.LuminaGPS.lastFix || {};
    window.LuminaGPS.lastFix = { ...previous, lat, lng, timestamp: Date.now(), receivedAt: Date.now(), source: 'active-map' };
  };
  const wrapped = function (...args) {
    const marker = original(...args);
    const options = args[1] || {};
    if (options.fillColor === '#58ddd1' && Number(options.radius) === 9) {
      window.__luminaCurrentUserMarker = marker;
      sync(args[0]);
      const originalSetLatLng = marker.setLatLng.bind(marker);
      marker.setLatLng = function (latlng) {
        const result = originalSetLatLng(latlng);
        sync(latlng);
        return result;
      };
    }
    return marker;
  };
  wrapped.__luminaWrapped = true;
  L.circleMarker = wrapped;
})();