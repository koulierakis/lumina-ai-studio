const CACHE='lumina-drive-v30';
const CORE=[
  './index.html','./styles.css?v=30','./poi.css?v=30','./ui-fixes.css?v=30','./address-autocomplete.css?v=30','./app-v2.js?v=30','./walking-router.js?v=30','./poi-catalog.js?v=30','./address-autocomplete.js?v=30','./map-labels.js?v=30','./map-fallback.js?v=30','./user-marker-hook.js?v=30','./reverse-geocode-fallback.js?v=30','./overpass-fallback.js?v=30','./session-bootstrap.js?v=30','./drive-completion.js?v=30','./road-safety.js?v=30','./manifest.webmanifest?v=30'
];
self.addEventListener('install',event=>event.waitUntil(caches.open(CACHE).then(cache=>cache.addAll(CORE)).then(()=>self.skipWaiting())));
self.addEventListener('activate',event=>event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k!==CACHE).map(k=>caches.delete(k)))).then(()=>self.clients.claim())));
self.addEventListener('fetch',event=>{
 if(event.request.method!=='GET')return;const url=new URL(event.request.url),sameOrigin=url.origin===self.location.origin;
 if(event.request.mode==='navigate'||url.pathname.endsWith('/index.html')||url.pathname.endsWith('/')){event.respondWith(fetch(event.request,{cache:'no-store'}).then(response=>{if(response&&response.ok){const copy=response.clone();caches.open(CACHE).then(cache=>cache.put('./index.html',copy)).catch(()=>{});}return response;}).catch(()=>caches.match('./index.html')));return;}
 if(!sameOrigin){event.respondWith(fetch(event.request).catch(()=>caches.match(event.request)));return;}
 const isAppAsset=/\.(?:js|css|webmanifest)$/.test(url.pathname);if(isAppAsset){event.respondWith(fetch(event.request,{cache:'no-store'}).then(response=>{const copy=response.clone();caches.open(CACHE).then(cache=>cache.put(event.request,copy)).catch(()=>{});return response}).catch(()=>caches.match(event.request)));return;}
 event.respondWith(caches.match(event.request).then(hit=>hit||fetch(event.request)));
});