(() => {
  const mapNode = document.getElementById("requestMap");
  if (!mapNode || typeof L === "undefined") return;

  const address = document.getElementById("requestAddress")?.value ?? "";
  const latValue = document.getElementById("requestLat")?.value ?? "";
  const lngValue = document.getElementById("requestLng")?.value ?? "";

  const lat = latValue ? Number(latValue) : null;
  const lng = lngValue ? Number(lngValue) : null;

  const map = L.map("requestMap", { zoomControl: true });
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "&copy; OpenStreetMap contributors",
  }).addTo(map);

  function setPoint(latitude, longitude, label) {
    map.setView([latitude, longitude], 15);
    L.marker([latitude, longitude]).addTo(map).bindPopup(label).openPopup();
  }

  async function geocodeByAddress() {
    if (!address) {
      map.setView([55.751244, 37.618423], 10);
      return;
    }
    try {
      const query = encodeURIComponent(address);
      const response = await fetch(
        `https://nominatim.openstreetmap.org/search?format=json&limit=1&q=${query}`
      );
      const data = await response.json();
      if (Array.isArray(data) && data.length > 0) {
        setPoint(Number(data[0].lat), Number(data[0].lon), address);
      } else {
        map.setView([55.751244, 37.618423], 10);
      }
    } catch (_err) {
      map.setView([55.751244, 37.618423], 10);
    }
  }

  if (lat !== null && lng !== null && !Number.isNaN(lat) && !Number.isNaN(lng)) {
    setPoint(lat, lng, address || "Адрес заявки");
  } else {
    geocodeByAddress();
  }
})();
