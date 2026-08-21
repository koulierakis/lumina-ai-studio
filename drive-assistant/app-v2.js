const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];

const cfg = {
  nominatim: 'https://nominatim.openstreetmap.org',
  osrm: 'https://router.project-osrm.org',
  overpass: 'https://overpass-api.de/api/interpreter',
  weather: 'https://api.open-meteo.com/v1/forecast'
};

const DEFAULT_SETTINGS = { voice: true, speed: true, camera: true, weather: true, autoReroute: true };
const state = {
  map: null,
  userMarker: null,
  routeLayer: null,
  poiLayer: null,
  destinationMarker: null,
  lastPos: null,
  lastAcceptedPos: null,
  startAt: null,
  totalM: 0,
  speeds: [],
  route: null,
  routeSteps: [],
  routeCoords: [],
  destination: null,
  watchId: null,
  alerts: new Map(),
  spoken: new Map(),
  freeDrive: false,
  lastIntelAt: 0,
  lastRerouteAt: 0,
  wakeLock: null,
  settings: loadSettings()
};

function loadSettings() {
  try { return { ...DEFAULT_SETTINGS, ...JSON.parse(localStorage.getItem('lumina-drive-settings') || '{}') }; }
  catch { return { ...DEFAULT_SETTINGS }; }
}
function saveSettings() { localStorage.setItem('lumina-drive-settings', JSON.stringify(state.settings)); }
function kmh(ms) { return Number.isFinite(ms) ? Math.max(0, ms * 3.6) : 0; }
function rad(v) { return v * Math.PI / 180; }
function dist(a, b) {
  const R = 6371e3, p1 = rad(a.lat), p2 = rad(b.lat), dp = rad(b.lat - a.lat), dl = rad(b.lng - a.lng);
  const x = Math.sin(dp / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
  return 2 * R * Math.atan2(Math.sqrt(x), Math.sqrt(1 - x));
}
function fmtTime(ms) {
  const m = Math.max(0, Math.floor(ms / 60000));
  return `${String(Math.floor(m / 60)).padStart(2,'0')}:${String(m % 60).padStart(2,'0')}`;
}
function fmtDistance(m) { return m < 1000 ? `${Math.round(m)} m` : `${(m / 1000).toFixed(1)} km`; }
function escapeHtml(s='') { return String(s).replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c])); }

function speak(text, key = text, ttlMs = 30000) {
  if (!state.settings.voice || !('speechSynthesis' in window) || !text) return;
  const last = state.spoken.get(key) || 0;
  if (Date.now() - last < ttlMs) return;
  state.spoken.set(key, Date.now());
  const u = new SpeechSynthesisUtterance(text);
  u.lang = 'el-GR';
  u.rate = 0.96;
  speechSynthesis.cancel();
  speechSynthesis.speak(u);
}

function addAlert(id, icon, title, detail = '', voice = '') {
  state.alerts.set(id, { icon, title, detail, at: Date.now() });
  renderAlerts();
  if (voice) speak(voice, `alert:${id}`, 45000);
}
function clearAlert(id) { if (state.alerts.delete(id)) renderAlerts(); }
function renderAlerts() {
  const el = $('#alertsList'); if (!el) return;
  const arr = [...state.alerts.values()].sort((a,b) => b.at - a.at);
  $('#alertCount').textContent = `${arr.length} ειδοποιήσεις`;
  el.innerHTML = arr.length ? arr.map(a => `<div class="alert"><span>${a.icon}</span><div><b>${escapeHtml(a.title)}</b><small>${escapeHtml(a.detail)}</small></div></div>`).join('') : '<div class="empty">Δεν υπάρχουν ενεργές ειδοποιήσεις.</div>';
}

function setNetworkState() {
  const badge = $('#networkBadge'); if (!badge) return;
  badge.textContent = navigator.onLine ? 'ONLINE' : 'OFFLINE';
  badge.classList.toggle('offline', !navigator.onLine);
  if (!navigator.onLine) addAlert('offline','📴','Χωρίς σύνδεση','Ο χάρτης που έχει ήδη φορτωθεί παραμένει διαθέσιμος, αλλά νέα routing/POI δεδομένα απαιτούν internet.');
  else clearAlert('offline');
}

function initMap() {
  state.map = L.map('map', { zoomControl: false, preferCanvas: true }).setView([39.0742,21.8243], 7);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, attribution: '© OpenStreetMap' }).addTo(state.map);
  L.control.zoom({ position: 'bottomright' }).addTo(state.map);
}

async function requestWakeLock() {
  if (!('wakeLock' in navigator)) return;
  try { state.wakeLock = await navigator.wakeLock.request('screen'); } catch {}
}

document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') requestWakeLock(); });

function startGPS() {
  if (!navigator.geolocation) { $('#gpsStatus').textContent = 'GPS μη διαθέσιμο'; addAlert('gps','📡','GPS μη διαθέσιμο','Ο browser δεν παρέχει Geolocation API.'); return; }
  state.startAt = Date.now();
  state.watchId = navigator.geolocation.watchPosition(onPos, onGpsError, { enableHighAccuracy: true, maximumAge: 1000, timeout: 15000 });
  requestWakeLock();
}
function onGpsError(err) {
  $('#gpsStatus').textContent = 'GPS error';
  const msg = err?.code === 1 ? 'Χρειάζεται άδεια τοποθεσίας.' : 'Δεν υπάρχει αξιόπιστο GPS σήμα αυτή τη στιγμή.';
  addAlert('gps','📡','GPS',msg);
}

async function onPos(p) {
  const c = { lat: p.coords.latitude, lng: p.coords.longitude };
  const speed = kmh(p.coords.speed);
  $('#speed').textContent = Math.round(speed);
  $('#gpsStatus').textContent = `GPS ±${Math.round(p.coords.accuracy)}m`;
  clearAlert('gps');

  state.speeds.push(speed);
  if (state.speeds.length > 180) state.speeds.shift();
  if (state.lastAcceptedPos) {
    const d = dist(state.lastAcceptedPos, c);
    if (d >= 2 && d < 300 && p.coords.accuracy < 80) { state.totalM += d; state.lastAcceptedPos = c; }
  } else state.lastAcceptedPos = c;
  state.lastPos = c;

  $('#tripDistance').textContent = `${(state.totalM / 1000).toFixed(1)} km`;
  $('#tripTime').textContent = fmtTime(Date.now() - state.startAt);
  $('#avgSpeed').textContent = `${Math.round(state.speeds.reduce((a,b)=>a+b,0) / Math.max(1,state.speeds.length))} km/h`;

  if (!state.userMarker) {
    state.userMarker = L.circleMarker(c,{radius:9,weight:4,color:'#fff',fillColor:'#4fd1c5',fillOpacity:1}).addTo(state.map);
    state.map.setView(c,16);
  } else state.userMarker.setLatLng(c);
  if (state.freeDrive || state.route) state.map.panTo(c,{animate:true});

  checkOverspeed(speed);
  checkFatigue();
  await checkRouteProgress(c);
  throttledRoadIntel(c);
}

function checkOverspeed(speed) {
  if (!state.settings.speed) return clearAlert('speed');
  const lim = parseInt($('#speedLimit').textContent,10);
  if (Number.isFinite(lim) && speed > lim + 4) addAlert('speed','⚠️','Υπέρβαση ορίου',`${Math.round(speed)} km/h σε όριο ${lim}`,'Προσοχή. Έχεις υπερβεί το όριο ταχύτητας.');
  else clearAlert('speed');
}
function checkFatigue() {
  if (!state.startAt) return;
  const hrs = (Date.now() - state.startAt) / 36e5;
  if (hrs > 1.9) addAlert('rest','☕','Πρόταση στάσης',`Οδηγείς περίπου ${hrs.toFixed(1)} ώρες.`,'Σκέψου ένα σύντομο διάλειμμα από την οδήγηση.');
}

async function reverseRoad(c) {
  try {
    const r = await fetch(`${cfg.nominatim}/reverse?format=jsonv2&lat=${c.lat}&lon=${c.lng}&zoom=18&addressdetails=1`,{headers:{Accept:'application/json'}});
    if (!r.ok) throw new Error('reverse');
    const j = await r.json();
    $('#roadName').textContent = j.address?.road || j.address?.pedestrian || j.display_name?.split(',')[0] || '—';
  } catch {}
}

function nearestFeature(list,c) {
  let best = null;
  for (const x of list) {
    const p = x.lat ? {lat:x.lat,lng:x.lon} : x.center ? {lat:x.center.lat,lng:x.center.lon} : null;
    if (!p) continue;
    const d = dist(c,p);
    if (!best || d < best.d) best = {x,d};
  }
  return best;
}

async function queryRoadFeatures(c) {
  const q = `[out:json][timeout:12];(node(around:1200,${c.lat},${c.lng})[highway=speed_camera];node(around:550,${c.lat},${c.lng})[highway=crossing];node(around:750,${c.lat},${c.lng})[railway=level_crossing];node(around:500,${c.lat},${c.lng})[traffic_calming];way(around:110,${c.lat},${c.lng})[highway][maxspeed];way(around:800,${c.lat},${c.lng})[highway=construction];);out tags center;`;
  try {
    const r = await fetch(cfg.overpass,{method:'POST',body:q}); if (!r.ok) throw new Error('overpass');
    const j = await r.json();
    const road = j.elements.find(x=>x.tags?.maxspeed);
    if (road) { const n = parseInt(String(road.tags.maxspeed).match(/\d+/)?.[0],10); if (n) $('#speedLimit').textContent = n; }
    else $('#speedLimit').textContent = '—';

    const cam = nearestFeature(j.elements.filter(x=>x.tags?.highway==='speed_camera'),c);
    if (state.settings.camera && cam && cam.d < 1100) addAlert('camera','📷','Καταχωρημένη κάμερα',`${fmtDistance(cam.d)} από τη θέση σου.`,'Προσοχή. Καταχωρημένη κάμερα ταχύτητας στην περιοχή.'); else clearAlert('camera');
    const rail = nearestFeature(j.elements.filter(x=>x.tags?.railway==='level_crossing'),c);
    if (rail && rail.d < 700) addAlert('rail','🚆','Σιδηροδρομική διάβαση',fmtDistance(rail.d),'Προσοχή. Σιδηροδρομική διάβαση στην περιοχή.'); else clearAlert('rail');
    const works = nearestFeature(j.elements.filter(x=>x.tags?.highway==='construction'),c);
    if (works && works.d < 800) addAlert('works','🚧','Έργα δρόμου',fmtDistance(works.d),'Προσοχή. Καταχωρημένα έργα στον δρόμο.'); else clearAlert('works');
    const calming = nearestFeature(j.elements.filter(x=>x.tags?.traffic_calming),c);
    if (calming && calming.d < 320) addAlert('calming','〰️','Μείωση ταχύτητας',fmtDistance(calming.d)); else clearAlert('calming');
    const crossing = nearestFeature(j.elements.filter(x=>x.tags?.highway==='crossing'),c);
    if (crossing && crossing.d < 240) addAlert('crossing','🚶','Διάβαση πεζών',fmtDistance(crossing.d)); else clearAlert('crossing');
    clearAlert('data');
  } catch { addAlert('data','🛰️','Περιορισμένα οδικά δεδομένα','Η δημόσια υπηρεσία χαρτογραφικών δεδομένων δεν απάντησε.'); }
}

async function queryWeather(c) {
  if (!state.settings.weather) return clearAlert('weather');
  try {
    const r = await fetch(`${cfg.weather}?latitude=${c.lat}&longitude=${c.lng}&current=temperature_2m,precipitation,weather_code,wind_speed_10m&timezone=auto`);
    if (!r.ok) throw new Error('weather'); const j = await r.json(), w = j.current; if (!w) return;
    const issues=[]; if (w.precipitation > 0.2) issues.push(`βροχή ${w.precipitation} mm`); if (w.wind_speed_10m > 45) issues.push(`άνεμος ${Math.round(w.wind_speed_10m)} km/h`); if (w.temperature_2m < 2) issues.push(`${Math.round(w.temperature_2m)}°C`);
    if (issues.length) addAlert('weather','🌦️','Καιρός οδήγησης',issues.join(' · '),'Προσοχή στις καιρικές συνθήκες.'); else clearAlert('weather');
  } catch {}
}

function throttledRoadIntel(c) {
  if (Date.now() - state.lastIntelAt < 18000) return;
  state.lastIntelAt = Date.now();
  reverseRoad(c); queryRoadFeatures(c); queryWeather(c);
}

async function geocode(q) {
  const r = await fetch(`${cfg.nominatim}/search?format=jsonv2&limit=6&countrycodes=gr&q=${encodeURIComponent(q)}`,{headers:{Accept:'application/json'}});
  if (!r.ok) throw new Error('geocode'); return r.json();
}
async function routeToQuery(q) {
  if (!q) return;
  if (!state.lastPos) return addAlert('waitgps','📡','Περιμένω GPS','Χρειάζεται τρέχουσα θέση.');
  try {
    const g = await geocode(q); if (!g.length) return addAlert('dest','🔎','Δεν βρέθηκε προορισμός',q);
    clearAlert('dest'); await routeTo({lat:+g[0].lat,lng:+g[0].lon,name:g[0].display_name});
  } catch { addAlert('routeerr','⚠️','Σφάλμα διαδρομής','Έλεγξε τη σύνδεση και δοκίμασε ξανά.'); }
}

async function routeTo(d,{silent=false}={}) {
  const o = state.lastPos; if (!o) throw new Error('gps');
  const url = `${cfg.osrm}/route/v1/driving/${o.lng},${o.lat};${d.lng},${d.lat}?overview=full&geometries=geojson&steps=true&alternatives=false`;
  const r = await fetch(url); if (!r.ok) throw new Error('route'); const j = await r.json(); if (j.code !== 'Ok' || !j.routes?.[0]) throw new Error('route');
  state.route = j.routes[0]; state.routeSteps = state.route.legs?.[0]?.steps || []; state.routeCoords = state.route.geometry.coordinates || []; state.destination = d;
  if (state.routeLayer) state.routeLayer.remove();
  state.routeLayer = L.geoJSON(state.route.geometry,{style:{color:'#4fd1c5',weight:6,opacity:.9}}).addTo(state.map);
  if (state.destinationMarker) state.destinationMarker.remove();
  state.destinationMarker = L.marker(d).addTo(state.map).bindPopup(escapeHtml(d.name || 'Προορισμός'));
  state.map.fitBounds(state.routeLayer.getBounds(),{padding:[30,30]});
  $('#maneuverCard').classList.remove('hidden');
  updateManeuverCard(state.routeSteps[0], state.route.distance, state.route.duration);
  detectRouteCurves(state.routeCoords);
  clearAlert('routeerr');
  if (!silent) speak(`Η διαδρομή ξεκίνησε. Απόσταση ${(state.route.distance/1000).toFixed(1)} χιλιόμετρα και εκτιμώμενος χρόνος ${Math.round(state.route.duration/60)} λεπτά.`,'route-start',5000);
}
function updateManeuverCard(step, distanceM, durationS) {
  const instruction = step?.maneuver?.instruction || step?.name || 'Συνέχισε';
  $('#maneuverText').textContent = instruction;
  $('#maneuverDistance').textContent = `${fmtDistance(distanceM)} · ${Math.round(durationS/60)}′`;
}

function bearing(a,b,c) {
  const h1 = Math.atan2(b[1]-a[1], b[0]-a[0]), h2 = Math.atan2(c[1]-b[1], c[0]-b[0]);
  let d = Math.abs((h2-h1)*180/Math.PI); if (d>180) d=360-d; return d;
}
function detectRouteCurves(coords) {
  let sharp=0; for(let i=2;i<coords.length;i+=4) if(bearing(coords[i-2],coords[i-1],coords[i])>55) sharp++;
  if(sharp) addAlert('curves','↪️','Έντονες στροφές',`${sharp} έντονες αλλαγές κατεύθυνσης στη χαρτογραφημένη διαδρομή.`); else clearAlert('curves');
}

function nearestRouteDistance(c) {
  if (!state.routeCoords.length) return Infinity;
  let best=Infinity; const stride=Math.max(1,Math.floor(state.routeCoords.length/500));
  for(let i=0;i<state.routeCoords.length;i+=stride){const q=state.routeCoords[i];best=Math.min(best,dist(c,{lat:q[1],lng:q[0]}));}
  return best;
}

async function checkRouteProgress(c) {
  if (!state.route || !state.destination) return;
  const remainingToDest = dist(c,state.destination);
  if (remainingToDest < 45) {
    addAlert('arrival','🏁','Έφτασες στον προορισμό','Η πλοήγηση ολοκληρώθηκε.','Έφτασες στον προορισμό σου.');
    $('#maneuverText').textContent='Άφιξη'; $('#maneuverDistance').textContent='—'; return;
  }

  let best=null;
  for(const s of state.routeSteps){const loc=s.maneuver?.location;if(!loc)continue;const d=dist(c,{lat:loc[1],lng:loc[0]});if(!best||d<best.d)best={s,d};}
  if(best && best.d < 1200){
    $('#maneuverText').textContent=best.s.maneuver?.instruction||best.s.name||'Συνέχισε';
    $('#maneuverDistance').textContent=fmtDistance(best.d);
    if(best.d<260 && best.d>70) speak(`Σε ${Math.round(best.d/10)*10} μέτρα, ${best.s.name||'ακολούθησε την επόμενη οδηγία'}.`,`turn:${best.s.maneuver?.location?.join(',')}`,120000);
  }

  if (state.settings.autoReroute && Date.now()-state.lastRerouteAt>30000 && nearestRouteDistance(c)>120) {
    state.lastRerouteAt=Date.now(); addAlert('reroute','🔄','Επαναϋπολογισμός','Έχεις απομακρυνθεί από τη διαδρομή.','Επαναϋπολογίζω τη διαδρομή.');
    try { await routeTo(state.destination,{silent:true}); clearAlert('reroute'); } catch { addAlert('reroute','⚠️','Αποτυχία επαναϋπολογισμού','Θα ξαναδοκιμάσω όταν υπάρχει σύνδεση.'); }
  }
}

const poiTags={pharmacy:['amenity','pharmacy'],fuel:['amenity','fuel'],restaurant:['amenity','restaurant'],gym:['leisure','fitness_centre'],parking:['amenity','parking'],hospital:['amenity','hospital'],charging_station:['amenity','charging_station'],supermarket:['shop','supermarket'],cafe:['amenity','cafe'],police:['amenity','police'],bank:['amenity','bank']};
async function findPOI(kind) {
  if (!state.lastPos) return addAlert('waitgps','📡','Περιμένω GPS','Χρειάζεται τρέχουσα θέση.');
  const pair=poiTags[kind]; if(!pair)return; const [k,v]=pair,c=state.lastPos;
  const q=`[out:json][timeout:15];(node(around:6000,${c.lat},${c.lng})[${k}=${v}];way(around:6000,${c.lat},${c.lng})[${k}=${v}];relation(around:6000,${c.lat},${c.lng})[${k}=${v}];);out center tags 25;`;
  try {
    const r=await fetch(cfg.overpass,{method:'POST',body:q}); if(!r.ok)throw new Error('poi'); const j=await r.json();
    if(state.poiLayer)state.poiLayer.clearLayers(); else state.poiLayer=L.layerGroup().addTo(state.map);
    const found=[];
    for(const x of j.elements){const p=x.lat?{lat:x.lat,lng:x.lon}:x.center?{lat:x.center.lat,lng:x.center.lon}:null;if(!p)continue;found.push({p,name:x.tags?.name||v,d:dist(c,p)});}
    found.sort((a,b)=>a.d-b.d); found.slice(0,20).forEach(item=>L.marker(item.p).addTo(state.poiLayer).bindPopup(`<b>${escapeHtml(item.name)}</b><br>${fmtDistance(item.d)}<br><button class="poi-route" data-lat="${item.p.lat}" data-lng="${item.p.lng}" data-name="${escapeHtml(item.name)}">Διαδρομή</button>`));
    addAlert('poi','📍','Κοντινά σημεία',`${found.length} αποτελέσματα σε ακτίνα 6 km.`); clearAlert('poierr');
  } catch { addAlert('poierr','⚠️','POI προσωρινά μη διαθέσιμα','Η δημόσια υπηρεσία δεδομένων δεν απάντησε.'); }
}

function setupVoice() {
  const SR=window.SpeechRecognition||window.webkitSpeechRecognition;
  if(!SR){$('#voiceBtn').disabled=true;$('#voiceHint').textContent='Η φωνητική αναγνώριση δεν υποστηρίζεται σε αυτόν τον browser.';return;}
  const rec=new SR(); rec.lang='el-GR'; rec.interimResults=false; rec.maxAlternatives=1;
  $('#voiceBtn').addEventListener('click',()=>{try{rec.start();$('#voiceHint').textContent='Ακούω…';}catch{}});
  rec.onerror=()=>{$('#voiceHint').textContent='Δεν άκουσα καθαρά. Δοκίμασε ξανά.';};
  rec.onresult=e=>{const t=e.results[0][0].transcript.toLowerCase();$('#voiceHint').textContent=`Άκουσα: ${t}`;
    if(t.includes('βενζ'))findPOI('fuel'); else if(t.includes('φαρμακ'))findPOI('pharmacy'); else if(t.includes('εστια')||t.includes('φαγη'))findPOI('restaurant'); else if(t.includes('γυμνα'))findPOI('gym'); else if(t.includes('νοσοκο'))findPOI('hospital'); else if(t.includes('πάρκιν')||t.includes('parking'))findPOI('parking'); else {const q=t.replace(/πήγαινέ με|πήγαινε με|διαδρομή για|οδήγησέ με|προς/g,'').trim(); if(q)routeToQuery(q);}
  };
}

function bindSettings() {
  const map={voiceAlertsToggle:'voice',speedAlertsToggle:'speed',cameraAlertsToggle:'camera',weatherAlertsToggle:'weather'};
  for(const [id,key] of Object.entries(map)){const el=$(`#${id}`);if(!el)continue;el.checked=!!state.settings[key];el.addEventListener('change',()=>{state.settings[key]=el.checked;saveSettings();renderMonitor();});}
}
function renderMonitor() {
  const checks=[['Χάρτης',!!window.L],['GPS','geolocation'in navigator],['Ελληνική TTS','speechSynthesis'in window],['Voice input',!!(window.SpeechRecognition||window.webkitSpeechRecognition)],['Online',navigator.onLine],['Wake Lock','wakeLock'in navigator],['Routing',true],['POI / OSM',true],['Safety data / OSM',true],['Offline shell','serviceWorker'in navigator]];
  $('#monitorGrid').innerHTML=checks.map(([n,v])=>`<div class="monitor-item"><span>${n}</span><b class="${v?'ok':'warn'}">${v?'READY':'LIMITED'}</b></div>`).join('');
  const essentials=checks.slice(0,5).filter(x=>x[1]).length; $('#readyState').textContent=essentials>=4?'OPERATIONAL':'LIMITED';
}

$('#themeBtn').addEventListener('click',()=>document.body.classList.toggle('light'));
$('#routeBtn').addEventListener('click',()=>routeToQuery($('#destinationInput').value.trim()));
$('#destinationInput').addEventListener('keydown',e=>{if(e.key==='Enter')routeToQuery(e.target.value.trim());});
$$('[data-poi]').forEach(b=>b.addEventListener('click',()=>findPOI(b.dataset.poi)));
$('#freeDriveBtn').addEventListener('click',()=>{state.freeDrive=!state.freeDrive;$('#freeDriveBtn span').textContent=state.freeDrive?'Free Drive ON':'Free Drive';if(state.freeDrive){speak('Λειτουργία ελεύθερης οδήγησης ενεργή.','freedrive',5000);if(state.lastPos)state.map.setView(state.lastPos,16);} });
$('#menuBtn').addEventListener('click',()=>$('#menuDrawer').classList.remove('hidden'));
$('#closeMenuBtn').addEventListener('click',()=>$('#menuDrawer').classList.add('hidden'));
$('#centerMapBtn').addEventListener('click',()=>{if(state.lastPos)state.map.setView(state.lastPos,17);$('#menuDrawer').classList.add('hidden');});
document.addEventListener('click',e=>{const t=e.target;if(t.classList?.contains('poi-route'))routeTo({lat:+t.dataset.lat,lng:+t.dataset.lng,name:t.dataset.name});});
window.addEventListener('online',()=>{setNetworkState();renderMonitor();}); window.addEventListener('offline',()=>{setNetworkState();renderMonitor();});

initMap(); bindSettings(); setupVoice(); setNetworkState(); renderMonitor(); renderAlerts(); startGPS();
