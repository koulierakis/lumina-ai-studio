(() => {
  const MODE_KEY = 'lumina-drive-travel-mode';
  const originalFetch = window.fetch.bind(window);

  function getMode() {
    return localStorage.getItem(MODE_KEY) === 'walk' ? 'walk' : 'drive';
  }

  function setMode(mode) {
    const next = mode === 'walk' ? 'walk' : 'drive';
    localStorage.setItem(MODE_KEY, next);
    window.__luminaTravelMode = next;
    document.querySelectorAll('[data-travel-mode]').forEach(btn => {
      const active = btn.dataset.travelMode === next;
      btn.classList.toggle('active', active);
      btn.setAttribute('aria-pressed', String(active));
    });
    const hint = document.querySelector('#travelModeHint');
    if (hint) hint.textContent = next === 'walk'
      ? '🚶 Πεζή διαδρομή: πεζόδρομοι και δρόμοι προσβάσιμοι με τα πόδια.'
      : '🚗 Διαδρομή με αυτοκίνητο.';
    const preview = document.querySelector('#routePreview');
    if (preview && !preview.classList.contains('hidden')) {
      preview.classList.add('hidden');
      const alerts = document.querySelector('#alertsList');
      if (alerts) {
        const note = document.createElement('div');
        note.className = 'alert';
        note.innerHTML = `<span>🔄</span><div><b>Άλλαξε ο τρόπος μετακίνησης</b><small>Πάτησε ξανά «Οδηγίες» για νέα ${next === 'walk' ? 'πεζή' : 'οδική'} διαδρομή.</small></div>`;
        alerts.prepend(note);
      }
    }
  }

  function decodePolyline6(encoded) {
    let index = 0, lat = 0, lon = 0;
    const coords = [];
    while (index < encoded.length) {
      let shift = 0, result = 0, byte;
      do {
        byte = encoded.charCodeAt(index++) - 63;
        result |= (byte & 0x1f) << shift;
        shift += 5;
      } while (byte >= 0x20 && index <= encoded.length);
      lat += (result & 1) ? ~(result >> 1) : (result >> 1);
      shift = 0; result = 0;
      do {
        byte = encoded.charCodeAt(index++) - 63;
        result |= (byte & 0x1f) << shift;
        shift += 5;
      } while (byte >= 0x20 && index <= encoded.length);
      lon += (result & 1) ? ~(result >> 1) : (result >> 1);
      coords.push([lon / 1e6, lat / 1e6]);
    }
    return coords;
  }

  function osrmStepFromValhalla(m, coords) {
    const instruction = String(m.instruction || m.verbal_transition_alert_instruction || '').trim();
    const lower = instruction.toLocaleLowerCase('el-GR');
    let type = 'continue';
    let modifier = 'straight';
    if (/προορισμ|destination|arrive/.test(lower)) type = 'arrive';
    else if (/ξεκί|start|depart/.test(lower)) type = 'depart';
    else if (/κυκλικ|roundabout|rotary/.test(lower)) type = 'roundabout';
    if (/δεξ|right/.test(lower)) modifier = 'right';
    else if (/αρισ|left/.test(lower)) modifier = 'left';
    else if (/αναστροφ|u-turn|uturn/.test(lower)) modifier = 'uturn';
    const idx = Math.min(Math.max(Number(m.begin_shape_index) || 0, 0), Math.max(0, coords.length - 1));
    const exitMatch = instruction.match(/(?:έξοδο|exit)\s*(\d+)/i);
    return {
      name: Array.isArray(m.street_names) && m.street_names.length ? m.street_names[0] : '',
      distance: Number(m.length || 0) * 1000,
      duration: Number(m.time || 0),
      maneuver: {
        type,
        modifier,
        location: coords[idx] || coords[0] || [0, 0],
        ...(exitMatch ? {exit:Number(exitMatch[1])} : {})
      }
    };
  }

  async function pedestrianRoute(points) {
    if (points.length < 2 || points.some(p => !Number.isFinite(p.lat) || !Number.isFinite(p.lon))) throw new Error('walking-route-points');
    const payload = {
      locations: points,
      costing: 'pedestrian',
      units: 'kilometers',
      language: 'el-GR',
      directions_options: {units:'kilometers', language:'el-GR'}
    };
    const url = `https://valhalla1.openstreetmap.de/route?json=${encodeURIComponent(JSON.stringify(payload))}`;
    const response = await originalFetch(url, {headers:{Accept:'application/json'}, cache:'no-store'});
    if (!response.ok) throw new Error(`walking-route-${response.status}`);
    const data = await response.json();
    const trip = data.trip;
    const leg = trip?.legs?.[0];
    if (!trip || !leg?.shape) throw new Error('walking-route-empty');
    const coords = decodePolyline6(leg.shape);
    const summary = trip.summary || leg.summary || {};
    const distanceM = Number(summary.length || 0) * 1000;
    const durationS = Number(summary.time || 0);
    const steps = (leg.maneuvers || []).map(m => osrmStepFromValhalla(m, coords));
    return {
      distance: distanceM,
      duration: durationS,
      geometry: {type:'LineString', coordinates:coords},
      legs: [{distance:distanceM, duration:durationS, steps}]
    };
  }

  async function pedestrianOsrmResponse(osrmUrl) {
    const match = osrmUrl.match(/\/route\/v1\/driving\/([^?]+)/);
    if (!match) throw new Error('walking-route-parse');
    const points = match[1].split(';').map(pair => {
      const [lon, lat] = pair.split(',').map(Number);
      return {lat, lon};
    });
    const route = await pedestrianRoute(points);
    return new Response(JSON.stringify({code:'Ok', routes:[route], waypoints:points.map(p => ({location:[p.lon,p.lat]}))}), {
      status: 200,
      headers: {'Content-Type':'application/json'}
    });
  }

  window.LuminaWalkingRouter = {
    route: (origin, destination) => pedestrianRoute([
      {lat:Number(origin.lat), lon:Number(origin.lng)},
      {lat:Number(destination.lat), lon:Number(destination.lng)}
    ])
  };

  window.__luminaTravelMode = getMode();
  window.fetch = async (input, init) => {
    const url = typeof input === 'string' ? input : input?.url || '';
    if (window.__luminaTravelMode === 'walk' && url.includes('router.project-osrm.org/route/v1/driving/')) {
      try {
        return await pedestrianOsrmResponse(url);
      } catch (error) {
        console.warn('LUMINA pedestrian routing failed', error);
        return new Response(JSON.stringify({code:'NoRoute', message:'Pedestrian route unavailable'}), {
          status: 503,
          headers: {'Content-Type':'application/json'}
        });
      }
    }
    return originalFetch(input, init);
  };

  document.querySelectorAll('[data-travel-mode]').forEach(btn => btn.addEventListener('click', () => setMode(btn.dataset.travelMode)));
  setMode(getMode());
})();
