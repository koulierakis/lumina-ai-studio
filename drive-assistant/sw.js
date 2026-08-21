const CACHE='lumina-drive-v17';
const CORE=['./styles.css?v=17','./poi.css?v=17','./ui-fixes.css?v=17','./address-autocomplete.css?v=17','./app-v2.js?v=17','./walking-router.js?v=17','./poi-catalog.js?v=17','./address-autocomplete.js?v=17','./map-labels.js?v=17','./map-fallback.js?v=17','./user-marker-hook.js?v=17','./session-bootstrap.js?v=17','./manifest.webmanifest?v=17'];
self.addEventListener('install',event=>event.waitUntil(caches.open(CACHE).then(cache=>cache.addAll(CORE)).then(()=>self.skipWaiting())));
self.addEventListener('activate',event=>event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k!==CACHE).map(k=>caches.delete(k)))).then(()=>self.clients.claim())));
self.addEventListener('fetch',event=>{
  if(event.request.method!=='GET')return;
  const url=new URL(event.request.url),sameOrigin=url.origin===self.location.origin;
  if(event.request.mode==='navigate'||url.pathname.endsWith('/index.html')||url.pathname.endsWith('/')){
    event.respondWith(fetch(event.request,{cache:'no-store'}));
    return;
  }
  if(!sameOrigin){event.respondWith(fetch(event.request).catch(()=>caches.match(event.request)));return;}
  const isAppAsset=/\.(?:js|css|webmanifest)$/.test(url.pathname);
  if(isAppAsset){event.respondWith(fetch(event.request,{cache:'no-store'}).then(response=>{const copy=response.clone();caches.open(CACHE).then(cache=>cache.put(event.request,copy)).catch(()=>{});return response}).catch(()=>caches.match(event.request)));return;}
  event.respondWith(caches.match(event.request).then(hit=>hit||fetch(event.request)));
});