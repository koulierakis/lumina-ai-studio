const CACHE='lumina-drive-v66';
self.addEventListener('install',event=>{self.skipWaiting();event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k.startsWith('lumina-drive-')).map(k=>caches.delete(k)))));});
self.addEventListener('activate',event=>{event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k.startsWith('lumina-drive-')).map(k=>caches.delete(k)))).then(()=>self.clients.claim()));});
self.addEventListener('fetch',event=>{
  if(event.request.method!=='GET')return;
  const url=new URL(event.request.url);
  const sameOrigin=url.origin===self.location.origin;
  if(!sameOrigin){event.respondWith(fetch(event.request));return;}
  event.respondWith(fetch(event.request,{cache:'no-store'}));
});