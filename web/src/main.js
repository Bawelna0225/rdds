import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { forward as toMgrs } from "mgrs";

import "./styles.css";

const REFRESH_INTERVAL_MS = 2000;
const DEFAULT_CENTER = [52.2297, 21.0122];
const SIDEBAR_STATE_KEY = "rdds.sidebar.sections.v1";

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
  inactive: "wyłączona",
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

const auditEventLabels = {
  alert_opened: "Otwarto alarm",
  alert_acknowledged: "Potwierdzono alarm",
  alert_closed: "Zamknięto alarm",
  zone_created: "Utworzono strefę",
  zone_enabled: "Włączono strefę",
  zone_disabled: "Wyłączono strefę",
  zone_updated: "Zmieniono strefę",
  zone_deleted: "Usunięto strefę",
  sensor_registered: "Zarejestrowano sensor",
  sensor_enabled: "Włączono sensor",
  sensor_disabled: "Wyłączono sensor",
  sensor_updated: "Zmieniono sensor",
  sensor_deleted: "Usunięto sensor",
  sensor_token_issued: "Wydano token sensora",
  sensor_token_rotated: "Zmieniono token sensora",
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
  operatorMenu: document.querySelector("#operator-menu"),
  operatorMenuToggle: document.querySelector("#operator-menu-toggle"),
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
  registerSensor: document.querySelector("#register-sensor"),
  trackCount: document.querySelector("#track-count"),
  sensorCount: document.querySelector("#sensor-count"),
  alertCount: document.querySelector("#alert-count"),
  zoneCount: document.querySelector("#zone-count"),
  auditCount: document.querySelector("#audit-count"),
  trackList: document.querySelector("#track-list"),
  sensorList: document.querySelector("#sensor-list"),
  alertList: document.querySelector("#alert-list"),
  zoneList: document.querySelector("#zone-list"),
  auditList: document.querySelector("#audit-list"),
  auditCategory: document.querySelector("#audit-category"),
  auditExportCsv: document.querySelector("#audit-export-csv"),
  auditExportJson: document.querySelector("#audit-export-json"),
  showEnded: document.querySelector("#show-ended"),
  showClosedAlerts: document.querySelector("#show-closed-alerts"),
  fitMap: document.querySelector("#fit-map"),
  selectionPanel: document.querySelector("#selection-panel"),
  selectionEyebrow: document.querySelector("#selection-eyebrow"),
  selectionTitle: document.querySelector("#selection-title"),
  selectionDetails: document.querySelector("#selection-details"),
  selectionTimeline: document.querySelector("#selection-timeline"),
  selectionTimelineList: document.querySelector("#selection-timeline-list"),
  closeSelection: document.querySelector("#close-selection"),
  zoneEditor: document.querySelector("#zone-editor"),
  zoneDrawStep: document.querySelector("#zone-draw-step"),
  zonePointCount: document.querySelector("#zone-point-count"),
  zoneDrawEyebrow: document.querySelector("#zone-draw-eyebrow"),
  zoneDrawTitle: document.querySelector("#zone-draw-title"),
  zoneDrawHelp: document.querySelector("#zone-draw-help"),
  zoneUndoPoint: document.querySelector("#zone-undo-point"),
  zoneClearPoints: document.querySelector("#zone-clear-points"),
  zoneFinishDrawing: document.querySelector("#zone-finish-drawing"),
  zoneCancelDrawing: document.querySelector("#zone-cancel-drawing"),
  zoneForm: document.querySelector("#zone-form"),
  zoneFormEyebrow: document.querySelector("#zone-form-eyebrow"),
  zoneFormTitle: document.querySelector("#zone-form-title"),
  zoneName: document.querySelector("#zone-name"),
  zoneSeverity: document.querySelector("#zone-severity"),
  zoneDescription: document.querySelector("#zone-description"),
  zoneActive: document.querySelector("#zone-active"),
  zoneSave: document.querySelector("#zone-save"),
  zoneBackToDrawing: document.querySelector("#zone-back-to-drawing"),
  zoneCancelForm: document.querySelector("#zone-cancel-form"),
  sensorEditor: document.querySelector("#sensor-editor"),
  sensorForm: document.querySelector("#sensor-form"),
  sensorFormEyebrow: document.querySelector("#sensor-form-eyebrow"),
  sensorFormTitle: document.querySelector("#sensor-form-title"),
  sensorFormHelp: document.querySelector("#sensor-form-help"),
  sensorKey: document.querySelector("#sensor-key"),
  sensorDisplayName: document.querySelector("#sensor-display-name"),
  sensorLatitude: document.querySelector("#sensor-latitude"),
  sensorLongitude: document.querySelector("#sensor-longitude"),
  sensorSave: document.querySelector("#sensor-save"),
  sensorCancel: document.querySelector("#sensor-cancel"),
  sensorTokenPanel: document.querySelector("#sensor-token-panel"),
  sensorTokenTitle: document.querySelector("#sensor-token-title"),
  sensorTokenValue: document.querySelector("#sensor-token-value"),
  sensorTokenCopy: document.querySelector("#sensor-token-copy"),
  sensorTokenClose: document.querySelector("#sensor-token-close"),
  toast: document.querySelector("#toast"),
  sectionToggles: document.querySelectorAll(".section-toggle"),
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
let currentAuditEvents = [];
let currentAuditTotal = 0;
let selectedTrackId = null;
let selectedSensorId = null;
let selectedAuditEvent = null;
let selectedHistory = null;
let initialFitComplete = false;
let refreshInProgress = false;
let adminToken = null;
let activeOperator = null;
let operatorMenuOpen = false;
let drawingMode = false;
let drawingPoints = [];
let drawingLayer = null;
let editingZoneId = null;
let editingSensorId = null;
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

function formatInteger(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return "—";
  }
  return new Intl.NumberFormat("pl-PL").format(value);
}

function formatBytes(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return "—";
  }
  if (value >= 1024 * 1024) {
    return `${(value / (1024 * 1024)).toFixed(1)} MiB`;
  }
  if (value >= 1024) {
    return `${(value / 1024).toFixed(1)} KiB`;
  }
  return `${value} B`;
}

function formatDuration(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return "—";
  }
  const seconds = Math.max(0, Math.round(value));
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (days > 0) {
    return `${days} d ${hours} h`;
  }
  if (hours > 0) {
    return `${hours} h ${minutes} min`;
  }
  return `${minutes} min`;
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

function formatDateTime(value) {
  if (!value) {
    return "—";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "—";
  }
  return date.toLocaleString("pl-PL", {
    dateStyle: "medium",
    timeStyle: "medium",
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

function auditEventLabel(eventType) {
  return auditEventLabels[eventType] ?? eventType ?? "—";
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
      <span>Token</span><strong>${sensor.credential_mode === "individual" ? "indywidualny" : "wspólny"}</strong>
      <span>Obserwacje</span><strong>${escapeHtml(formatInteger(sensor.observation_count))}</strong>
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

function setOperatorMenuOpen(open) {
  operatorMenuOpen = open;
  elements.operatorMenu.classList.toggle("open", open);
  elements.operatorPanel.classList.toggle("hidden", !open);
  elements.operatorMenuToggle.setAttribute("aria-expanded", String(open));
}

function toggleOperatorMenu() {
  setOperatorMenuOpen(!operatorMenuOpen);
  if (operatorMenuOpen && !adminToken) {
    elements.operatorName.focus();
  }
}

function readSidebarState() {
  try {
    return JSON.parse(localStorage.getItem(SIDEBAR_STATE_KEY) || "{}") ?? {};
  } catch {
    return {};
  }
}

function writeSidebarState(state) {
  try {
    localStorage.setItem(SIDEBAR_STATE_KEY, JSON.stringify(state));
  } catch {
    // Zwijanie nadal działa, nawet jeśli przeglądarka blokuje localStorage.
  }
}

function setSectionCollapsed(section, collapsed, persist = true) {
  const toggle = section.querySelector(".section-toggle");
  section.classList.toggle("collapsed", collapsed);
  toggle?.setAttribute("aria-expanded", String(!collapsed));

  if (persist) {
    const state = readSidebarState();
    state[section.dataset.sectionKey] = collapsed;
    writeSidebarState(state);
  }
}

function initializeCollapsibleSections() {
  const state = readSidebarState();
  for (const toggle of elements.sectionToggles) {
    const section = toggle.closest(".sidebar-section");
    if (!section) {
      continue;
    }
    setSectionCollapsed(section, Boolean(state[section.dataset.sectionKey]), false);
    toggle.addEventListener("click", () => {
      setSectionCollapsed(section, !section.classList.contains("collapsed"));
    });
  }
}

function updateOperatorUi(message = null, error = false) {
  const unlocked = Boolean(adminToken && activeOperator);
  elements.operatorMenu.classList.toggle("unlocked", unlocked);
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
    const verification = await requestJson("/api/v1/admin/verify", { token });
    adminToken = token;
    activeOperator = operator;
    elements.operatorToken.value = "";
    updateOperatorUi(
      verification.legacy_ingest_enabled
        ? "Narzędzia aktywne. Wspólny token sensorów nadal jest dozwolony."
        : "Narzędzia administracyjne są aktywne.",
    );
    renderAlertList(currentAlerts);
    renderSensorList(currentSensors);
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
  cancelSensorRegistration();
  closeSensorToken();
  adminToken = null;
  activeOperator = null;
  elements.operatorToken.value = "";
  updateOperatorUi(message);
  renderAlertList(currentAlerts);
  renderSensorList(currentSensors);
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

function renderAuditList(events) {
  elements.auditList.replaceChildren();
  elements.auditList.classList.toggle("empty-state", events.length === 0);

  if (events.length === 0) {
    elements.auditList.textContent = "Brak zarejestrowanych zdarzeń";
    return;
  }

  for (const event of events) {
    const card = document.createElement("button");
    card.type = "button";
    const selected = String(event.id) === String(selectedAuditEvent?.id);
    const category = event.event_type.startsWith("alert_")
      ? "alert"
      : event.event_type.startsWith("sensor_")
        ? "sensor"
        : "zone";
    card.className = `entity-card audit-card audit-${category}${selected ? " selected" : ""}`;
    card.addEventListener("click", () => selectAuditEvent(event));

    const titleRow = document.createElement("div");
    titleRow.className = "entity-title-row";
    const title = document.createElement("span");
    title.className = "entity-title";
    title.textContent = auditEventLabel(event.event_type);
    const actor = document.createElement("span");
    actor.className = "audit-actor";
    actor.textContent = event.actor || "system";
    titleRow.append(title, actor);

    const meta = document.createElement("div");
    meta.className = "entity-meta audit-meta";
    const subject = document.createElement("span");
    subject.textContent =
      event.basic_id ||
      event.identity_key ||
      event.zone_name ||
      event.sensor_name ||
      event.sensor_key ||
      "system";
    const context = document.createElement("span");
    context.textContent = event.zone_name || event.sensor_key || "—";
    const time = document.createElement("span");
    time.textContent = formatDateTime(event.occurred_at);
    meta.append(subject, context, time);

    card.append(titleRow, meta);
    elements.auditList.append(card);
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

async function runSensorStateChange(sensor, enabled, button) {
  button.disabled = true;
  try {
    await adminRequest(
      `/api/v1/sensors/${encodeURIComponent(sensor.id)}`,
      "PATCH",
      { enabled, actor: activeOperator },
    );
    showToast(
      `Sensor „${sensor.display_name}” został ${enabled ? "włączony" : "wyłączony"}.`,
    );
    await refresh();
  } catch (error) {
    showToast(`Zmiana sensora nie powiodła się: ${error.message}`, true);
  } finally {
    button.disabled = false;
  }
}

async function runSensorTokenRotation(sensor, button) {
  const action = sensor.credential_mode === "individual" ? "zmienić" : "wydać";
  const warning =
    sensor.credential_mode === "individual"
      ? "Poprzedni token natychmiast przestanie działać."
      : "Po tej operacji wspólny token przestanie działać dla tego sensora.";
  if (!window.confirm(`Czy ${action} indywidualny token sensora? ${warning}`)) {
    return;
  }

  button.disabled = true;
  try {
    const response = await adminRequest(
      `/api/v1/sensors/${encodeURIComponent(sensor.id)}/token/rotate`,
      "POST",
      { actor: activeOperator },
    );
    showSensorToken(response.sensor, response.credential);
    await refresh();
  } catch (error) {
    showToast(`Nie udało się wydać tokenu: ${error.message}`, true);
  } finally {
    button.disabled = false;
  }
}

async function runSensorDeletion(sensor, button) {
  const confirmed = window.confirm(
    `Usunąć sensor „${sensor.display_name}”? Zniknie z mapy, a jego token ` +
      "zostanie unieważniony. Dane historyczne pozostaną w dzienniku.",
  );
  if (!confirmed) {
    return;
  }

  button.disabled = true;
  try {
    await adminRequest(
      `/api/v1/sensors/${encodeURIComponent(sensor.id)}`,
      "DELETE",
      { actor: activeOperator },
    );
    if (selectedSensorId === sensor.id) {
      clearSelection();
    }
    showToast(`Sensor „${sensor.display_name}” został usunięty.`);
    await refresh();
  } catch (error) {
    showToast(`Nie udało się usunąć sensora: ${error.message}`, true);
  } finally {
    button.disabled = false;
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
    const card = document.createElement("div");
    card.className = `entity-card managed-card sensor-card${sensor.id === selectedSensorId ? " selected" : ""}`;
    const main = document.createElement("button");
    main.type = "button";
    main.className = "managed-card-main";
    main.addEventListener("click", () => selectSensor(sensor.id));

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
    const credential = document.createElement("span");
    credential.textContent =
      sensor.credential_mode === "individual"
        ? `token ${sensor.token_prefix}…`
        : "token wspólny";
    const time = document.createElement("span");
    time.textContent = formatTime(sensor.last_seen_at);
    meta.append(identifier, credential, time);

    main.append(titleRow, meta);
    card.append(main);

    if (adminToken) {
      const actions = document.createElement("div");
      actions.className = "managed-actions";
      const edit = document.createElement("button");
      edit.type = "button";
      edit.textContent = "Edytuj";
      edit.addEventListener("click", () => startSensorEditing(sensor));
      const toggle = document.createElement("button");
      toggle.type = "button";
      toggle.className = sensor.status === "disabled" ? "" : "danger-button";
      toggle.textContent = sensor.status === "disabled" ? "Włącz" : "Wyłącz";
      toggle.addEventListener("click", () => {
        runSensorStateChange(sensor, sensor.status === "disabled", toggle);
      });
      const rotate = document.createElement("button");
      rotate.type = "button";
      rotate.textContent =
        sensor.credential_mode === "individual" ? "Zmień token" : "Wydaj token";
      rotate.addEventListener("click", () => runSensorTokenRotation(sensor, rotate));
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "danger-button";
      remove.textContent = "Usuń";
      remove.addEventListener("click", () => runSensorDeletion(sensor, remove));
      actions.append(edit, toggle, rotate, remove);
      card.append(actions);
    }

    elements.sensorList.append(card);
  }
}

async function runZoneStateChange(zone, active, button) {
  button.disabled = true;
  try {
    await adminRequest(
      `/api/v1/zones/${encodeURIComponent(zone.id)}`,
      "PATCH",
      { active, actor: activeOperator },
    );
    showToast(`Strefa „${zone.name}” została ${active ? "włączona" : "wyłączona"}.`);
    await refresh();
  } catch (error) {
    showToast(`Zmiana strefy nie powiodła się: ${error.message}`, true);
  } finally {
    button.disabled = false;
  }
}

async function runZoneDeletion(zone, button) {
  const confirmed = window.confirm(
    `Usunąć strefę „${zone.name}”? Zniknie z mapy, a jej otwarte alarmy ` +
      "zostaną zamknięte. Historia pozostanie w dzienniku.",
  );
  if (!confirmed) {
    return;
  }

  button.disabled = true;
  try {
    await adminRequest(
      `/api/v1/zones/${encodeURIComponent(zone.id)}`,
      "DELETE",
      { actor: activeOperator },
    );
    showToast(`Strefa „${zone.name}” została usunięta.`);
    await refresh();
  } catch (error) {
    showToast(`Nie udało się usunąć strefy: ${error.message}`, true);
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
      const edit = document.createElement("button");
      edit.type = "button";
      edit.textContent = "Edytuj";
      edit.addEventListener("click", () => startZoneEditing(zone));
      const toggle = document.createElement("button");
      toggle.type = "button";
      toggle.className = zone.active ? "danger-button" : "";
      toggle.textContent = zone.active ? "Wyłącz strefę" : "Włącz strefę";
      toggle.addEventListener("click", () => {
        runZoneStateChange(zone, !zone.active, toggle);
      });
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "danger-button";
      remove.textContent = "Usuń";
      remove.addEventListener("click", () => runZoneDeletion(zone, remove));
      actions.append(edit, toggle, remove);
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
    elements.selectionDetails.replaceChildren();
    elements.selectionTimeline.classList.add("hidden");
    elements.selectionTimelineList.replaceChildren();
    return;
  }

  elements.selectionPanel.classList.remove("hidden");
  elements.selectionEyebrow.textContent = "Wybrany ślad";
  elements.selectionTitle.textContent = track.basic_id || track.identity_key || track.track_key;
  elements.selectionTimeline.classList.add("hidden");
  elements.selectionTimelineList.replaceChildren();
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

function renderSensorSelection(sensor) {
  elements.selectionPanel.classList.remove("hidden");
  elements.selectionEyebrow.textContent = "Wybrany sensor";
  elements.selectionTitle.textContent = sensor.display_name || sensor.sensor_id;
  elements.selectionTimeline.classList.add("hidden");
  elements.selectionTimelineList.replaceChildren();
  elements.selectionDetails.replaceChildren(
    detailItem("Status", stateLabel(sensor.status)),
    detailItem("Identyfikator", sensor.sensor_id),
    detailItem(
      "Uwierzytelnianie",
      sensor.credential_mode === "individual" ? "token indywidualny" : "token wspólny",
    ),
    detailItem("Prefiks tokenu", sensor.token_prefix ? `${sensor.token_prefix}…` : "—"),
    detailItem("Ostatni kontakt", formatDateTime(sensor.last_seen_at)),
    detailItem("MGRS", formatMgrs(sensor.latitude, sensor.longitude)),
    detailItem("Obserwacje", formatInteger(sensor.observation_count)),
    detailItem("Heartbeat", formatInteger(sensor.heartbeat_count)),
    detailItem("Uptime", formatDuration(sensor.uptime_seconds)),
    detailItem("RSSI modemu", formatNumber(sensor.cellular_rssi, 0, " dBm")),
    detailItem("Wolna pamięć", formatBytes(sensor.free_heap_bytes)),
    detailItem("Kolejka", formatInteger(sensor.queue_depth)),
  );
}

function renderAuditTimeline(events) {
  elements.selectionTimelineList.replaceChildren();

  if (events.length === 0) {
    elements.selectionTimelineList.textContent = "Brak zdarzeń w tej historii.";
    return;
  }

  for (const event of [...events].reverse()) {
    const item = document.createElement("div");
    const category = event.event_type.startsWith("alert_")
      ? "alert"
      : event.event_type.startsWith("sensor_")
        ? "sensor"
        : "zone";
    item.className = `timeline-event ${category}`;
    const marker = document.createElement("span");
    marker.className = "timeline-marker";
    const content = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = auditEventLabel(event.event_type);
    const meta = document.createElement("span");
    meta.textContent = `${formatDateTime(event.occurred_at)} · ${event.actor || "system"}`;
    content.append(title, meta);
    item.append(marker, content);
    elements.selectionTimelineList.append(item);
  }
}

function renderAuditSelection(event) {
  elements.selectionPanel.classList.remove("hidden");
  elements.selectionEyebrow.textContent = "Zdarzenie audytowe";
  elements.selectionTitle.textContent = auditEventLabel(event.event_type);
  elements.selectionDetails.replaceChildren(
    detailItem("Czas", formatDateTime(event.occurred_at)),
    detailItem("Operator", event.actor),
    detailItem("Dron", event.basic_id || event.identity_key),
    detailItem("Operator drona", event.operator_id),
    detailItem("Strefa", event.zone_name),
    detailItem("Sensor", event.sensor_name || event.sensor_key),
    detailItem("Poziom", severityLabel(event.alert_severity || event.details?.severity)),
    detailItem("Stan alarmu", stateLabel(event.alert_state)),
  );
  elements.selectionTimeline.classList.remove("hidden");
  elements.selectionTimelineList.textContent = "Ładowanie historii…";
}

async function refreshSelectedAuditTimeline() {
  if (!selectedAuditEvent) {
    return;
  }

  const requestedId = String(selectedAuditEvent.id);
  let parameter = null;
  if (selectedAuditEvent.alert_id) {
    parameter = `alert_id=${encodeURIComponent(selectedAuditEvent.alert_id)}`;
  } else if (selectedAuditEvent.zone_id) {
    parameter = `zone_id=${encodeURIComponent(selectedAuditEvent.zone_id)}`;
  } else if (selectedAuditEvent.sensor_id) {
    parameter = `sensor_id=${encodeURIComponent(selectedAuditEvent.sensor_id)}`;
  }
  if (!parameter) {
    renderAuditTimeline([selectedAuditEvent]);
    return;
  }
  const payload = await fetchJson(`/api/v1/audit/events?${parameter}&limit=200`);
  if (String(selectedAuditEvent?.id) === requestedId) {
    renderAuditTimeline(payload.events ?? []);
  }
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
  if (
    !elements.zoneEditor.classList.contains("hidden") ||
    !elements.sensorEditor.classList.contains("hidden") ||
    !elements.sensorTokenPanel.classList.contains("hidden")
  ) {
    return;
  }
  selectedAuditEvent = null;
  selectedSensorId = null;
  selectedTrackId = trackId;
  const track = currentTracks.find((candidate) => candidate.id === trackId);
  renderAuditList(currentAuditEvents);
  renderSensorList(currentSensors);
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

function selectSensor(sensorId) {
  if (
    !elements.zoneEditor.classList.contains("hidden") ||
    !elements.sensorEditor.classList.contains("hidden") ||
    !elements.sensorTokenPanel.classList.contains("hidden")
  ) {
    return;
  }

  selectedTrackId = null;
  selectedAuditEvent = null;
  selectedSensorId = sensorId;
  selectedHistory?.remove();
  selectedHistory = null;
  const sensor = currentSensors.find((candidate) => candidate.id === sensorId);
  renderTrackList(currentTracks);
  renderAuditList(currentAuditEvents);
  renderSensorList(currentSensors);
  if (sensor) {
    renderSensorSelection(sensor);
    if (hasPosition(sensor)) {
      map.setView([sensor.latitude, sensor.longitude], Math.max(map.getZoom(), 14));
      sensorMarkers.get(sensor.id)?.openPopup();
    }
  }
}

function selectAuditEvent(event) {
  if (
    !elements.zoneEditor.classList.contains("hidden") ||
    !elements.sensorEditor.classList.contains("hidden") ||
    !elements.sensorTokenPanel.classList.contains("hidden")
  ) {
    return;
  }

  selectedTrackId = null;
  selectedSensorId = null;
  selectedHistory?.remove();
  selectedHistory = null;
  selectedAuditEvent = event;
  renderTrackList(currentTracks);
  renderSensorList(currentSensors);
  renderAuditList(currentAuditEvents);
  renderAuditSelection(event);

  const track = currentTracks.find((candidate) => candidate.id === event.track_id);
  if (track && hasPosition(track)) {
    map.panTo([track.latitude, track.longitude]);
    trackLayers.get(track.id)?.marker.openPopup();
  }

  refreshSelectedAuditTimeline().catch((error) => {
    elements.selectionTimelineList.textContent = "Nie udało się pobrać historii.";
    console.error("Nie udało się pobrać historii audytu", error);
  });
}

function clearSelection() {
  selectedTrackId = null;
  selectedSensorId = null;
  selectedAuditEvent = null;
  selectedHistory?.remove();
  selectedHistory = null;
  renderSelection(null);
  renderTrackList(currentTracks);
  renderSensorList(currentSensors);
  renderAuditList(currentAuditEvents);
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

  cancelSensorRegistration();
  closeSensorToken();
  clearSelection();
  setOperatorMenuOpen(false);
  editingZoneId = null;
  drawingPoints = [];
  drawingMode = true;
  elements.zoneForm.reset();
  elements.zoneDrawEyebrow.textContent = "Nowa strefa";
  elements.zoneDrawTitle.textContent = "Wskaż granice na mapie";
  elements.zoneDrawHelp.textContent =
    "Klikaj kolejne narożniki wielokąta. Minimum to trzy punkty.";
  elements.zoneFormEyebrow.textContent = "Nowa strefa";
  elements.zoneFormTitle.textContent = "Parametry strefy";
  elements.zoneSave.textContent = "Zapisz strefę";
  elements.zoneSeverity.value = "high";
  elements.zoneActive.checked = true;
  elements.zoneEditor.classList.remove("hidden");
  setZoneEditorStep("drawing");
  map.getContainer().classList.add("drawing-zone");
  map.closePopup();
  updateDrawingLayer();
  showToast("Klikaj na mapie, aby wyznaczyć granice strefy.");
}

function startZoneEditing(zone) {
  if (!adminToken) {
    showToast("Najpierw odblokuj tryb operatora.", true);
    return;
  }

  const ring = zone.geometry?.coordinates?.[0];
  if (!Array.isArray(ring) || ring.length < 4) {
    showToast("Ta strefa nie ma poprawnej geometrii do edycji.", true);
    return;
  }

  cancelSensorRegistration();
  closeSensorToken();
  clearSelection();
  setOperatorMenuOpen(false);
  editingZoneId = zone.id;
  drawingMode = false;
  drawingPoints = ring.slice(0, -1).map(([longitude, latitude]) =>
    L.latLng(latitude, longitude),
  );
  elements.zoneForm.reset();
  elements.zoneName.value = zone.name;
  elements.zoneSeverity.value = zone.severity;
  elements.zoneDescription.value = zone.description ?? "";
  elements.zoneActive.checked = zone.active;
  elements.zoneDrawEyebrow.textContent = "Edycja strefy";
  elements.zoneDrawTitle.textContent = "Zmień granice na mapie";
  elements.zoneDrawHelp.textContent =
    "Możesz cofać punkty albo wyczyścić granice i narysować je ponownie.";
  elements.zoneFormEyebrow.textContent = "Edycja strefy";
  elements.zoneFormTitle.textContent = "Parametry strefy";
  elements.zoneSave.textContent = "Zapisz zmiany";
  elements.zoneEditor.classList.remove("hidden");
  setZoneEditorStep("form");
  map.getContainer().classList.remove("drawing-zone");
  map.closePopup();
  updateDrawingLayer();
  elements.zoneName.focus();
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

function clearZonePoints() {
  if (!drawingMode) {
    return;
  }
  drawingPoints = [];
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
  editingZoneId = null;
  elements.zoneSave.disabled = false;
  elements.zonePointCount.textContent = "0";
  elements.zoneFinishDrawing.disabled = true;
  elements.zoneUndoPoint.disabled = true;
}

function startSensorRegistration() {
  if (!adminToken) {
    showToast("Najpierw odblokuj tryb operatora.", true);
    return;
  }

  cancelZoneDrawing();
  closeSensorToken();
  clearSelection();
  setOperatorMenuOpen(false);
  editingSensorId = null;
  elements.sensorForm.reset();
  elements.sensorKey.disabled = false;
  elements.sensorFormEyebrow.textContent = "Nowy sensor";
  elements.sensorFormTitle.textContent = "Rejestracja odbiornika";
  elements.sensorFormHelp.textContent =
    "Identyfikator musi być identyczny z wartością skonfigurowaną w urządzeniu.";
  elements.sensorSave.textContent = "Zarejestruj";
  const center = map.getCenter();
  elements.sensorLatitude.value = center.lat.toFixed(7);
  elements.sensorLongitude.value = center.lng.toFixed(7);
  elements.sensorEditor.classList.remove("hidden");
  elements.sensorKey.focus();
}

function startSensorEditing(sensor) {
  if (!adminToken) {
    showToast("Najpierw odblokuj tryb operatora.", true);
    return;
  }

  cancelZoneDrawing();
  closeSensorToken();
  clearSelection();
  setOperatorMenuOpen(false);
  editingSensorId = sensor.id;
  elements.sensorForm.reset();
  elements.sensorKey.value = sensor.sensor_id;
  elements.sensorKey.disabled = true;
  elements.sensorDisplayName.value = sensor.display_name ?? sensor.sensor_id;
  elements.sensorLatitude.value = hasPosition(sensor) ? String(sensor.latitude) : "";
  elements.sensorLongitude.value = hasPosition(sensor) ? String(sensor.longitude) : "";
  elements.sensorFormEyebrow.textContent = "Edycja sensora";
  elements.sensorFormTitle.textContent = "Ustawienia odbiornika";
  elements.sensorFormHelp.textContent =
    "Identyfikator pozostaje stały. Możesz zmienić nazwę i pozycję na mapie.";
  elements.sensorSave.textContent = "Zapisz zmiany";
  elements.sensorEditor.classList.remove("hidden");
  elements.sensorDisplayName.focus();
}

function cancelSensorRegistration() {
  elements.sensorEditor.classList.add("hidden");
  elements.sensorForm.reset();
  elements.sensorKey.disabled = false;
  editingSensorId = null;
  elements.sensorSave.disabled = false;
}

function showSensorToken(sensor, credential) {
  cancelSensorRegistration();
  clearSelection();
  elements.sensorTokenTitle.textContent = `Token: ${sensor.display_name}`;
  elements.sensorTokenValue.textContent = credential.ingest_token;
  elements.sensorTokenPanel.classList.remove("hidden");
}

function closeSensorToken() {
  elements.sensorTokenPanel.classList.add("hidden");
  elements.sensorTokenValue.textContent = "";
}

async function copySensorToken() {
  const token = elements.sensorTokenValue.textContent;
  if (!token) {
    return;
  }

  let copied = false;
  if (window.isSecureContext && navigator.clipboard) {
    try {
      await navigator.clipboard.writeText(token);
      copied = true;
    } catch {
      copied = false;
    }
  }

  if (!copied) {
    const field = document.createElement("textarea");
    field.value = token;
    field.style.position = "fixed";
    field.style.opacity = "0";
    document.body.append(field);
    field.focus();
    field.select();
    try {
      copied = document.execCommand("copy");
    } catch {
      copied = false;
    } finally {
      field.remove();
    }
  }

  if (copied) {
    showToast("Token sensora skopiowany do schowka.");
    return;
  }

  const selection = window.getSelection();
  if (selection) {
    const range = document.createRange();
    range.selectNodeContents(elements.sensorTokenValue);
    selection.removeAllRanges();
    selection.addRange(range);
  }
  showToast("Token został zaznaczony. Skopiuj go ręcznie przez Ctrl+C.", true);
}

async function saveSensorRegistration(event) {
  event.preventDefault();
  if (!adminToken) {
    showToast("Tryb operatora jest zablokowany.", true);
    return;
  }

  const latitudeText = elements.sensorLatitude.value.trim();
  const longitudeText = elements.sensorLongitude.value.trim();
  if (Boolean(latitudeText) !== Boolean(longitudeText)) {
    showToast("Podaj obie współrzędne albo pozostaw oba pola puste.", true);
    return;
  }

  const sensorId = editingSensorId;
  const payload = {
    display_name: elements.sensorDisplayName.value.trim(),
    position: latitudeText
      ? {
          latitude: Number(latitudeText),
          longitude: Number(longitudeText),
        }
      : null,
    actor: activeOperator,
  };
  if (!sensorId) {
    payload.sensor_key = elements.sensorKey.value.trim();
  }

  elements.sensorSave.disabled = true;
  try {
    const response = await adminRequest(
      sensorId ? `/api/v1/sensors/${encodeURIComponent(sensorId)}` : "/api/v1/sensors",
      sensorId ? "PUT" : "POST",
      payload,
    );
    if (sensorId) {
      cancelSensorRegistration();
      showToast(`Sensor „${response.sensor.display_name}” został zaktualizowany.`);
    } else {
      showSensorToken(response.sensor, response.credential);
    }
    await refresh();
  } catch (error) {
    showToast(
      `${sensorId ? "Edycja" : "Rejestracja"} sensora nie powiodła się: ${error.message}`,
      true,
    );
  } finally {
    elements.sensorSave.disabled = false;
  }
}

async function saveDrawnZone(event) {
  event.preventDefault();
  if (!adminToken || drawingPoints.length < 3) {
    showToast("Nie można zapisać niekompletnej strefy.", true);
    return;
  }

  const zoneId = editingZoneId;
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
    actor: activeOperator,
    geometry: {
      type: "Polygon",
      coordinates: [coordinates],
    },
  };

  elements.zoneSave.disabled = true;
  try {
    const response = await adminRequest(
      zoneId ? `/api/v1/zones/${encodeURIComponent(zoneId)}` : "/api/v1/zones",
      zoneId ? "PUT" : "POST",
      payload,
    );
    const savedZone = response.zone;
    cancelZoneDrawing();
    showToast(
      `Strefa „${savedZone.name}” została ${zoneId ? "zaktualizowana" : "utworzona"}.`,
    );
    await refresh();
    const layer = zoneLayers.get(savedZone.id);
    if (layer) {
      map.fitBounds(layer.getBounds(), { padding: [45, 45], maxZoom: 16 });
      layer.openPopup();
    }
  } catch (error) {
    showToast(
      `Nie udało się ${zoneId ? "zaktualizować" : "utworzyć"} strefy: ${error.message}`,
      true,
    );
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

function downloadAudit(format) {
  const category = encodeURIComponent(elements.auditCategory.value);
  const link = document.createElement("a");
  link.href = `/api/v1/audit/export?format=${format}&category=${category}`;
  link.download = "";
  document.body.append(link);
  link.click();
  link.remove();
}

async function refresh() {
  if (refreshInProgress) {
    return;
  }
  refreshInProgress = true;

  try {
    const includeEnded = elements.showEnded.checked ? "true" : "false";
    const includeClosedAlerts = elements.showClosedAlerts.checked ? "true" : "false";
    const auditCategory = encodeURIComponent(elements.auditCategory.value);
    const [sensorPayload, trackPayload, zonePayload, alertPayload, auditPayload] = await Promise.all([
      fetchJson("/api/v1/sensors"),
      fetchJson(`/api/v1/tracks?include_ended=${includeEnded}`),
      fetchJson("/api/v1/zones"),
      fetchJson(`/api/v1/alerts?include_closed=${includeClosedAlerts}`),
      fetchJson(`/api/v1/audit/events?category=${auditCategory}&limit=100`),
    ]);

    currentSensors = sensorPayload.sensors ?? [];
    currentTracks = trackPayload.tracks ?? [];
    currentZones = zonePayload.zones ?? [];
    currentAlerts = alertPayload.alerts ?? [];
    currentAuditEvents = auditPayload.events ?? [];
    currentAuditTotal = auditPayload.total ?? currentAuditEvents.length;

    updateZoneLayers(currentZones, currentAlerts);
    updateSensorMarkers(currentSensors);
    updateTrackMarkers(currentTracks);
    renderSensorList(currentSensors);
    renderTrackList(currentTracks);
    renderAlertList(currentAlerts);
    renderZoneList(currentZones, currentAlerts);
    renderAuditList(currentAuditEvents);

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
    elements.auditCount.textContent = String(currentAuditTotal);

    if (selectedTrackId) {
      const selected = currentTracks.find((track) => track.id === selectedTrackId);
      if (selected) {
        renderSelection(selected);
        await refreshSelectedHistory();
      } else {
        clearSelection();
      }
    } else if (selectedSensorId) {
      const selected = currentSensors.find((sensor) => sensor.id === selectedSensorId);
      if (selected) {
        renderSensorSelection(selected);
      } else {
        clearSelection();
      }
    } else if (selectedAuditEvent) {
      const refreshedEvent = currentAuditEvents.find(
        (event) => String(event.id) === String(selectedAuditEvent.id),
      );
      if (refreshedEvent) {
        selectedAuditEvent = refreshedEvent;
      }
      renderAuditSelection(selectedAuditEvent);
      await refreshSelectedAuditTimeline();
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
elements.auditCategory.addEventListener("change", () => {
  clearSelection();
  refresh();
});
elements.auditExportCsv.addEventListener("click", () => downloadAudit("csv"));
elements.auditExportJson.addEventListener("click", () => downloadAudit("json"));
elements.fitMap.addEventListener("click", fitAllEntities);
elements.closeSelection.addEventListener("click", clearSelection);
elements.operatorMenuToggle.addEventListener("click", toggleOperatorMenu);
elements.operatorLoginForm.addEventListener("submit", unlockOperator);
elements.operatorLock.addEventListener("click", () => lockOperator());
elements.drawZone.addEventListener("click", startZoneDrawing);
elements.registerSensor.addEventListener("click", startSensorRegistration);
elements.zoneUndoPoint.addEventListener("click", undoZonePoint);
elements.zoneClearPoints.addEventListener("click", clearZonePoints);
elements.zoneFinishDrawing.addEventListener("click", finishZoneDrawing);
elements.zoneCancelDrawing.addEventListener("click", cancelZoneDrawing);
elements.zoneForm.addEventListener("submit", saveDrawnZone);
elements.zoneBackToDrawing.addEventListener("click", returnToZoneDrawing);
elements.zoneCancelForm.addEventListener("click", cancelZoneDrawing);
elements.sensorForm.addEventListener("submit", saveSensorRegistration);
elements.sensorCancel.addEventListener("click", cancelSensorRegistration);
elements.sensorTokenCopy.addEventListener("click", copySensorToken);
elements.sensorTokenClose.addEventListener("click", closeSensorToken);
map.on("click", handleMapDrawingClick);
document.addEventListener("click", (event) => {
  if (operatorMenuOpen && !elements.operatorMenu.contains(event.target)) {
    setOperatorMenuOpen(false);
  }
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !elements.zoneEditor.classList.contains("hidden")) {
    cancelZoneDrawing();
  } else if (
    event.key === "Escape" &&
    !elements.sensorEditor.classList.contains("hidden")
  ) {
    cancelSensorRegistration();
  } else if (
    event.key === "Escape" &&
    !elements.sensorTokenPanel.classList.contains("hidden")
  ) {
    closeSensorToken();
  } else if (event.key === "Escape" && operatorMenuOpen) {
    setOperatorMenuOpen(false);
  }
});

initializeCollapsibleSections();
updateOperatorUi();
setOperatorMenuOpen(false);
refresh();
setInterval(refresh, REFRESH_INTERVAL_MS);
