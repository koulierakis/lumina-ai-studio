(() => {
  if (!window.L || !L.map || L.map.__luminaWrapped) return;

  const originalMap = L.map.bind(L);
  const wrappedMap = function (...args) {
    const map = originalMap(...args);
    window.__luminaDriveMap = map;

    map.createPane('roadNames');
    const pane = map.getPane('roadNames');
    pane.style.zIndex = '470';
    pane.style.pointerEvents = 'none';

    const labelsLayer = L.layerGroup([], { pane: 'roadNames' }).addTo(map);
    let lastKey = '';
    let loading = false;
    let timer = null;

    const ensureStyle = () => {
      if (document.getElementById('lumina-road-label-style')) return;
      const style = document.createElement('style');
      style.id = 'lumina-road-label-style';
      style.textContent = `
        .lumina-road-name.leaflet-tooltip {
          background: rgba(255,255,255,.94);
          border: 1px solid rgba(20,35,55,.18);
          color: #172235;
          border-radius: 7px;
          padding: 2px 6px;
          font-size: 11px;
          font-weight: 800;
          line-height: 1.15;
          box-shadow: 0 1px 4px rgba(0,0,0,.16);
          white-space: nowrap;
        }
        .lumina-road-name.leaflet-tooltip:before { display:none; }
      `;
      document.head.appendChild(style);
    };

    const boundsKey = b => {
      const c = b.getCenter();
      return `${map.getZoom()}:${c.lat.toFixed(3)}:${c.lng.toFixed(3)}`;
    };

    const loadRoadNames = async () => {
      if (map.getZoom() < 16 || loading) {
        if (map.getZoom() < 16) { labelsLayer.clearLayers(); lastKey = ''; }
        return;
      }
      const b = map.getBounds();
      const key = boundsKey(b);
      if (key === lastKey) return;
      loading = true;
      try {
        const s = b.getSouth(), w = b.getWest(), n = b.getNorth(), e = b.getEast();
        const q = `[out:json][timeout:12];way(${s},${w},${n},${e})[highway][name];out tags geom 80;`;
        const r = await fetch('https://overpass-api.de/api/interpreter', { method: 'POST', body: q });
        if (!r.ok) throw new Error('roads');
        const j = await r.json();
        labelsLayer.clearLayers();
        const seen = new Set();
        for (const way of j.elements || []) {
          const name = way.tags?.name;
          const geom = way.geometry;
          if (!name || !Array.isArray(geom) || geom.length < 2) continue;
          const ref = way.tags?.ref;
          const label = ref && !name.includes(ref) ? `${name} · ${ref}` : name;
          const signature = `${label}:${Math.round(geom[0].lat*1000)}:${Math.round(geom[0].lon*1000)}`;
          if (seen.has(signature)) continue;
          seen.add(signature);
          const latlngs = geom.map(p => [p.lat, p.lon]);
          const road = L.polyline(latlngs, { pane: 'roadNames', opacity: 0, weight: 14, interactive: false }).addTo(labelsLayer);
          road.bindTooltip(label, { permanent: true, direction: 'center', className: 'lumina-road-name', opacity: 1, sticky: false });
        }
        lastKey = key;
      } catch {
        // Keep the base map usable if the public OSM data service is unavailable.
      } finally {
        loading = false;
      }
    };

    const schedule = () => {
      clearTimeout(timer);
      timer = setTimeout(loadRoadNames, 350);
    };

    ensureStyle();
    map.on('zoomend moveend', schedule);
    map.whenReady(schedule);
    return map;
  };

  Object.assign(wrappedMap, L.map);
  wrappedMap.__luminaWrapped = true;
  L.map = wrappedMap;
})();