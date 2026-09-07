/* 앱으로 설치했을 때 화면 껍데기를 캐시해 두는 서비스 워커.
 *
 * 캐시하는 것은 정적 파일뿐이다. 변환 API(/api/…)와 결과 파일은 절대 캐시하지
 * 않는다. 진행 상황이 멈춘 것처럼 보이거나 남의 결과가 보일 수 있기 때문이다.
 */
"use strict";

const CACHE = "scan2doc-shell-v1";
const SHELL = [
  "/",
  "/static/style.css",
  "/static/app.js",
  "/static/icon.svg",
  "/manifest.webmanifest",
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((names) =>
      Promise.all(names.filter((n) => n !== CACHE).map((n) => caches.delete(n))))
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  const url = new URL(request.url);
  const isApi = url.pathname.startsWith("/api/");
  if (request.method !== "GET" || isApi || url.origin !== self.location.origin) return;

  // 네트워크를 먼저 쓰고, 안 되면 캐시로 버틴다.
  event.respondWith(
    fetch(request)
      .then((response) => {
        const copy = response.clone();
        caches.open(CACHE).then((cache) => cache.put(request, copy)).catch(() => {});
        return response;
      })
      .catch(() => caches.match(request).then((hit) => hit || caches.match("/")))
  );
});
