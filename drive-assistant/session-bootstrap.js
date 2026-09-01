(() => {
  'use strict';
  const SESSION_KEY = 'lumina-drive-session-v1';
  const BUILD_KEY = 'lumina-drive-build';
  const BUILD = '66';

  function showBuildMarker(text = `LIVE v${BUILD}`) {
    if (document.getElementById('luminaBuildMarker')) return;
    const marker = document.createElement('div');
    marker.id = 'luminaBuildMarker';
    marker.textContent = text;
    marker.setAttribute('aria-label', 'LUMINA live build');
    Object.assign(marker.style, {
      position: 'fixed', top: '6px', left: '50%', transform: 'translateX(-50%)',
      zIndex: '99999', padding: '3px 8px', borderRadius: '999px',
      background: 'rgba(7,17,31,.88)', color: '#58ddd1',
      border: '1px solid rgba(88,221,209,.5)', font: '700 10px/1.2 system-ui,sans-serif',
      letterSpacing: '.08em', pointerEvents: 'none'
    });
    document.addEventListener('DOMContentLoaded', () => document.body.appendChild(marker), { once: true });
    if (document.body) document.body.appendChild(marker);
  }

  async function purgeOldClientCaches() {
    try {
      if ('serviceWorker' in navigator) {
        const regs = await navigator.serviceWorker.getRegistrations();
        await Promise.all(regs.map(reg => reg.unregister().catch(() => false)));
      }
      if ('caches' in window) {
        const names = await caches.keys();
        await Promise.all(names.filter(name => name.startsWith('lumina-drive-')).map(name => caches.delete(name)));
      }
    } catch {}
  }

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

  showBuildMarker();
  purgeOldClientCaches().finally(() => {
    try {
      const reloadKey = `lumina-fresh-reload-v${BUILD}`;
      if (!sessionStorage.getItem(reloadKey)) {
        sessionStorage.setItem(reloadKey, '1');
        const u = new URL(location.href);
        u.searchParams.set('fresh', BUILD);
        u.searchParams.set('_', Date.now().toString());
        location.replace(u.toString());
      }
    } catch {}
  });
})();