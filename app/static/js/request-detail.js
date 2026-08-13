(() => {
  const mapNode = document.getElementById("requestMap");
  if (!mapNode || typeof L === "undefined") return;

  const address = document.getElementById("requestAddress")?.value ?? "";
  const latValue = document.getElementById("requestLat")?.value ?? "";
  const lngValue = document.getElementById("requestLng")?.value ?? "";

  const lat = latValue ? Number(latValue) : null;
  const lng = lngValue ? Number(lngValue) : null;
  if (lat === null || lng === null || Number.isNaN(lat) || Number.isNaN(lng)) return;

  const map = L.map("requestMap", { zoomControl: true });
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "&copy; OpenStreetMap contributors",
  }).addTo(map);

  map.setView([lat, lng], 15);
  L.marker([lat, lng]).addTo(map).bindPopup(address || "Адрес заявки").openPopup();
})();
