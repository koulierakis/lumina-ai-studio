const CACHE='lumina-drive-v31';
const CORE=[
  './index.html','./styles.css?v=31','./poi.css?v=31','./ui-fixes.css?v=31','./address-autocomplete.css?v=31','./app-v2.js?v=31','./walking-router.js?v=31','./poi-catalog.js?v=31','./address-autocomplete.js?v=31','./map-labels.js?v=31','./map-fallback.js?v=31','./user-marker-hook.js?v=31','./reverse-geocode-fallback.js?v=31','./overpass-fallback.js?v=31','./session-bootstrap.js?v=31','./drive-completion.js?v=31','./road-safety.js?v=31','./manifest.webmanifest?v=31'
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