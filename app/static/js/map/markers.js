/* Цвета маркеров: заявка, дефект, деревня, план, рядом, объект. */
window.OporaMapKit = window.OporaMapKit || {};
window.OporaMapKit.markerColor = function markerColor(point) {
  const code = String(point.status_code || "");
  const inPlan = point.in_plan === true || point.in_plan === "true";
  const nearby = point.nearby === true || point.nearby === "true";
  if (code === "completed" || code === "cancelled" || code === "fixed") return "#6b7280";
  if (inPlan) return "#198754";
  if (nearby) return "#0f766e";
  if (point.kind === "village" || point.type === "village") return "#b45309";
  if (point.type === "defect") return "#dc2626";
  if (point.type === "object") return "#0369a1";
  if (point.type === "agreement") return "#7c3aed";
  return "#2563eb";
};

window.OporaMapKit.pointFeature = function pointFeature(point) {
  const lat = Number(point.lat);
  const lng = Number(point.lng);
  if (!Number.isFinite(lat) || !Number.isFinite(lng)) return null;
  const type = point.type || point.entity_type || "request";
  const inPlan = point.in_plan === true || point.in_plan === "true";
  return {
    type: "Feature",
    geometry: { type: "Point", coordinates: [lng, lat] },
    properties: {
      ...point,
      type,
      id: String(point.id || point.entity_id || ""),
      in_plan: inPlan,
      color: window.OporaMapKit.markerColor({ ...point, type, in_plan: inPlan }),
    },
  };
};

window.OporaMapKit.escapeHtml = function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[char]));
};
