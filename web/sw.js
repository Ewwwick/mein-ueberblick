// Minimaler Service Worker – nötig, damit Edge "Mein Überblick" als App installieren kann.
self.addEventListener('install', e => self.skipWaiting());
self.addEventListener('activate', e => self.clients.claim());
self.addEventListener('fetch', () => {});
