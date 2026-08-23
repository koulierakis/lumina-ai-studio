(() => {
  'use strict';
  const SESSION_KEY = 'lumina-drive-session-v1';
  const BUILD_KEY = 'lumina-drive-build';
  const BUILD = '40';
  try {
    const previous = localStorage.getItem(BUILD_KEY);
    if (previous !== BUILD) {
      // v40 intentionally drops stale route/destination state from older builds.
      localStorage.removeItem(SESSION_KEY);
      sessionStorage.removeItem(SESSION_KEY);
      localStorage.removeItem('lumina-route-destination');
      localStorage.removeItem('lumina-drive-destination');
      sessionStorage.removeItem('lumina-route-destination');
      sessionStorage.removeItem('lumina-drive-destination');
      localStorage.setItem(BUILD_KEY, BUILD);
    }
  } catch {}
})();