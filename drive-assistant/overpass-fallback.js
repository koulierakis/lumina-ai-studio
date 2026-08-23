(() => {
  'use strict';
  const originalFetch = window.fetch.bind(window);
  const PRIMARY = 'https://overpass-api.de/api/interpreter';
  const FALLBACKS = [
    'https://overpass.kumi.systems/api/interpreter',
    'https://overpass.nchc.org.tw/api/interpreter'
  ];

  function requestUrl(input) {
    return typeof input === 'string' ? input : input?.url || '';
  }

  async function tryEndpoint(url, input, init) {
    if (typeof input === 'string') return originalFetch(url, init);
    const request = new Request(input, init);
    return originalFetch(new Request(url, request));
  }

  window.fetch = async (input, init) => {
    const url = requestUrl(input);
    if (!url.startsWith(PRIMARY)) return originalFetch(input, init);

    let lastResponse = null;
    let lastError = null;
    const candidates = [PRIMARY, ...FALLBACKS];
    const suffix = url.slice(PRIMARY.length);

    for (const endpoint of candidates) {
      try {
        const response = await tryEndpoint(endpoint + suffix, input, init);
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
