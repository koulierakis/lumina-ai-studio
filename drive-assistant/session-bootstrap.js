(() => {
  'use strict';
  const SESSION_KEY = 'lumina-drive-session-v1';
  const BUILD_KEY = 'lumina-drive-build';
  const BUILD = '26';
  try {
    const previous = localStorage.getItem(BUILD_KEY);
    if (!previous) {
      // First run after the legacy builds: discard only unknown pre-versioned state once.
      localStorage.removeItem(SESSION_KEY);
      sessionStorage.removeItem(SESSION_KEY);
    }
    localStorage.setItem(BUILD_KEY, BUILD);
  } catch {}
})();
