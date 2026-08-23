(() => {
  'use strict';
  const originalFetch = window.fetch.bind(window);
  const PRIMARY = 'https://overpass-api.de/api/interpreter';
  const FALLBACKS = [
    'https://overpass.kumi.systems/api/interpreter',
    'https://overpass.nchc.org.tw/api/interpreter'
  ];

  window.fetch = async (input, init) => {
    if (typeof input !== 'string' || !input.startsWith(PRIMARY)) {
      return originalFetch(input, init);
    }

    const suffix = input.slice(PRIMARY.length);
    let lastResponse = null;
    let lastError = null;

    for (const endpoint of [PRIMARY, ...FALLBACKS]) {
      try {
        const response = await originalFetch(endpoint + suffix, init);
        lastResponse = response;
        if (response.ok) return response;
        if (![408, 429, 500, 502, 503, 504].includes(response.status)) return response;
      } catch (error) {
        lastError = error;
      }
    }

    if (lastResponse) return lastResponse;
    throw lastError || new TypeError('Overpass services unavailable');
  };
})();
