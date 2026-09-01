import assert from 'node:assert/strict';

const headers = {
  Accept: 'application/json',
  'User-Agent': 'LUMINA-Drive-runtime-services-smoke/1.0',
};

async function getJson(url, timeoutMs = 20000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, { headers, signal: controller.signal });
    assert.equal(response.ok, true, `${url} -> HTTP ${response.status}`);
    return response.json();
  } finally {
    clearTimeout(timer);
  }
}

// Real public routing path used by the browser app. Two points inside Trikala are
// intentionally used so the smoke test validates a normal urban driving route
// without pretending to validate real GPS, maneuver timing or driving behavior.
const start = { lat: 39.5556, lon: 21.7679 };
const end = { lat: 39.5599, lon: 21.7708 };
const osrm = new URL(`https://router.project-osrm.org/route/v1/driving/${start.lon},${start.lat};${end.lon},${end.lat}`);
osrm.searchParams.set('overview', 'full');
osrm.searchParams.set('steps', 'true');
osrm.searchParams.set('geometries', 'geojson');
const route = await getJson(osrm);
assert.equal(route.code, 'Ok', `OSRM route code=${route.code}`);
assert.ok(Array.isArray(route.routes) && route.routes.length > 0, 'OSRM returned no route');
assert.ok(route.routes[0].distance > 0, 'OSRM route distance is not positive');
assert.ok(route.routes[0].duration > 0, 'OSRM route duration is not positive');
assert.ok((route.routes[0].legs?.[0]?.steps || []).length > 0, 'OSRM returned no maneuver steps');

// Live weather provider used by Drive for road-weather awareness.
const weather = new URL('https://api.open-meteo.com/v1/forecast');
weather.searchParams.set('latitude', String(start.lat));
weather.searchParams.set('longitude', String(start.lon));
weather.searchParams.set('current', 'temperature_2m,precipitation,wind_speed_10m');
weather.searchParams.set('timezone', 'auto');
const weatherData = await getJson(weather);
assert.ok(weatherData.current, 'Open-Meteo returned no current conditions');
for (const key of ['temperature_2m', 'precipitation', 'wind_speed_10m']) {
  assert.ok(Number.isFinite(Number(weatherData.current[key])), `Open-Meteo current.${key} invalid`);
}

console.log(`PASS live OSRM route=${Math.round(route.routes[0].distance)}m steps=${route.routes[0].legs[0].steps.length} weather=OK`);
console.log('NOT PROVEN HERE: physical GPS accuracy, live maneuver timing, real deviation rerouting, microphone/TTS audibility, background return, Wake Lock or local safety-data coverage.');
