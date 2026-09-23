/* Загрузка MapLibre и создание карты с корректным resize, в том числе в скрытом контейнере. */
window.OporaMapKit = window.OporaMapKit || {};
(() => {
  const kit = window.OporaMapKit;
  let assetPromise = null;

  kit.ensureAssets = function ensureAssets() {
    if (window.maplibregl) return Promise.resolve(window.maplibregl);
    if (assetPromise) return assetPromise;
    const base = kit.readConfig().assetBase;
    assetPromise = new Promise((resolve, reject) => {
      let css = document.querySelector("link[data-opora-maplibre]");
      if (!css) {
        css = document.createElement("link");
        css.rel = "stylesheet";
        css.href = `${base}/maplibre-gl.css`;
        css.dataset.oporaMaplibre = "1";
        document.head.append(css);
      }
      let script = document.querySelector("script[data-opora-maplibre]");
      if (!script) {
        script = document.createElement("script");
        script.src = `${base}/maplibre-gl.js`;
        script.dataset.oporaMaplibre = "1";
        document.head.append(script);
      }
      const ready = () => (window.maplibregl ? resolve(window.maplibregl) : reject(new Error("MapLibre unavailable")));
      if (window.maplibregl) ready();
      else {
        script.addEventListener("load", ready, { once: true });
        script.addEventListener("error", () => reject(new Error("MapLibre load failed")), { once: true });
      }
    }).catch((error) => {
      assetPromise = null;
      throw error;
    });
    return assetPromise;
  };

  kit.createMap = function createMap(container, options = {}) {
    const cfg = kit.readConfig();
    return kit.ensureAssets().then((lib) => new Promise((resolve, reject) => {
      if (!container) {
        reject(new Error("map container missing"));
        return;
      }
      const map = new lib.Map({
        container,
        style: options.style || cfg.styleUrl,
        center: options.center || cfg.center,
        zoom: options.zoom ?? cfg.zoom,
        minZoom: options.minZoom ?? cfg.minZoom,
        maxZoom: options.maxZoom ?? cfg.maxZoom,
        attributionControl: true,
      });
      map.addControl(new lib.NavigationControl({ showCompass: false }), "top-left");
      const resize = () => map.resize();
      const observer = window.ResizeObserver ? new ResizeObserver(resize) : null;
      observer?.observe(container);
      window.addEventListener("resize", resize);
      const failTimer = window.setTimeout(() => {
        if (!map.loaded()) options.onError?.("Не удалось загрузить карту. Проверьте style URL и подключение.");
      }, 12000);
      map.on("load", () => {
        window.clearTimeout(failTimer);
        resize();
        resolve(map);
      });
      map.on("error", (event) => {
        if (map.loaded() || !event?.error) return;
        options.onError?.(event.error.message || "Не удалось загрузить карту.");
      });
      map._oporaCleanup = () => {
        window.clearTimeout(failTimer);
        observer?.disconnect();
        window.removeEventListener("resize", resize);
      };
      requestAnimationFrame(() => requestAnimationFrame(resize));
    }));
  };

  kit.destroyMap = function destroyMap(map) {
    if (!map) return;
    map._oporaCleanup?.();
    map.remove();
  };
})();
