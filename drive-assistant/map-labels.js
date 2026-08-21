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
    let currentRoadLabel = null;
    let lastKey = '';
    let loading = false;
    let timer = null;

    const ensureStyle = () => {
      if (document.getElementById('lumina-road-label-style')) return;
      const style = document.createElement('style');
      style.id = 'lumina-road-label-style';
      style.textContent = `
        .lumina-road-name.leaflet-tooltip,
        .lumina-current-road.leaflet-tooltip {
          background: rgba(255,255,255,.96);
          border: 1px solid rgba(20,35,55,.18);
          color: #172235;
          border-radius: 8px;
          padding: 3px 7px;
          font-size: 12px;
          font-weight: 850;
          line-height: 1.15;
          box-shadow: 0 2px 8px rgba(0,0,0,.18);
          white-space: nowrap;
        }
        .lumina-current-road.leaflet-tooltip {
          background: rgba(7,17,31,.94);
          color: #fff;
          border-color: rgba(88,221,209,.5);
          font-size: 13px;
        }
        .lumina-road-name.leaflet-tooltip:before,
        .lumina-current-road.leaflet-tooltip:before { display:none; }
      `;
      document.head.appendChild(style);
    };

    const boundsKey = b => {
      const c = b.getCenter();
      return `${map.getZoom()}:${c.lat.toFixed(3)}:${c.lng.toFixed(3)}`;
    };

    const updateCurrentRoad = () => {
      const marker = window.__luminaCurrentUserMarker;
      const roadEl = document.getElementById('roadName');
      const road = roadEl?.textContent?.trim();
      if (!marker || !road || road === '—') return;
      const latlng = marker.getLatLng?.();
      if (!latlng) return;
      if (currentRoadLabel) labelsLayer.removeLayer(currentRoadLabel);
      currentRoadLabel = L.circleMarker(latlng, {
        pane: 'roadNames', radius: 1, opacity: 0, fillOpacity: 0, interactive: false
      }).addTo(labelsLayer);
      currentRoadLabel.bindTooltip(road, {
        permanent: true,
        direction: 'top',
        offset: [0, -14],
        className: 'lumina-current-road',
        opacity: 1
      });
    };

    const loadRoadNames = async () => {
      if (map.getZoom() < 16 || loading) {
        if (map.getZoom() < 16) { labelsLayer.clearLayers(); currentRoadLabel = null; lastKey = ''; }
        return;
      }
      const b = map.getBounds();
      const key = boundsKey(b);
      if (key === lastKey) { updateCurrentRoad(); return; }
      loading = true;
      try {
        const s = b.getSouth(), w = b.getWest(), n = b.getNorth(), e = b.getEast();
        const q = `[out:json][timeout:10];way(${s},${w},${n},${e})[highway][name];out tags geom 60;`;
        const r = await fetch('https://overpass-api.de/api/interpreter', { method: 'POST', body: q });
        if (!r.ok) throw new Error('roads');
        const j = await r.json();
        labelsLayer.clearLayers();
        currentRoadLabel = null;
        const seen = new Set();
        for (const way of j.elements || []) {
          const name = way.tags?.name;
          const geom = way.geometry;
          if (!name || !Array.isArray(geom) || geom.length < 2) continue;
          const ref = way.tags?.ref;
          const label = ref && !name.includes(ref) ? `${name} · ${ref}` : name;
          if (seen.has(label)) continue;
          seen.add(label);
          const latlngs = geom.map(p => [p.lat, p.lon]);
          const road = L.polyline(latlngs, { pane: 'roadNames', opacity: 0, weight: 14, interactive: false }).addTo(labelsLayer);
          road.bindTooltip(label, { permanent: true, direction: 'center', className: 'lumina-road-name', opacity: 1 });
        }
        lastKey = key;
      } catch {
        // Fallback below still shows the current road even when Overpass is unavailable.
      } finally {
        loading = false;
        updateCurrentRoad();
      }
    };

    const schedule = () => {
      clearTimeout(timer);
      timer = setTimeout(loadRoadNames, 300);
    };

    ensureStyle();
    map.on('zoomend moveend', schedule);
    map.whenReady(schedule);
    const observer = new MutationObserver(() => setTimeout(updateCurrentRoad, 0));
    const roadEl = document.getElementById('roadName');
    if (roadEl) observer.observe(roadEl, { childList: true, characterData: true, subtree: true });
    return map;
  };

  Object.assign(wrappedMap, L.map);
  wrappedMap.__luminaWrapped = true;
  L.map = wrappedMap;
})();