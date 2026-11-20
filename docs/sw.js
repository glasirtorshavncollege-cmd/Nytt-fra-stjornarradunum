const CACHE='ministry-check-v8';
const CORE=['./','./index.html','./manifest.webmanifest','./icon.svg','./apple-touch-icon.png'];
self.addEventListener('install',event=>{event.waitUntil(caches.open(CACHE).then(cache=>cache.addAll(CORE)));self.skipWaiting()});
self.addEventListener('activate',event=>{event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k!==CACHE).map(k=>caches.delete(k)))));self.clients.claim()});
self.addEventListener('fetch',event=>{if(event.request.method!=='GET')return;const url=new URL(event.request.url);if(url.origin!==self.location.origin)return;if(url.pathname.endsWith('/feed.json')){event.respondWith(fetch(event.request,{cache:'no-store'}));return}if(event.request.mode==='navigate'){event.respondWith(fetch(event.request).catch(()=>caches.match('./index.html')));return}event.respondWith(caches.match(event.request).then(cached=>cached||fetch(event.request)))});

self.addEventListener('push',event=>{
  let payload={title:'Nýtt frá ráðunum',body:'Nýggj tíðindi eru komin.'};
  try{if(event.data)payload={...payload,...event.data.json()}}catch{}
  const link=payload.articleId?'./?article='+encodeURIComponent(payload.articleId):'./';
  event.waitUntil(self.registration.showNotification(payload.title,{
    body:payload.body,icon:'./apple-touch-icon.png',badge:'./icon.svg',tag:'ministry-news-'+(payload.articleId||'latest'),data:{url:new URL(link,self.registration.scope).href}
  }));
});
self.addEventListener('notificationclick',event=>{
  event.notification.close();
  const target=event.notification.data?.url||self.registration.scope;
  event.waitUntil(clients.matchAll({type:'window',includeUncontrolled:true}).then(windows=>{
    const found=windows.find(c=>new URL(c.url).origin===new URL(target).origin);
    if(found){return found.navigate(target).then(c=>c.focus())}
    return clients.openWindow(target);
  }));
});
