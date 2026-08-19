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
  operatorStatus: document.querySelector("#operator-status"),
  operatorPanel: document.querySelector("#operator-panel"),
  operatorModeLabel: document.querySelector("#operator-mode-label"),
  operatorLockIndicator: document.querySelector("#operator-lock-indicator"),
  operatorLoginForm: document.querySelector("#operator-login-form"),
  operatorName: document.querySelector("#operator-name"),
  operatorToken: document.querySelector("#operator-token"),
  operatorUnlock: document.querySelector("#operator-unlock"),
  operatorMessage: document.querySelector("#operator-message"),
  operatorActions: document.querySelector("#operator-actions"),
  operatorLock: document.querySelector("#operator-lock"),
  drawZone: document.querySelector("#draw-zone"),
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
  zoneEditor: document.querySelector("#zone-editor"),
  zoneDrawStep: document.querySelector("#zone-draw-step"),
  zonePointCount: document.querySelector("#zone-point-count"),
  zoneUndoPoint: document.querySelector("#zone-undo-point"),
  zoneFinishDrawing: document.querySelector("#zone-finish-drawing"),
  zoneCancelDrawing: document.querySelector("#zone-cancel-drawing"),
  zoneForm: document.querySelector("#zone-form"),
  zoneName: document.querySelector("#zone-name"),
  zoneSeverity: document.querySelector("#zone-severity"),
  zoneDescription: document.querySelector("#zone-description"),
  zoneActive: document.querySelector("#zone-active"),
  zoneSave: document.querySelector("#zone-save"),
  zoneBackToDrawing: document.querySelector("#zone-back-to-drawing"),
  zoneCancelForm: document.querySelector("#zone-cancel-form"),
  toast: document.querySelector("#toast"),
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
let adminToken = null;
let activeOperator = null;
let drawingMode = false;
let drawingPoints = [];
let drawingLayer = null;
let toastTimeout = null;

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

class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function requestJson(
  path,
  { method = "GET", body = null, token = null } = {},
) {
  const headers = { Accept: "application/json" };
  if (body !== null) {
    headers["Content-Type"] = "application/json";
  }
  if (token) {
    headers["X-RDDS-Admin-Token"] = token;
  }

  const response = await fetch(path, {
    method,
    headers,
    body: body === null ? null : JSON.stringify(body),
    cache: "no-store",
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const payload = await response.json();
      detail = payload.detail ?? detail;
    } catch {
      // The status code remains sufficient when the response is not JSON.
    }
    throw new ApiError(`${response.status}: ${detail}`, response.status);
  }
  return response.json();
}

function fetchJson(path) {
  return requestJson(path);
}

function showToast(message, error = false) {
  if (toastTimeout) {
    clearTimeout(toastTimeout);
  }
  elements.toast.textContent = message;
  elements.toast.classList.toggle("error", error);
  elements.toast.classList.remove("hidden");
  toastTimeout = setTimeout(() => {
    elements.toast.classList.add("hidden");
    toastTimeout = null;
  }, 4200);
}

async function adminRequest(path, method, body) {
  if (!adminToken) {
    throw new ApiError("Tryb operatora jest zablokowany", 401);
  }
  try {
    return await requestJson(path, { method, body, token: adminToken });
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      lockOperator("Sesja została zablokowana — podaj aktualny token.");
    }
    throw error;
  }
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

function updateOperatorUi(message = null, error = false) {
  const unlocked = Boolean(adminToken && activeOperator);
  elements.operatorPanel.classList.toggle("unlocked", unlocked);
  elements.operatorLoginForm.classList.toggle("hidden", unlocked);
  elements.operatorActions.classList.toggle("hidden", !unlocked);
  elements.operatorStatus.classList.toggle("unlocked", unlocked);
  elements.operatorStatus.textContent = unlocked ? activeOperator : "Obserwator";
  elements.operatorModeLabel.textContent = unlocked
    ? `Operator: ${activeOperator}`
    : "Tylko podgląd";
  elements.operatorLockIndicator.textContent = unlocked
    ? "Odblokowany"
    : "Zablokowany";
  elements.operatorMessage.classList.toggle("error", error);
  if (message !== null) {
    elements.operatorMessage.textContent = message;
  }
}

async function unlockOperator(event) {
  event.preventDefault();
  const operator = elements.operatorName.value.trim();
  const token = elements.operatorToken.value.trim();

  if (!operator || token.length < 32) {
    updateOperatorUi("Podaj nazwę operatora i poprawny token.", true);
    return;
  }

  elements.operatorUnlock.disabled = true;
  elements.operatorMessage.textContent = "Sprawdzanie uprawnień…";
  elements.operatorMessage.classList.remove("error");
  try {
    await requestJson("/api/v1/admin/verify", { token });
    adminToken = token;
    activeOperator = operator;
    elements.operatorToken.value = "";
    updateOperatorUi("Narzędzia administracyjne są aktywne.");
    renderAlertList(currentAlerts);
    renderZoneList(currentZones, currentAlerts);
    showToast(`Tryb operatora odblokowany: ${operator}`);
  } catch (error) {
    adminToken = null;
    activeOperator = null;
    elements.operatorToken.value = "";
    updateOperatorUi("Token został odrzucony przez API.", true);
  } finally {
    elements.operatorUnlock.disabled = false;
  }
}

function lockOperator(message = "Token usunięto z pamięci tej karty.") {
  cancelZoneDrawing();
  adminToken = null;
  activeOperator = null;
  elements.operatorToken.value = "";
  updateOperatorUi(message);
  renderAlertList(currentAlerts);
  renderZoneList(currentZones, currentAlerts);
}

async function runAlertAction(alert, action, button) {
  button.disabled = true;
  try {
    await adminRequest(
      `/api/v1/alerts/${encodeURIComponent(alert.id)}/${action}`,
      "POST",
      { actor: activeOperator },
    );
    showToast(
      action === "acknowledge"
        ? `Alarm dla ${alert.basic_id || alert.identity_key} został przyjęty.`
        : `Alarm został zamknięty. Jeśli naruszenie trwa, system otworzy nowy.`,
    );
    await refresh();
  } catch (error) {
    showToast(`Operacja na alarmie nie powiodła się: ${error.message}`, true);
  } finally {
    button.disabled = false;
  }
}

function renderAlertList(alerts) {
  elements.alertList.replaceChildren();
  elements.alertList.classList.toggle("empty-state", alerts.length === 0);

  if (alerts.length === 0) {
    elements.alertList.textContent = "Brak otwartych alarmów";
    return;
  }

  for (const alert of alerts) {
    const card = document.createElement("div");
    card.className = `entity-card managed-card alert-card severity-${alert.severity} alert-${alert.state}`;

    const main = document.createElement("button");
    main.type = "button";
    main.className = "managed-card-main";
    main.addEventListener("click", () => {
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
    main.append(titleRow, meta);
    card.append(main);

    if (adminToken && alert.state !== "closed") {
      const actions = document.createElement("div");
      actions.className = "managed-actions";
      if (alert.state === "active") {
        const acknowledge = document.createElement("button");
        acknowledge.type = "button";
        acknowledge.textContent = "Potwierdź";
        acknowledge.addEventListener("click", () => {
          runAlertAction(alert, "acknowledge", acknowledge);
        });
        actions.append(acknowledge);
      }
      const close = document.createElement("button");
      close.type = "button";
      close.className = "danger-button";
      close.textContent = "Zamknij";
      close.addEventListener("click", () => {
        runAlertAction(alert, "close", close);
      });
      actions.append(close);
      card.append(actions);
    }

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

async function runZoneStateChange(zone, active, button) {
  button.disabled = true;
  try {
    await adminRequest(
      `/api/v1/zones/${encodeURIComponent(zone.id)}`,
      "PATCH",
      { active },
    );
    showToast(`Strefa „${zone.name}” została ${active ? "włączona" : "wyłączona"}.`);
    await refresh();
  } catch (error) {
    showToast(`Zmiana strefy nie powiodła się: ${error.message}`, true);
  } finally {
    button.disabled = false;
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
    const card = document.createElement("div");
    card.className = "entity-card managed-card";
    const main = document.createElement("button");
    main.type = "button";
    main.className = "managed-card-main";
    main.addEventListener("click", () => {
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

    main.append(titleRow, meta);
    card.append(main);

    if (adminToken) {
      const actions = document.createElement("div");
      actions.className = "managed-actions";
      const toggle = document.createElement("button");
      toggle.type = "button";
      toggle.className = zone.active ? "danger-button" : "";
      toggle.textContent = zone.active ? "Wyłącz strefę" : "Włącz strefę";
      toggle.addEventListener("click", () => {
        runZoneStateChange(zone, !zone.active, toggle);
      });
      actions.append(toggle);
      card.append(actions);
    }

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
  if (!elements.zoneEditor.classList.contains("hidden")) {
    return;
  }
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

function updateDrawingLayer() {
  drawingLayer?.remove();
  drawingLayer = null;

  if (drawingPoints.length === 0) {
    elements.zonePointCount.textContent = "0";
    elements.zoneFinishDrawing.disabled = true;
    elements.zoneUndoPoint.disabled = true;
    return;
  }

  const layers = drawingPoints.map((point) =>
    L.circleMarker(point, {
      radius: 4,
      color: "#ffb84d",
      fillColor: "#ffb84d",
      fillOpacity: 0.9,
      weight: 1,
    }),
  );

  if (drawingPoints.length >= 2) {
    const shape = drawingMode
      ? L.polyline(drawingPoints, {
          color: "#ffb84d",
          weight: 2,
          dashArray: "7 6",
        })
      : L.polygon(drawingPoints, {
          color: "#ffb84d",
          fillColor: "#ffb84d",
          fillOpacity: 0.16,
          weight: 2,
        });
    layers.unshift(shape);
  }

  drawingLayer = L.layerGroup(layers).addTo(map);
  elements.zonePointCount.textContent = String(drawingPoints.length);
  elements.zoneFinishDrawing.disabled = drawingPoints.length < 3;
  elements.zoneUndoPoint.disabled = drawingPoints.length === 0;
}

function setZoneEditorStep(step) {
  const drawing = step === "drawing";
  elements.zoneDrawStep.classList.toggle("hidden", !drawing);
  elements.zoneForm.classList.toggle("hidden", drawing);
}

function startZoneDrawing() {
  if (!adminToken) {
    showToast("Najpierw odblokuj tryb operatora.", true);
    return;
  }

  clearSelection();
  drawingPoints = [];
  drawingMode = true;
  elements.zoneForm.reset();
  elements.zoneSeverity.value = "high";
  elements.zoneActive.checked = true;
  elements.zoneEditor.classList.remove("hidden");
  setZoneEditorStep("drawing");
  map.getContainer().classList.add("drawing-zone");
  map.closePopup();
  updateDrawingLayer();
  showToast("Klikaj na mapie, aby wyznaczyć granice strefy.");
}

function handleMapDrawingClick(event) {
  if (!drawingMode) {
    return;
  }
  if (drawingPoints.length >= 500) {
    showToast("Osiągnięto limit 500 punktów strefy.", true);
    return;
  }
  drawingPoints.push(event.latlng);
  updateDrawingLayer();
}

function undoZonePoint() {
  if (!drawingMode || drawingPoints.length === 0) {
    return;
  }
  drawingPoints.pop();
  updateDrawingLayer();
}

function finishZoneDrawing() {
  if (drawingPoints.length < 3) {
    showToast("Strefa wymaga co najmniej trzech punktów.", true);
    return;
  }
  drawingMode = false;
  map.getContainer().classList.remove("drawing-zone");
  setZoneEditorStep("form");
  updateDrawingLayer();
  elements.zoneName.focus();
}

function returnToZoneDrawing() {
  drawingMode = true;
  setZoneEditorStep("drawing");
  map.getContainer().classList.add("drawing-zone");
  updateDrawingLayer();
}

function cancelZoneDrawing() {
  drawingMode = false;
  drawingPoints = [];
  drawingLayer?.remove();
  drawingLayer = null;
  map.getContainer().classList.remove("drawing-zone");
  elements.zoneEditor.classList.add("hidden");
  elements.zoneForm.reset();
  elements.zonePointCount.textContent = "0";
  elements.zoneFinishDrawing.disabled = true;
  elements.zoneUndoPoint.disabled = true;
}

async function saveDrawnZone(event) {
  event.preventDefault();
  if (!adminToken || drawingPoints.length < 3) {
    showToast("Nie można zapisać niekompletnej strefy.", true);
    return;
  }

  const coordinates = drawingPoints.map((point) => [
    Number(point.lng.toFixed(7)),
    Number(point.lat.toFixed(7)),
  ]);
  coordinates.push([...coordinates[0]]);
  const payload = {
    name: elements.zoneName.value.trim(),
    description: elements.zoneDescription.value.trim() || null,
    severity: elements.zoneSeverity.value,
    active: elements.zoneActive.checked,
    geometry: {
      type: "Polygon",
      coordinates: [coordinates],
    },
  };

  elements.zoneSave.disabled = true;
  try {
    const response = await adminRequest("/api/v1/zones", "POST", payload);
    const createdZone = response.zone;
    cancelZoneDrawing();
    showToast(`Strefa „${createdZone.name}” została utworzona.`);
    await refresh();
    const layer = zoneLayers.get(createdZone.id);
    if (layer) {
      map.fitBounds(layer.getBounds(), { padding: [45, 45], maxZoom: 16 });
      layer.openPopup();
    }
  } catch (error) {
    showToast(`Nie udało się utworzyć strefy: ${error.message}`, true);
  } finally {
    elements.zoneSave.disabled = false;
  }
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
elements.operatorLoginForm.addEventListener("submit", unlockOperator);
elements.operatorLock.addEventListener("click", () => lockOperator());
elements.drawZone.addEventListener("click", startZoneDrawing);
elements.zoneUndoPoint.addEventListener("click", undoZonePoint);
elements.zoneFinishDrawing.addEventListener("click", finishZoneDrawing);
elements.zoneCancelDrawing.addEventListener("click", cancelZoneDrawing);
elements.zoneForm.addEventListener("submit", saveDrawnZone);
elements.zoneBackToDrawing.addEventListener("click", returnToZoneDrawing);
elements.zoneCancelForm.addEventListener("click", cancelZoneDrawing);
map.on("click", handleMapDrawingClick);
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !elements.zoneEditor.classList.contains("hidden")) {
    cancelZoneDrawing();
  }
});

updateOperatorUi();
refresh();
setInterval(refresh, REFRESH_INTERVAL_MS);
