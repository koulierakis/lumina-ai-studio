(() => {
  const SESSION_KEY='lumina-drive-session-v1';
  try {
    localStorage.removeItem(SESSION_KEY);
    sessionStorage.removeItem(SESSION_KEY);
    localStorage.setItem('lumina-drive-build','14');
  } catch {}
})();