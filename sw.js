const CACHE='trio-paper-__BUILD_VERSION__';
const SHELL=['./','./index.html','./styles.css','./app.js','./view-state.js','./icon.svg','./manifest.webmanifest'];
self.addEventListener('install',e=>e.waitUntil(caches.open(CACHE).then(c=>c.addAll(SHELL)).then(()=>self.skipWaiting())));
self.addEventListener('activate',e=>e.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k!==CACHE).map(k=>caches.delete(k)))).then(()=>self.clients.claim())));
self.addEventListener('fetch',e=>{
 if(e.request.method!=='GET'||new URL(e.request.url).origin!==self.location.origin)return;
 const u=new URL(e.request.url);
 // Research JSON never falls back to cached results, including offline.
 if(u.pathname.endsWith('.json')){e.respondWith(fetch(e.request,{cache:'no-store'}));return;}
 e.respondWith(fetch(e.request).catch(()=>caches.match(u.pathname).then(r=>r|| (e.request.mode==='navigate'?caches.match('./index.html'):Response.error()))));
});
