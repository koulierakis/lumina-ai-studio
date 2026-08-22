(() => {
  'use strict';
  const SESSION_KEY = 'lumina-drive-session-v1';
  const BUILD_KEY = 'lumina-drive-build';
  const BUILD = '26';
  try {
    const previous = localStorage.getItem(BUILD_KEY);
    if (previous !== BUILD) {
      // Clear incompatible legacy state once on upgrade, then preserve sessions on normal reloads.
      localStorage.removeItem(SESSION_KEY);
      sessionStorage.removeItem(SESSION_KEY);
      localStorage.setItem(BUILD_KEY, BUILD);
    }
  } catch {}
})();
