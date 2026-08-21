(() => {
  if (!window.L || !L.circleMarker || L.circleMarker.__luminaWrapped) return;
  const original = L.circleMarker.bind(L);
  const wrapped = function (...args) {
    const marker = original(...args);
    const options = args[1] || {};
    if (options.fillColor === '#58ddd1' && Number(options.radius) === 9) {
      window.__luminaCurrentUserMarker = marker;
    }
    return marker;
  };
  wrapped.__luminaWrapped = true;
  L.circleMarker = wrapped;
})();