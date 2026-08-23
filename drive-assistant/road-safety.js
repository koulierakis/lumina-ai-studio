// LUMINA Drive Assistant - live road-safety and service-health layer
// Uses only browser capabilities and live public data sources. No mock safety data.
(() => {
  'use strict';

  const $ = s => document.querySelector(s);
  const CFG = {
    osrm: 'https://router.project-osrm.org',
    overpass: 'https://overpass-api.de/api/interpreter',
    nominatim: 'https://nominatim.openstreetmap.org',
    weather: 'https://api.open-meteo.com/v1/forecast'
  };
  const SERVICE_TTL = 5 * 60 * 1000;
  const INTEL_TTL = 22 * 1000;
  const spokenAt = new Map();
  let lastIntelAt = 0;
  let lastServiceAt = 0;
  let safetyItems = [];
  let lastPos = null;
  let osmHealth = null;
  let lastRemoteState = {routing:null, osm:null, geocode:null, weather:null};

  const rad = v => v * Math.PI / 180;
  function distance(a, b) {
    const R = 6371e3;
    const p1 = rad(a.lat), p2 = rad(b.lat);
    const dp = rad(b.lat - a.lat), dl = rad(b.lng - a.lng);
    const x = Math.sin(dp / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
    return 2 * R * Math.atan2(Math.sqrt(x), Math.sqrt(1 - x));
  }
  const fmtDistance = m => m < 1000 ? `${Math.round(m)} m` : `${(m / 1000).toFixed(1)} km`;
  const pointOf = x => x.lat ? {lat: x.lat, lng: x.lon} : x.center ? {lat: x.center.lat, lng: x.center.lon} : null;

  function nearest(list, c) {
    let best = null;
    for (const x of list) {
      const p = pointOf(x);
      if (!p) continue;
      const d = distance(c, p);
      if (!best || d < best.d) best = {x, d};
    }
    return best;
  }

  function parseSpeedLimit(value) {
    const raw = String(value || '').trim().toLowerCase();
    if (!raw || /^(none|signals|variable|walk|national|urban|rural)$/.test(raw)) return null;
    const match = raw.match(/(\d{1,3})(?:\s*(mph|km\/h|kph))?/);
    if (!match) return null;
    let n = Number(match[1]);
    if (!Number.isFinite(n) || n <= 0 || n > 160) return null;
    if (match[2] === 'mph') n = Math.round(n * 1.609344);
    return n;
  }

  function applyConfidentSpeedLimit(elements) {
    const limits = elements
      .filter(x => x.type === 'way' && x.tags?.highway && x.tags?.maxspeed)
      .map(x => parseSpeedLimit(x.tags.maxspeed))
      .filter(Number.isFinite);
    if (!limits.length) return;
    const unique = [...new Set(limits)];
    // At junctions/parallel roads different nearby limits can legitimately coexist.
    // In that case do not overwrite the UI with a potentially false limit.
    if (unique.length !== 1) return;
    const value = String(unique[0]);
    const a = $('#speedLimit'), b = $('#navSpeedLimit');
    if (a) a.textContent = value;
    if (b) b.textContent = value;
  }

  function speakOnce(key, text, ttl = 90000) {
    if (!text || !('speechSynthesis' in window)) return;
    const voiceToggle = $('#voiceAlertsToggle');
    if (voiceToggle && !voiceToggle.checked) return;
    const last = spokenAt.get(key) || 0;
    if (Date.now() - last < ttl) return;
    spokenAt.set(key, Date.now());
    try {
      const u = new SpeechSynthesisUtterance(text);
      u.lang = 'el-GR';
      u.rate = 0.96;
      speechSynthesis.speak(u);
    } catch {}
  }

  function ensureSafetyBox() {
    const list = $('#alertsList');
    if (!list) return null;
    let box = $('#verifiedSafetyAlerts');
    if (!box) {
      box = document.createElement('div');
      box.id = 'verifiedSafetyAlerts';
      box.className = 'verified-safety-alerts';
      list.parentElement?.insertBefore(box, list);
    }
    return box;
  }

  function renderSafety() {
    const box = ensureSafetyBox();
    if (!box) return;
    if (!safetyItems.length) {
      box.innerHTML = '';
      return;
    }
    box.innerHTML = safetyItems.map(item => {
      const detail = item.detail ? `<small>${item.detail}</small>` : '';
      return `<div class="alert verified-alert"><span>${item.icon}</span><div><b>${item.title}</b>${detail}</div></div>`;
    }).join('');
  }

  async function fetchJson(url, options = {}, timeoutMs = 9000) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(url, {...options, signal: controller.signal, cache: 'no-store'});
      if (!response.ok) throw new Error(String(response.status));
      return await response.json();
    } finally {
      clearTimeout(timer);
    }
  }

  async function refreshRoadSafety(c) {
    if (!navigator.onLine || Date.now() - lastIntelAt < INTEL_TTL) return;
    lastIntelAt = Date.now();

    const q = `[out:json][timeout:10];(
      node(around:700,${c.lat},${c.lng})[railway=level_crossing];
      way(around:900,${c.lat},${c.lng})[highway=construction];
      node(around:700,${c.lat},${c.lng})[hazard];
      way(around:700,${c.lat},${c.lng})[hazard];
      node(around:500,${c.lat},${c.lng})[traffic_calming];
      way(around:35,${c.lat},${c.lng})[highway][maxspeed];
    );out tags center;`;

    try {
      const data = await fetchJson(CFG.overpass, {method: 'POST', body: q}, 12000);
      const elements = Array.isArray(data.elements) ? data.elements : [];
      const items = [];

      applyConfidentSpeedLimit(elements);

      const works = nearest(elements.filter(x => x.tags?.highway === 'construction'), c);
      if (works && works.d < 850) {
        items.push({icon: '🚧', title: 'Χαρτογραφημένα έργα', detail: `${fmtDistance(works.d)} από τη θέση σου · OpenStreetMap`});
        if (works.d < 500) speakOnce('works', 'Προσοχή. Υπάρχουν χαρτογραφημένα έργα στον δρόμο μπροστά.');
      }

      const crossing = nearest(elements.filter(x => x.tags?.railway === 'level_crossing'), c);
      if (crossing && crossing.d < 650) {
        items.push({icon: '🚆', title: 'Ισόπεδη σιδηροδρομική διάβαση', detail: `${fmtDistance(crossing.d)} από τη θέση σου · OpenStreetMap`});
        if (crossing.d < 350) speakOnce('rail', 'Προσοχή. Πλησιάζεις ισόπεδη σιδηροδρομική διάβαση.');
      }

      const hazard = nearest(elements.filter(x => x.tags?.hazard), c);
      if (hazard && hazard.d < 650) {
        const raw = String(hazard.x.tags.hazard || '').replace(/_/g, ' ');
        const curve = /curve|bend|turn|serpentine|winding/i.test(raw);
        items.push({
          icon: curve ? '↪️' : '⚠️',
          title: curve ? 'Χαρτογραφημένη επικίνδυνη στροφή' : 'Χαρτογραφημένος οδικός κίνδυνος',
          detail: `${fmtDistance(hazard.d)} · ${raw} · OpenStreetMap`
        });
        if (hazard.d < 350) speakOnce(`hazard:${raw}`, curve ? 'Προσοχή. Υπάρχει χαρτογραφημένη επικίνδυνη στροφή μπροστά.' : 'Προσοχή. Υπάρχει χαρτογραφημένος οδικός κίνδυνος μπροστά.');
      }

      const calming = nearest(elements.filter(x => x.tags?.traffic_calming), c);
      if (calming && calming.d < 300) items.push({icon:'〰️', title:'Μείωση ταχύτητας', detail:`${fmtDistance(calming.d)} · χαρτογραφημένο traffic calming`});

      safetyItems = items;
      osmHealth = true;
      lastRemoteState.osm = true;
      renderSafety();
      renderMonitor(lastRemoteState);
    } catch {
      safetyItems = [];
      osmHealth = false;
      lastRemoteState.osm = false;
      renderSafety();
      renderMonitor(lastRemoteState);
    }
  }

  function statusCell(name, status) {
    const cls = status === true ? 'ok' : status === false ? 'warn' : '';
    const text = status === true ? 'READY' : status === false ? 'LIMITED' : 'CHECKING';
    return `<div class="monitor-item"><span>${name}</span><b class="${cls}">${text}</b></div>`;
  }

  async function refreshServices(c) {
    if (!navigator.onLine) {
      lastRemoteState = {routing:false, osm:false, geocode:false, weather:false};
      return renderMonitor(lastRemoteState);
    }
    if (Date.now() - lastServiceAt < SERVICE_TTL) return;
    lastServiceAt = Date.now();

    lastRemoteState = {routing:null, osm:osmHealth, geocode:null, weather:null};
    renderMonitor(lastRemoteState);
    const tinyLng = c.lng + 0.001;
    const probes = await Promise.allSettled([
      fetchJson(`${CFG.osrm}/route/v1/driving/${c.lng},${c.lat};${tinyLng},${c.lat}?overview=false&steps=false`, {}, 8000),
      fetchJson(`${CFG.nominatim}/reverse?format=jsonv2&lat=${c.lat}&lon=${c.lng}&zoom=14`, {headers:{Accept:'application/json'}}, 8000),
      fetchJson(`${CFG.weather}?latitude=${c.lat}&longitude=${c.lng}&current=temperature_2m`, {}, 8000)
    ]);
    lastRemoteState = {
      routing: probes[0].status === 'fulfilled' && probes[0].value?.code === 'Ok',
      geocode: probes[1].status === 'fulfilled' && !!probes[1].value,
      weather: probes[2].status === 'fulfilled' && !!probes[2].value?.current,
      osm: osmHealth
    };
    renderMonitor(lastRemoteState);
  }

  function renderMonitor(remote = {}) {
    const grid = $('#monitorGrid');
    if (!grid) return;
    const local = [
      ['Χάρτης', !!window.L],
      ['GPS', 'geolocation' in navigator],
      ['Ελληνική TTS', 'speechSynthesis' in window],
      ['Voice input', !!(window.SpeechRecognition || window.webkitSpeechRecognition)],
      ['Online', navigator.onLine],
      ['Wake Lock', 'wakeLock' in navigator],
      ['Offline shell', 'serviceWorker' in navigator]
    ];
    grid.innerHTML = local.map(([name, ok]) => statusCell(name, ok)).join('') +
      statusCell('Routing / OSRM', remote.routing) +
      statusCell('OSM safety data', remote.osm) +
      statusCell('Geocoding', remote.geocode) +
      statusCell('Weather', remote.weather);

    const ready = $('#readyState');
    if (!ready) return;
    const localCritical = local.slice(0, 5).every(([, ok]) => ok);
    const remoteValues = [remote.routing, remote.osm, remote.geocode, remote.weather];
    if (remoteValues.some(v => v === null || typeof v === 'undefined')) ready.textContent = 'CHECKING';
    else ready.textContent = localCritical && remoteValues.every(Boolean) ? 'OPERATIONAL' : 'LIMITED';
  }

  function onPosition(p) {
    const c = {lat:p.coords.latitude, lng:p.coords.longitude};
    lastPos = c;
    refreshRoadSafety(c);
    refreshServices(c);
  }

  function start() {
    lastRemoteState = {routing:navigator.onLine?null:false, osm:navigator.onLine?null:false, geocode:navigator.onLine?null:false, weather:navigator.onLine?null:false};
    renderMonitor(lastRemoteState);
    if (!navigator.geolocation) return;
    navigator.geolocation.watchPosition(onPosition, () => {}, {enableHighAccuracy:true, maximumAge:5000, timeout:15000});
    window.addEventListener('online', () => {
      lastServiceAt = 0;
      lastIntelAt = 0;
      osmHealth = null;
      if (lastPos) { refreshRoadSafety(lastPos); refreshServices(lastPos); }
    });
    window.addEventListener('offline', () => {
      lastRemoteState = {routing:false, osm:false, geocode:false, weather:false};
      renderMonitor(lastRemoteState);
    });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, {once:true});
  else start();
})();
