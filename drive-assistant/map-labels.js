(() => {
  if (!window.L || !L.map || L.map.__luminaWrapped) return;

  const originalMap = L.map.bind(L);
  const wrappedMap = function (...args) {
    const map = originalMap(...args);
    window.__luminaDriveMap = map;

    map.createPane('roadLabels');
    const pane = map.getPane('roadLabels');
    pane.style.zIndex = '460';
    pane.style.pointerEvents = 'none';

    const streetLabels = L.tileLayer(
      'https://{s}.basemaps.cartocdn.com/light_only_labels/{z}/{x}/{y}{r}.png',
      {
        subdomains: 'abcd',
        minZoom: 15,
        maxZoom: 20,
        pane: 'roadLabels',
        opacity: 0.98,
        attribution: '© OpenStreetMap © CARTO'
      }
    );

    const syncLabels = () => {
      if (map.getZoom() >= 15) {
        if (!map.hasLayer(streetLabels)) streetLabels.addTo(map);
      } else if (map.hasLayer(streetLabels)) {
        map.removeLayer(streetLabels);
      }
    };

    map.on('zoomend', syncLabels);
    map.whenReady(syncLabels);
    return map;
  };

  Object.assign(wrappedMap, L.map);
  wrappedMap.__luminaWrapped = true;
  L.map = wrappedMap;
})();