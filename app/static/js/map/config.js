/* Общие настройки карты. Значения приходят из meta, не из адреса тайлов в каждом файле. */
window.OporaMapKit = window.OporaMapKit || {};
window.OporaMapKit.readConfig = function () {
  const meta = (name) => document.querySelector(`meta[name="${name}"]`)?.content || "";
  const parts = meta("opora-map-center").split(",").map(Number);
  const center = parts.length === 2 && parts.every(Number.isFinite) ? parts : [49.668, 58.6035];
  const number = (name, fallback) => {
    const value = Number(meta(name));
    return Number.isFinite(value) ? value : fallback;
  };
  return {
    styleUrl: meta("opora-maplibre-style") || "https://tiles.openfreemap.org/styles/liberty",
    center,
    zoom: number("opora-map-zoom", 12),
    minZoom: number("opora-map-min-zoom", 8),
    maxZoom: number("opora-map-max-zoom", 20),
    entranceMinZoom: number("opora-entrance-zoom", 17),
    assetBase: "/static/vendor/maplibre",
  };
};
