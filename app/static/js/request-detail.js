window.OporaRequestDetail = (() => {
  let mapInstance = null;

  function destroy() {
    if (mapInstance) {
      mapInstance.remove();
      mapInstance = null;
    }
    const mapNode = document.getElementById("requestMap");
    if (mapNode) {
      mapNode._leaflet_id = null;
      mapNode.innerHTML = "";
    }
  }

  function init() {
    const mapNode = document.getElementById("requestMap");
    if (!mapNode || typeof L === "undefined") return;

    destroy();

    const address = document.getElementById("requestAddress")?.value ?? "";
    const latValue = document.getElementById("requestLat")?.value ?? "";
    const lngValue = document.getElementById("requestLng")?.value ?? "";

    const lat = latValue ? Number(latValue) : null;
    const lng = lngValue ? Number(lngValue) : null;
    if (lat === null || lng === null || Number.isNaN(lat) || Number.isNaN(lng)) return;

    if (typeof L.Icon?.Default?.mergeOptions === "function") {
      L.Icon.Default.mergeOptions({
        iconUrl: "/static/vendor/leaflet/images/marker-icon.png",
        iconRetinaUrl: "/static/vendor/leaflet/images/marker-icon-2x.png",
        shadowUrl: "/static/vendor/leaflet/images/marker-shadow.png",
      });
    }

    mapInstance = L.map(mapNode, { zoomControl: true });
    L.tileLayer("https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png", {
      maxZoom: 19,
      subdomains: "abcd",
      attribution: "&copy; OpenStreetMap &copy; CARTO",
    }).addTo(mapInstance);

    mapInstance.setView([lat, lng], 15);
    L.marker([lat, lng]).addTo(mapInstance).bindPopup(address || "Адрес заявки").openPopup();
    const refreshSize = () => mapInstance?.invalidateSize();
    mapInstance.whenReady(refreshSize);
    window.addEventListener("resize", refreshSize);
    setTimeout(refreshSize, 250);
  }

  document.addEventListener("DOMContentLoaded", init);

  return { init, destroy };
})();
