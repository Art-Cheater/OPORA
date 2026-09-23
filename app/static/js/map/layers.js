/* Слои работ, маршрута и подъездов. Подъезды только на крупном масштабе. */
window.OporaMapKit = window.OporaMapKit || {};
window.OporaMapKit.collection = function collection(rows) {
  return {
    type: "FeatureCollection",
    features: (rows || []).map((point) => window.OporaMapKit.pointFeature(point)).filter(Boolean),
  };
};

window.OporaMapKit.addWorkLayers = function addWorkLayers(map) {
  map.addSource("opora-works", {
    type: "geojson",
    data: window.OporaMapKit.collection([]),
    cluster: true,
    clusterMaxZoom: 14,
    clusterRadius: 48,
  });
  map.addLayer({
    id: "opora-clusters",
    type: "circle",
    source: "opora-works",
    filter: ["has", "point_count"],
    paint: {
      "circle-color": "#344054",
      "circle-radius": ["step", ["get", "point_count"], 18, 20, 23, 100, 29],
      "circle-stroke-width": 2,
      "circle-stroke-color": "#ffffff",
    },
  });
  map.addLayer({
    id: "opora-cluster-count",
    type: "symbol",
    source: "opora-works",
    filter: ["has", "point_count"],
    layout: {
      "text-field": ["get", "point_count_abbreviated"],
      "text-font": ["Noto Sans Bold", "Noto Sans Regular"],
      "text-size": 12,
    },
    paint: { "text-color": "#ffffff" },
  });
  map.addLayer({
    id: "opora-points",
    type: "circle",
    source: "opora-works",
    filter: ["!", ["has", "point_count"]],
    paint: {
      "circle-radius": ["case", ["get", "in_plan"], 10, 8],
      "circle-color": ["get", "color"],
      "circle-stroke-width": 2,
      "circle-stroke-color": "#ffffff",
      "circle-opacity": 0.96,
    },
  });
  map.addSource("opora-selected", { type: "geojson", data: window.OporaMapKit.collection([]) });
  map.addLayer({
    id: "opora-selected-point",
    type: "circle",
    source: "opora-selected",
    paint: {
      "circle-radius": 14,
      "circle-color": "transparent",
      "circle-stroke-width": 3,
      "circle-stroke-color": "#111827",
    },
  });
  map.addSource("opora-route", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
  map.addLayer({
    id: "opora-route-line",
    type: "line",
    source: "opora-route",
    paint: { "line-color": "#c45c26", "line-width": 5, "line-opacity": 0.9 },
  });
  map.addSource("opora-entrances", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
  map.addLayer({
    id: "opora-entrances",
    type: "circle",
    source: "opora-entrances",
    minzoom: window.OporaMapKit.readConfig().entranceMinZoom,
    paint: {
      "circle-radius": 4,
      "circle-color": "#7c3aed",
      "circle-stroke-width": 1,
      "circle-stroke-color": "#ffffff",
    },
  });
};
