(() => {
  const BUILD = '12';
  const BUILD_KEY = 'lumina-drive-build';
  const SESSION_KEY = 'lumina-drive-session-v1';
  try {
    const previousBuild = localStorage.getItem(BUILD_KEY);
    if (previousBuild !== BUILD) {
      localStorage.removeItem(SESSION_KEY);
      sessionStorage.removeItem(SESSION_KEY);
      localStorage.setItem(BUILD_KEY, BUILD);
    }
  } catch {}
})();
