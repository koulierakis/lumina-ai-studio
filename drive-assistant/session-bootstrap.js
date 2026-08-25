(() => {
  'use strict';
  const SESSION_KEY = 'lumina-drive-session-v1';
  const BUILD_KEY = 'lumina-drive-build';
  const BUILD = '58';
  try {
    const previous = localStorage.getItem(BUILD_KEY);
    if (previous !== BUILD) {
      localStorage.removeItem(SESSION_KEY);
      sessionStorage.removeItem(SESSION_KEY);
      localStorage.removeItem('lumina-route-destination');
      localStorage.removeItem('lumina-drive-destination');
      sessionStorage.removeItem('lumina-route-destination');
      sessionStorage.removeItem('lumina-drive-destination');
      localStorage.setItem(BUILD_KEY, BUILD);
    } else {
      const raw = localStorage.getItem(SESSION_KEY);
      if (raw) {
        const s = JSON.parse(raw);
        if (s && typeof s === 'object' && s.handsFree) {
          s.handsFree = false;
          localStorage.setItem(SESSION_KEY, JSON.stringify(s));
        }
      }
    }
  } catch {}
})();