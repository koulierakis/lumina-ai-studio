const CACHE='lumina-drive-v32';
const CORE=[
  './index.html','./styles.css?v=32','./poi.css?v=32','./ui-fixes.css?v=32','./address-autocomplete.css?v=32','./app-v2.js?v=32','./walking-router.js?v=32','./poi-catalog.js?v=32','./address-autocomplete.js?v=32','./map-labels.js?v=32','./map-fallback.js?v=32','./user-marker-hook.js?v=32','./reverse-geocode-fallback.js?v=32','./overpass-fallback.js?v=32','./session-bootstrap.js?v=32','./drive-completion.js?v=32','./road-safety.js?v=32','./manifest.webmanifest?v=32'
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