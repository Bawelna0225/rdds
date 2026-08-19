import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { forward as toMgrs } from "mgrs";

import "./styles.css";

const REFRESH_INTERVAL_MS = 2000;
const DEFAULT_CENTER = [52.2297, 21.0122];

const stateLabels = {
  new: "nowy",
  active: "aktywny",
  stale: "nieaktualny",
  ended: "zakończony",
  anomalous: "anomalia",
  no_gps: "brak GPS",
  online: "online",
  offline: "offline",
  disabled: "wyłączony",
  provisioning: "konfiguracja",
  acknowledged: "przyjęty",
  closed: "zamknięty",
};

const severityLabels = {
  low: "niski",
  medium: "średni",
  high: "wysoki",
  critical: "krytyczny",
};

const severityColors = {
  low: "#43d5ff",
  medium: "#ffb84d",
  high: "#ff4d5e",
  critical: "#ff2841",
};

const stateColors = {
  new: "#43d5ff",
  active: "#35e69a",
  stale: "#ffb84d",
  ended: "#778292",
  anomalous: "#ff4d5e",
  no_gps: "#b48cff",
};

const elements = {
  connectionDot: document.querySelector("#connection-dot"),
  connectionLabel: document.querySelector("#connection-label"),
  lastUpdate: document.querySelector("#last-update"),
  onlineSensors: document.querySelector("#online-sensors"),
  activeTracks: document.querySelector("#active-tracks"),
  openAlerts: document.querySelector("#open-alerts"),
  trackCount: document.querySelector("#track-count"),
  sensorCount: document.querySelector("#sensor-count"),
  alertCount: document.querySelector("#alert-count"),
  zoneCount: document.querySelector("#zone-count"),
  trackList: document.querySelector("#track-list"),
  sensorList: document.querySelector("#sensor-list"),
  alertList: document.querySelector("#alert-list"),
  zoneList: document.querySelector("#zone-list"),
  showEnded: document.querySelector("#show-ended"),
  showClosedAlerts: document.querySelector("#show-closed-alerts"),
  fitMap: document.querySelector("#fit-map"),
  selectionPanel: document.querySelector("#selection-panel"),
  selectionTitle: document.querySelector("#selection-title"),
  selectionDetails: document.querySelector("#selection-details"),
  closeSelection: document.querySelector("#close-selection"),
};

const map = L.map("map", {
  center: DEFAULT_CENTER,
  zoom: 12,
  zoomControl: false,
  preferCanvas: true,
});

L.control.zoom({ position: "bottomright" }).addTo(map);

L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19,
  attribution: "&copy; OpenStreetMap contributors",
}).addTo(map);

const sensorMarkers = new Map();
const trackLayers = new Map();
const zoneLayers = new Map();
let currentSensors = [];
let currentTracks = [];
let currentZones = [];
let currentAlerts = [];
let selectedTrackId = null;
let selectedHistory = null;
let initialFitComplete = false;
let refreshInProgress = false;

function isCoordinate(value) {
  return typeof value === "number" && Number.isFinite(value);
}

function hasPosition(entity, prefix = "") {
  return (
    isCoordinate(entity[`${prefix}latitude`]) &&
    isCoordinate(entity[`${prefix}longitude`])
  );
}

function escapeHtml(value) {
  return String(value ?? "—")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatNumber(value, digits = 1, suffix = "") {
  if (!isCoordinate(value)) {
    return "—";
  }
  return `${value.toFixed(digits)}${suffix}`;
}

function formatTime(value) {
  if (!value) {
    return "—";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "—";
  }
  return date.toLocaleTimeString("pl-PL", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function formatMgrs(latitude, longitude) {
  if (!isCoordinate(latitude) || !isCoordinate(longitude)) {
    return "—";
  }
  try {
    return toMgrs([longitude, latitude], 5);
  } catch {
    return "—";
  }
}

function stateLabel(state) {
  return stateLabels[state] ?? state ?? "—";
}

function severityLabel(severity) {
  return severityLabels[severity] ?? severity ?? "—";
}

function openAlertCountForTrack(trackId) {
  return currentAlerts.filter(
    (alert) => alert.track_id === trackId && alert.state !== "closed",
  ).length;
}

function setConnection(online, message) {
  elements.connectionDot.className = `connection-dot ${online ? "online" : "offline"}`;
  elements.connectionLabel.textContent = message;
}

async function fetchJson(path) {
  const response = await fetch(path, {
    headers: { Accept: "application/json" },
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json();
}

function sensorIcon(status) {
  return L.divIcon({
    className: "",
    html: `<div class="sensor-marker ${escapeHtml(status)}"></div>`,
    iconSize: [18, 18],
    iconAnchor: [9, 9],
  });
}

function droneIcon(track) {
  const heading = isCoordinate(track.heading_deg) ? track.heading_deg : 0;
  const state = track.state ?? "ended";
  const hasOpenAlert = currentAlerts.some(
    (alert) => alert.track_id === track.id && alert.state !== "closed",
  );
  return L.divIcon({
    className: "",
    html: `<div class="drone-marker ${escapeHtml(state)}${hasOpenAlert ? " alerting" : ""}" style="--heading:${heading}deg"></div>`,
    iconSize: [32, 32],
    iconAnchor: [16, 16],
  });
}

function pilotIcon() {
  return L.divIcon({
    className: "",
    html: '<div class="pilot-marker"></div>',
    iconSize: [14, 14],
    iconAnchor: [7, 7],
  });
}

function sensorPopup(sensor) {
  return `
    <h3 class="popup-title">${escapeHtml(sensor.display_name)}</h3>
    <div class="popup-grid">
      <span>ID</span><strong>${escapeHtml(sensor.sensor_id)}</strong>
      <span>Status</span><strong>${escapeHtml(stateLabel(sensor.status))}</strong>
      <span>MGRS</span><strong>${escapeHtml(formatMgrs(sensor.latitude, sensor.longitude))}</strong>
      <span>Ostatni kontakt</span><strong>${escapeHtml(formatTime(sensor.last_seen_at))}</strong>
    </div>`;
}

function trackPopup(track) {
  return `
    <h3 class="popup-title">${escapeHtml(track.basic_id || track.identity_key)}</h3>
    <div class="popup-grid">
      <span>Status</span><strong>${escapeHtml(stateLabel(track.state))}</strong>
      <span>Wysokość</span><strong>${escapeHtml(formatNumber(track.altitude_m, 1, " m"))}</strong>
      <span>Prędkość</span><strong>${escapeHtml(formatNumber(track.speed_mps, 1, " m/s"))}</strong>
      <span>Kierunek</span><strong>${escapeHtml(formatNumber(track.heading_deg, 0, "°"))}</strong>
      <span>Sensory</span><strong>${escapeHtml(track.contributing_sensors)}</strong>
      <span>Alarmy</span><strong>${escapeHtml(openAlertCountForTrack(track.id))}</strong>
      <span>MGRS</span><strong>${escapeHtml(formatMgrs(track.latitude, track.longitude))}</strong>
    </div>`;
}

function zonePopup(zone, hasOpenAlert) {
  return `
    <h3 class="popup-title">${escapeHtml(zone.name)}</h3>
    <div class="popup-grid">
      <span>Status</span><strong>${zone.active ? "aktywna" : "wyłączona"}</strong>
      <span>Zagrożenie</span><strong>${escapeHtml(severityLabel(zone.severity))}</strong>
      <span>Alarm</span><strong>${hasOpenAlert ? "otwarty" : "brak"}</strong>
      <span>Opis</span><strong>${escapeHtml(zone.description)}</strong>
    </div>`;
}

function updateZoneLayers(zones, alerts) {
  const visibleIds = new Set();
  const alertingZoneIds = new Set(
    alerts
      .filter((alert) => alert.state !== "closed")
      .map((alert) => alert.zone_id),
  );

  for (const zone of zones) {
    if (!zone.geometry) {
      continue;
    }

    visibleIds.add(zone.id);
    const hasOpenAlert = alertingZoneIds.has(zone.id);
    const color = hasOpenAlert
      ? severityColors[zone.severity] ?? severityColors.high
      : zone.active
        ? "#ffb84d"
        : "#778292";
    const style = {
      color,
      fillColor: color,
      fillOpacity: hasOpenAlert ? 0.22 : zone.active ? 0.08 : 0.03,
      opacity: zone.active ? 0.9 : 0.45,
      weight: hasOpenAlert ? 3 : 2,
      dashArray: hasOpenAlert ? null : "7 6",
    };
    let layer = zoneLayers.get(zone.id);

    if (!layer) {
      layer = L.geoJSON(zone.geometry, { style }).addTo(map);
      zoneLayers.set(zone.id, layer);
    } else {
      layer.setStyle(style);
    }
    layer.bindPopup(zonePopup(zone, hasOpenAlert));
  }

  for (const [id, layer] of zoneLayers) {
    if (!visibleIds.has(id)) {
      layer.remove();
      zoneLayers.delete(id);
    }
  }
}

function updateSensorMarkers(sensors) {
  const visibleIds = new Set();

  for (const sensor of sensors) {
    if (!hasPosition(sensor)) {
      continue;
    }
    visibleIds.add(sensor.id);
    const latLng = [sensor.latitude, sensor.longitude];
    let marker = sensorMarkers.get(sensor.id);

    if (!marker) {
      marker = L.marker(latLng, {
        icon: sensorIcon(sensor.status),
        zIndexOffset: 200,
      }).addTo(map);
      marker.on("click", () => map.panTo(marker.getLatLng()));
      sensorMarkers.set(sensor.id, marker);
    } else {
      marker.setLatLng(latLng);
      marker.setIcon(sensorIcon(sensor.status));
    }
    marker.bindPopup(sensorPopup(sensor));
  }

  for (const [id, marker] of sensorMarkers) {
    if (!visibleIds.has(id)) {
      marker.remove();
      sensorMarkers.delete(id);
    }
  }
}

function removeTrackLayer(id) {
  const layer = trackLayers.get(id);
  if (!layer) {
    return;
  }
  layer.marker?.remove();
  layer.pilot?.remove();
  layer.operatorLine?.remove();
  trackLayers.delete(id);
}

function updateTrackMarkers(tracks) {
  const visibleIds = new Set();

  for (const track of tracks) {
    if (!hasPosition(track)) {
      continue;
    }
    visibleIds.add(track.id);
    const droneLatLng = [track.latitude, track.longitude];
    const color = stateColors[track.state] ?? stateColors.ended;
    let layer = trackLayers.get(track.id);

    if (!layer) {
      const marker = L.marker(droneLatLng, {
        icon: droneIcon(track),
        zIndexOffset: 500,
      }).addTo(map);
      marker.on("click", () => selectTrack(track.id));
      layer = { marker, pilot: null, operatorLine: null };
      trackLayers.set(track.id, layer);
    } else {
      layer.marker.setLatLng(droneLatLng);
      layer.marker.setIcon(droneIcon(track));
    }
    layer.marker.bindPopup(trackPopup(track));

    if (hasPosition(track, "pilot_")) {
      const pilotLatLng = [track.pilot_latitude, track.pilot_longitude];
      if (!layer.pilot) {
        layer.pilot = L.marker(pilotLatLng, {
          icon: pilotIcon(),
          zIndexOffset: 350,
        }).addTo(map);
      } else {
        layer.pilot.setLatLng(pilotLatLng);
      }
      layer.pilot.bindPopup(
        `<h3 class="popup-title">Operator</h3><div class="popup-grid"><span>ID</span><strong>${escapeHtml(track.operator_id)}</strong><span>MGRS</span><strong>${escapeHtml(formatMgrs(track.pilot_latitude, track.pilot_longitude))}</strong></div>`,
      );

      const connection = [droneLatLng, pilotLatLng];
      if (!layer.operatorLine) {
        layer.operatorLine = L.polyline(connection, {
          color,
          weight: 1,
          opacity: 0.45,
          dashArray: "5 7",
        }).addTo(map);
      } else {
        layer.operatorLine.setLatLngs(connection);
        layer.operatorLine.setStyle({ color });
      }
    } else {
      layer.pilot?.remove();
      layer.operatorLine?.remove();
      layer.pilot = null;
      layer.operatorLine = null;
    }
  }

  for (const id of trackLayers.keys()) {
    if (!visibleIds.has(id)) {
      removeTrackLayer(id);
    }
  }
}

function createBadge(state) {
  const badge = document.createElement("span");
  badge.className = `state-badge state-${state}`;
  badge.textContent = stateLabel(state);
  return badge;
}

function createAlertBadge(state) {
  const badge = createBadge(state);
  badge.classList.add("alert-badge");
  return badge;
}

function renderAlertList(alerts) {
  elements.alertList.replaceChildren();
  elements.alertList.classList.toggle("empty-state", alerts.length === 0);

  if (alerts.length === 0) {
    elements.alertList.textContent = "Brak otwartych alarmów";
    return;
  }

  for (const alert of alerts) {
    const card = document.createElement("button");
    card.type = "button";
    card.className = `entity-card alert-card severity-${alert.severity} alert-${alert.state}`;
    card.addEventListener("click", () => {
      if (currentTracks.some((track) => track.id === alert.track_id)) {
        selectTrack(alert.track_id);
      } else if (hasPosition(alert)) {
        map.setView([alert.latitude, alert.longitude], Math.max(map.getZoom(), 15));
      }
    });

    const titleRow = document.createElement("div");
    titleRow.className = "entity-title-row";
    const title = document.createElement("span");
    title.className = "entity-title";
    title.textContent = alert.basic_id || alert.identity_key || alert.track_key;
    titleRow.append(title, createAlertBadge(alert.state));

    const meta = document.createElement("div");
    meta.className = "entity-meta";
    const zone = document.createElement("span");
    zone.textContent = alert.zone_name;
    const severity = document.createElement("span");
    severity.textContent = severityLabel(alert.severity);
    const time = document.createElement("span");
    time.textContent = formatTime(alert.last_detected_at);
    meta.append(zone, severity, time);

    card.append(titleRow, meta);
    elements.alertList.append(card);
  }
}

function renderTrackList(tracks) {
  elements.trackList.replaceChildren();
  elements.trackList.classList.toggle("empty-state", tracks.length === 0);

  if (tracks.length === 0) {
    elements.trackList.textContent = "Brak widocznych śladów";
    return;
  }

  for (const track of tracks) {
    const card = document.createElement("button");
    card.type = "button";
    card.className = `entity-card${track.id === selectedTrackId ? " selected" : ""}`;
    card.addEventListener("click", () => selectTrack(track.id));

    const titleRow = document.createElement("div");
    titleRow.className = "entity-title-row";
    const title = document.createElement("span");
    title.className = "entity-title";
    title.textContent = track.basic_id || track.identity_key || track.track_key;
    titleRow.append(title, createBadge(track.state));

    const meta = document.createElement("div");
    meta.className = "entity-meta";
    const altitude = document.createElement("span");
    altitude.textContent = formatNumber(track.altitude_m, 0, " m");
    const sensors = document.createElement("span");
    sensors.textContent = `${track.contributing_sensors} sensory`;
    const time = document.createElement("span");
    time.textContent = formatTime(track.last_seen_at);
    meta.append(altitude, sensors, time);

    card.append(titleRow, meta);
    elements.trackList.append(card);
  }
}

function renderSensorList(sensors) {
  elements.sensorList.replaceChildren();
  elements.sensorList.classList.toggle("empty-state", sensors.length === 0);

  if (sensors.length === 0) {
    elements.sensorList.textContent = "Brak skonfigurowanych sensorów";
    return;
  }

  for (const sensor of sensors) {
    const card = document.createElement("button");
    card.type = "button";
    card.className = "entity-card";
    card.addEventListener("click", () => {
      if (hasPosition(sensor)) {
        map.setView([sensor.latitude, sensor.longitude], Math.max(map.getZoom(), 14));
        sensorMarkers.get(sensor.id)?.openPopup();
      }
    });

    const titleRow = document.createElement("div");
    titleRow.className = "entity-title-row";
    const title = document.createElement("span");
    title.className = "entity-title";
    title.textContent = sensor.display_name || sensor.sensor_id;
    titleRow.append(title, createBadge(sensor.status));

    const meta = document.createElement("div");
    meta.className = "entity-meta";
    const identifier = document.createElement("span");
    identifier.textContent = sensor.sensor_id;
    const time = document.createElement("span");
    time.textContent = formatTime(sensor.last_seen_at);
    meta.append(identifier, time);

    card.append(titleRow, meta);
    elements.sensorList.append(card);
  }
}

function renderZoneList(zones, alerts) {
  elements.zoneList.replaceChildren();
  elements.zoneList.classList.toggle("empty-state", zones.length === 0);

  if (zones.length === 0) {
    elements.zoneList.textContent = "Brak zdefiniowanych stref";
    return;
  }

  const alertingZoneIds = new Set(
    alerts
      .filter((alert) => alert.state !== "closed")
      .map((alert) => alert.zone_id),
  );

  for (const zone of zones) {
    const card = document.createElement("button");
    card.type = "button";
    card.className = "entity-card";
    card.addEventListener("click", () => {
      const layer = zoneLayers.get(zone.id);
      if (layer) {
        map.fitBounds(layer.getBounds(), { padding: [45, 45], maxZoom: 16 });
        layer.openPopup();
      }
    });

    const titleRow = document.createElement("div");
    titleRow.className = "entity-title-row";
    const title = document.createElement("span");
    title.className = "entity-title";
    title.textContent = zone.name;
    titleRow.append(
      title,
      createBadge(zone.active ? "active" : "inactive"),
    );

    const meta = document.createElement("div");
    meta.className = "entity-meta";
    const severity = document.createElement("span");
    severity.textContent = `Poziom: ${severityLabel(zone.severity)}`;
    const status = document.createElement("span");
    status.textContent = alertingZoneIds.has(zone.id) ? "ALARM" : "spokojnie";
    meta.append(severity, status);

    card.append(titleRow, meta);
    elements.zoneList.append(card);
  }
}

function detailItem(label, value) {
  const item = document.createElement("div");
  item.className = "detail-item";
  const name = document.createElement("span");
  name.textContent = label;
  const content = document.createElement("strong");
  content.textContent = value ?? "—";
  item.append(name, content);
  return item;
}

function renderSelection(track) {
  if (!track) {
    elements.selectionPanel.classList.add("hidden");
    return;
  }

  elements.selectionPanel.classList.remove("hidden");
  elements.selectionTitle.textContent = track.basic_id || track.identity_key || track.track_key;
  elements.selectionDetails.replaceChildren(
    detailItem("Status", stateLabel(track.state)),
    detailItem("Operator", track.operator_id),
    detailItem("Wysokość", formatNumber(track.altitude_m, 1, " m")),
    detailItem("Prędkość", formatNumber(track.speed_mps, 1, " m/s")),
    detailItem("Kierunek", formatNumber(track.heading_deg, 0, "°")),
    detailItem("Sensory", String(track.contributing_sensors ?? "—")),
    detailItem("Otwarte alarmy", String(openAlertCountForTrack(track.id))),
    detailItem("Obserwacje", String(track.observation_count ?? "—")),
    detailItem("MGRS", formatMgrs(track.latitude, track.longitude)),
    detailItem("Pierwsza obserwacja", formatTime(track.first_seen_at)),
    detailItem("Ostatnia obserwacja", formatTime(track.last_seen_at)),
  );
}

async function refreshSelectedHistory() {
  if (!selectedTrackId) {
    return;
  }

  const payload = await fetchJson(
    `/api/v1/tracks/${encodeURIComponent(selectedTrackId)}/history?limit=1000`,
  );
  const points = payload.observations
    .filter((observation) => hasPosition(observation))
    .map((observation) => [observation.latitude, observation.longitude]);

  if (selectedHistory) {
    selectedHistory.remove();
    selectedHistory = null;
  }

  if (points.length > 1) {
    selectedHistory = L.polyline(points, {
      color: "#43d5ff",
      weight: 3,
      opacity: 0.78,
    }).addTo(map);
  }
}

function selectTrack(trackId) {
  selectedTrackId = trackId;
  const track = currentTracks.find((candidate) => candidate.id === trackId);
  renderTrackList(currentTracks);
  renderSelection(track);

  if (track && hasPosition(track)) {
    map.panTo([track.latitude, track.longitude]);
    trackLayers.get(track.id)?.marker.openPopup();
  }

  refreshSelectedHistory().catch((error) => {
    console.error("Nie udało się pobrać historii śladu", error);
  });
}

function clearSelection() {
  selectedTrackId = null;
  selectedHistory?.remove();
  selectedHistory = null;
  renderSelection(null);
  renderTrackList(currentTracks);
}

function fitAllEntities() {
  const points = [];
  for (const marker of sensorMarkers.values()) {
    points.push(marker.getLatLng());
  }
  for (const layer of trackLayers.values()) {
    points.push(layer.marker.getLatLng());
    if (layer.pilot) {
      points.push(layer.pilot.getLatLng());
    }
  }

  const bounds = L.latLngBounds(points);
  let hasZoneBounds = false;
  for (const layer of zoneLayers.values()) {
    const zoneBounds = layer.getBounds();
    if (zoneBounds.isValid()) {
      bounds.extend(zoneBounds);
      hasZoneBounds = true;
    }
  }

  if (points.length === 1 && !hasZoneBounds) {
    map.setView(points[0], 14);
  } else if (bounds.isValid()) {
    map.fitBounds(bounds, {
      padding: [45, 45],
      maxZoom: 15,
    });
  }
}

async function refresh() {
  if (refreshInProgress) {
    return;
  }
  refreshInProgress = true;

  try {
    const includeEnded = elements.showEnded.checked ? "true" : "false";
    const includeClosedAlerts = elements.showClosedAlerts.checked ? "true" : "false";
    const [sensorPayload, trackPayload, zonePayload, alertPayload] = await Promise.all([
      fetchJson("/api/v1/sensors"),
      fetchJson(`/api/v1/tracks?include_ended=${includeEnded}`),
      fetchJson("/api/v1/zones"),
      fetchJson(`/api/v1/alerts?include_closed=${includeClosedAlerts}`),
    ]);

    currentSensors = sensorPayload.sensors ?? [];
    currentTracks = trackPayload.tracks ?? [];
    currentZones = zonePayload.zones ?? [];
    currentAlerts = alertPayload.alerts ?? [];

    updateZoneLayers(currentZones, currentAlerts);
    updateSensorMarkers(currentSensors);
    updateTrackMarkers(currentTracks);
    renderSensorList(currentSensors);
    renderTrackList(currentTracks);
    renderAlertList(currentAlerts);
    renderZoneList(currentZones, currentAlerts);

    const onlineSensors = currentSensors.filter((sensor) => sensor.status === "online").length;
    const activeTracks = currentTracks.filter((track) => track.state === "active").length;
    const openAlerts = currentAlerts.filter((alert) => alert.state !== "closed").length;
    elements.onlineSensors.textContent = String(onlineSensors);
    elements.activeTracks.textContent = String(activeTracks);
    elements.openAlerts.textContent = String(openAlerts);
    elements.sensorCount.textContent = String(currentSensors.length);
    elements.trackCount.textContent = String(currentTracks.length);
    elements.alertCount.textContent = String(currentAlerts.length);
    elements.zoneCount.textContent = String(currentZones.length);

    if (selectedTrackId) {
      const selected = currentTracks.find((track) => track.id === selectedTrackId);
      if (selected) {
        renderSelection(selected);
        await refreshSelectedHistory();
      } else {
        clearSelection();
      }
    }

    if (
      !initialFitComplete &&
      (sensorMarkers.size > 0 || trackLayers.size > 0 || zoneLayers.size > 0)
    ) {
      fitAllEntities();
      initialFitComplete = true;
    }

    setConnection(true, "API online");
    elements.lastUpdate.textContent = `Aktualizacja ${new Date().toLocaleTimeString("pl-PL")}`;
  } catch (error) {
    console.error("Odświeżenie mapy nie powiodło się", error);
    setConnection(false, "Brak połączenia z API");
  } finally {
    refreshInProgress = false;
  }
}

elements.showEnded.addEventListener("change", refresh);
elements.showClosedAlerts.addEventListener("change", refresh);
elements.fitMap.addEventListener("click", fitAllEntities);
elements.closeSelection.addEventListener("click", clearSelection);

refresh();
setInterval(refresh, REFRESH_INTERVAL_MS);
