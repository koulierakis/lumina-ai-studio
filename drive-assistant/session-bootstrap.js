(() => {
  const SESSION_KEY = 'lumina-drive-session-v1';
  try {
    // A full page load is a fresh Drive session. This prevents stale routes,
    // destinations and maneuver cards from a previous trip from reappearing.
    localStorage.removeItem(SESSION_KEY);
    sessionStorage.removeItem(SESSION_KEY);
    localStorage.setItem('lumina-drive-build', '13');
  } catch {}
})();
