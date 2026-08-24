(() => {
  'use strict';
  const originalFetch = window.fetch.bind(window);
  // Full pool of CORS-friendly Overpass mirrors. Order = priority.
  // Verified 2026-05: overpass-api.de + kumi.systems are the two most rate-limited
  // public instances (this was the production cause of empty Nearby POI results
  // around Kanali / Nea Thesi, Preveza). openstreetmap.fr, private.coffee and
  // maps.mail.ru serve fresh OSM data with permissive CORS.
  const POOL = [
    'https://overpass-api.de/api/interpreter',
    'https://overpass.kumi.systems/api/interpreter',
    'https://overpass.openstreetmap.fr/api/interpreter',
    'https://overpass.private.coffee/api/interpreter',
    'https://maps.mail.ru/osm/tools/overpass/api/interpreter'
  ];
  const OVERPASS_HOSTS = POOL.map(u => new URL(u).host);

  function matchOverpass(input) {
    if (typeof input !== 'string') return null;
    for (const ep of POOL) {
      if (input === ep) return { ep, suffix: '' };
      if (input.startsWith(ep + '?')) return { ep, suffix: input.slice(ep.length) };
    }
    // Also match by host so any /api/interpreter path is rotated
    try {
      const u = new URL(input);
      if (OVERPASS_HOSTS.includes(u.host) && u.pathname.endsWith('/api/interpreter')) {
        const ep = `${u.protocol}//${u.host}${u.pathname}`;
        return { ep, suffix: input.slice(ep.length) };
      }
    } catch {}
    return null;
  }

  window.fetch = async (input, init) => {
    const match = matchOverpass(input);
    if (!match) return originalFetch(input, init);

    // Priority: the endpoint the caller chose first, then the rest of the pool.
    const ordered = [match.ep, ...POOL.filter(e => e !== match.ep)];
    let lastResponse = null;
    let lastError = null;

    for (const endpoint of ordered) {
      try {
        const response = await originalFetch(endpoint + match.suffix, init);
        lastResponse = response;
        if (response.ok) return response;
        // Only rotate on transient failures; hard client errors are surfaced.
        if (![408, 425, 429, 500, 502, 503, 504].includes(response.status)) return response;
      } catch (error) {
        lastError = error;
      }
    }

    if (lastResponse) return lastResponse;
    throw lastError || new TypeError('Overpass services unavailable');
  };
})();
