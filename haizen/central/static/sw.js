// Service worker mínimo: torna a central instalável como app.
// Não guarda nada em cache. Tudo vem sempre do seu PC, para nunca mostrar
// números velhos de faturamento como se fossem de agora.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", () => { /* deixa a rede responder */ });
