const CACHE='lumina-drive-v28';
const CORE=[
  './index.html','./styles.css?v=28','./poi.css?v=28','./ui-fixes.css?v=28','./address-autocomplete.css?v=28','./app-v2.js?v=28','./walking-router.js?v=28','./poi-catalog.js?v=28','./address-autocomplete.js?v=28','./map-labels.js?v=28','./map-fallback.js?v=28','./user-marker-hook.js?v=28','./reverse-geocode-fallback.js?v=28','./session-bootstrap.js?v=28','./drive-completion.js?v=28','./road-safety.js?v=28','./manifest.webmanifest?v=28'
];
self.addEventListener('install',event=>event.waitUntil(caches.open(CACHE).then(cache=>cache.addAll(CORE)).then(()=>self.skipWaiting())));
self.addEventListener('activate',event=>event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k!==CACHE).map(k=>caches.delete(k)))).then(()=>self.clients.claim())));
self.addEventListener('fetch',event=>{
 if(event.request.method!=='GET')return;const url=new URL(event.request.url),sameOrigin=url.origin===self.location.origin;
 if(event.request.mode==='navigate'||url.pathname.endsWith('/index.html')||url.pathname.endsWith('/')){event.respondWith(fetch(event.request,{cache:'no-store'}).then(response=>{if(response&&response.ok){const copy=response.clone();caches.open(CACHE).then(cache=>cache.put('./index.html',copy)).catch(()=>{});}return response;}).catch(()=>caches.match('./index.html')));return;}
 if(!sameOrigin){event.respondWith(fetch(event.request).catch(()=>caches.match(event.request)));return;}
 const isAppAsset=/\.(?:js|css|webmanifest)$/.test(url.pathname);if(isAppAsset){event.respondWith(fetch(event.request,{cache:'no-store'}).then(response=>{const copy=response.clone();caches.open(CACHE).then(cache=>cache.put(event.request,copy)).catch(()=>{});return response;}).catch(()=>caches.match(event.request)));return;}
 event.respondWith(caches.match(event.request).then(hit=>hit||fetch(event.request)));
});