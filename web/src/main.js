import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { forward as toMgrs } from "mgrs";

import "./styles.css";

const REFRESH_INTERVAL_MS = 2000;
const STORAGE_REFRESH_INTERVAL_MS = 60000;
const SECURITY_SUMMARY_INTERVAL_MS = 60000;
const DEFAULT_CENTER = [52.2297, 21.0122];
const SIDEBAR_STATE_KEY = "rdds.sidebar.sections.v1";
const DISPLAY_SETTINGS_KEY = "rdds.display.v1";
const ALERT_AUDIO_SETTINGS_KEY = "rdds.alert.audio.v1";
const CRITICAL_REPEAT_INTERVAL_MS = 30000;

let displaySettings = readDisplaySettings();
let currentTheme = displaySettings.theme === "light" ? "light" : "dark";
document.documentElement.dataset.theme = currentTheme;
document.documentElement.style.colorScheme = currentTheme;

const ALERT_SOUND_PROFILES = {
  detected: {
    waveform: "sawtooth",
    gain: 0.78,
    attackSeconds: 0.004,
    releaseSeconds: 0.025,
    steps: [
      { frequency: 1350, endFrequency: 720, duration: 0.26, gap: 0.09 },
      { frequency: 1350, endFrequency: 720, duration: 0.26, gap: 0.09 },
      { frequency: 1350, endFrequency: 720, duration: 0.26, gap: 0.09 },
      { frequency: 1350, endFrequency: 720, duration: 0.38, gap: 0 },
    ],
  },
  low: {
    waveform: "sawtooth",
    gain: 0.7,
    attackSeconds: 0.008,
    releaseSeconds: 0.04,
    steps: [
      { frequency: 420, endFrequency: 260, duration: 0.56, gap: 0.24 },
      { frequency: 420, endFrequency: 260, duration: 0.56, gap: 0.24 },
      { frequency: 420, endFrequency: 260, duration: 0.7, gap: 0 },
    ],
  },
  medium: {
    waveform: "square",
    gain: 0.74,
    attackSeconds: 0.004,
    releaseSeconds: 0.025,
    steps: [
      { frequency: 880, duration: 0.17, gap: 0.06 },
      { frequency: 620, duration: 0.17, gap: 0.24 },
      { frequency: 880, duration: 0.17, gap: 0.06 },
      { frequency: 620, duration: 0.17, gap: 0.24 },
      { frequency: 880, duration: 0.17, gap: 0.06 },
      { frequency: 620, duration: 0.17, gap: 0.24 },
      { frequency: 880, duration: 0.17, gap: 0.06 },
      { frequency: 620, duration: 0.28, gap: 0 },
    ],
  },
  high: {
    waveform: "sawtooth",
    gain: 0.8,
    attackSeconds: 0.006,
    releaseSeconds: 0.035,
    steps: [
      { frequency: 620, endFrequency: 1450, duration: 0.64, gap: 0.04 },
      { frequency: 1450, endFrequency: 620, duration: 0.64, gap: 0.1 },
      { frequency: 620, endFrequency: 1450, duration: 0.64, gap: 0.04 },
      { frequency: 1450, endFrequency: 620, duration: 0.64, gap: 0.1 },
      { frequency: 620, endFrequency: 1450, duration: 0.64, gap: 0.04 },
      { frequency: 1450, endFrequency: 620, duration: 0.78, gap: 0 },
    ],
  },
  critical: {
    waveform: "square",
    gain: 0.82,
    attackSeconds: 0.003,
    releaseSeconds: 0.02,
    steps: Array.from({ length: 18 }, (_, index) => ({
      frequency: index % 2 === 0 ? 1450 : 580,
      duration: index === 17 ? 0.3 : 0.13,
      gap: index === 17 ? 0 : 0.045,
    })),
  },
};

const stateLabels = {
  new: "nowy",
  active: "aktywny",
  stale: "nieaktualny",
  ended: "zakończony",
  anomalous: "anomalia",
  no_gps: "brak GPS",
  online: "online",
  degraded: "ograniczony",
  offline: "offline",
  maintenance: "konserwacja",
  disabled: "wyłączony",
  provisioning: "konfiguracja",
  acknowledged: "przyjęty",
  closed: "zamknięty",
  inactive: "wyłączona",
};

const sensorHealthReasonLabels = {
  healthy: "tor detekcji działa prawidłowo",
  awaiting_heartbeat: "oczekiwanie na pierwszy heartbeat",
  source_unavailable: "brak połączenia ze źródłem Sky-Spy",
  source_silent: "Sky-Spy nie przesyła komunikatów kontrolnych",
  queue_backlog: "zaległa kolejka wysyłkowa",
  dead_letter: "wiadomości w kolejce błędów",
  heartbeat_timeout: "brak heartbeat agenta",
  maintenance: "zaplanowana konserwacja",
  disabled: "sensor wyłączony administracyjnie",
};

const severityLabels = {
  low: "niski",
  medium: "średni",
  high: "wysoki",
  critical: "krytyczny",
};

const alertStateLabels = {
  active: "nowy",
  acknowledged: "potwierdzony",
  closed: "zamknięty",
};

const severityColors = {
  low: "#43d5ff",
  medium: "#ffb84d",
  high: "#ff7547",
  critical: "#ff2841",
};

const presenceLabels = {
  inside: "w strefie",
  left: "opuścił strefę",
  lost: "utracono ślad",
};

const auditEventLabels = {
  track_detected: "Nowy dron w zasięgu sensora",
  alert_opened: "Otwarto alarm",
  alert_acknowledged: "Potwierdzono alarm",
  alert_closed: "Zamknięto alarm",
  alert_presence_changed: "Zmienił się stan obecności",
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
  sensor_online: "Sensor rozpoczął pracę",
  sensor_degraded: "Ograniczona sprawność sensora",
  sensor_offline: "Utracono łączność z sensorem",
  sensor_health_changed: "Zmienił się stan usterki sensora",
  sensor_recovered: "Sensor odzyskał sprawność",
  sensor_maintenance_started: "Rozpoczęto konserwację sensora",
  sensor_maintenance_ended: "Zakończono konserwację sensora",
  operator_created: "Utworzono konto",
  operator_updated: "Zmieniono konto",
  operator_enabled: "Włączono konto",
  operator_disabled: "Wyłączono konto",
  operator_deleted: "Usunięto konto",
  operator_password_changed: "Zmieniono hasło konta",
  operator_logged_in: "Logowanie do RDDS",
  operator_logged_out: "Wylogowanie z RDDS",
  operator_session_revoked: "Zakończono sesję konta RDDS",
  operator_sessions_revoked: "Zakończono sesje konta RDDS",
  operator_security_exported: "Wyeksportowano dziennik bezpieczeństwa",
};

const securityEventLabels = {
  login_succeeded: "Udane logowanie",
  login_failed: "Nieudane logowanie",
  account_locked: "Konto zablokowane",
  session_logged_out: "Wylogowanie",
  session_revoked: "Sesja zakończona przez administratora",
  sessions_revoked: "Zakończono wiele sesji",
};

const stateColors = {
  new: "#43d5ff",
  active: "#35e69a",
  stale: "#ffb84d",
  ended: "#778292",
  anomalous: "#ff4d5e",
  no_gps: "#b48cff",
};
const LIVE_TRAIL_SECONDS = 60;
const LIVE_TRAIL_POINT_LIMIT = 100;

const elements = {
  workspace: document.querySelector(".workspace"),
  sidebar: document.querySelector("#sidebar"),
  sidebarToggle: document.querySelector("#sidebar-toggle"),
  sidebarToggleLabel: document.querySelector("#sidebar-toggle-label"),
  themeToggle: document.querySelector("#theme-toggle"),
  themeToggleIcon: document.querySelector("#theme-toggle-icon"),
  themeToggleLabel: document.querySelector("#theme-toggle-label"),
  connectionDot: document.querySelector("#connection-dot"),
  connectionLabel: document.querySelector("#connection-label"),
  lastUpdate: document.querySelector("#last-update"),
  alarmAudioToggle: document.querySelector("#alarm-audio-toggle"),
  alarmAudioTest: document.querySelector("#alarm-audio-test"),
  alarmAudioTestProfile: document.querySelector("#alarm-audio-test-profile"),
  alarmAudioVolume: document.querySelector("#alarm-audio-volume"),
  alarmAudioVolumeValue: document.querySelector("#alarm-audio-volume-value"),
  alarmAudioRepeat: document.querySelector("#alarm-audio-repeat"),
  onlineSensors: document.querySelector("#online-sensors"),
  activeTracks: document.querySelector("#active-tracks"),
  openAlerts: document.querySelector("#open-alerts"),
  loginScreen: document.querySelector("#login-screen"),
  loginForm: document.querySelector("#login-form"),
  loginUsername: document.querySelector("#login-username"),
  loginPassword: document.querySelector("#login-password"),
  loginSubmit: document.querySelector("#login-submit"),
  loginMessage: document.querySelector("#login-message"),
  operatorMenu: document.querySelector("#operator-menu"),
  operatorMenuToggle: document.querySelector("#operator-menu-toggle"),
  operatorStatus: document.querySelector("#operator-status"),
  operatorPanel: document.querySelector("#operator-panel"),
  operatorModeLabel: document.querySelector("#operator-mode-label"),
  operatorLockIndicator: document.querySelector("#operator-lock-indicator"),
  operatorTabButtons: document.querySelectorAll("[data-operator-tab]"),
  operatorTabPanels: document.querySelectorAll("[data-operator-tab-panel]"),
  operatorAdminTab: document.querySelector("#operator-tab-admin"),
  operatorAccountTab: document.querySelector("#operator-tab-account"),
  alarmTrainingTools: document.querySelector("#alarm-training-tools"),
  passwordForm: document.querySelector("#password-form"),
  currentPassword: document.querySelector("#current-password"),
  newPassword: document.querySelector("#new-password"),
  passwordSubmit: document.querySelector("#password-submit"),
  operatorMessage: document.querySelector("#operator-message"),
  operatorActions: document.querySelector("#operator-actions"),
  operatorLock: document.querySelector("#operator-lock"),
  drawZone: document.querySelector("#draw-zone"),
  registerSensor: document.querySelector("#register-sensor"),
  manageOperators: document.querySelector("#manage-operators"),
  manageSecurity: document.querySelector("#manage-security"),
  storagePanel: document.querySelector("#storage-panel"),
  storageRefresh: document.querySelector("#storage-refresh"),
  storageUsage: document.querySelector("#storage-usage"),
  storageMeter: document.querySelector("#storage-meter"),
  storageBar: document.querySelector("#storage-bar"),
  storagePercent: document.querySelector("#storage-percent"),
  storageLargestTable: document.querySelector("#storage-largest-table"),
  storageMessage: document.querySelector("#storage-message"),
  operatorEditor: document.querySelector("#operator-editor"),
  operatorEditorClose: document.querySelector("#operator-editor-close"),
  operatorCreateForm: document.querySelector("#operator-create-form"),
  accountUsername: document.querySelector("#account-username"),
  accountDisplayName: document.querySelector("#account-display-name"),
  accountRole: document.querySelector("#account-role"),
  accountPassword: document.querySelector("#account-password"),
  accountCreate: document.querySelector("#account-create"),
  operatorList: document.querySelector("#operator-list"),
  securityEditor: document.querySelector("#security-editor"),
  securityEditorClose: document.querySelector("#security-editor-close"),
  securityRefresh: document.querySelector("#security-refresh"),
  securityActiveSessions: document.querySelector("#security-active-sessions"),
  securityRecentFailures: document.querySelector("#security-recent-failures"),
  securityLockedAccounts: document.querySelector("#security-locked-accounts"),
  securitySourceAddresses: document.querySelector("#security-source-addresses"),
  securityAlertMessage: document.querySelector("#security-alert-message"),
  securitySessionCount: document.querySelector("#security-session-count"),
  securitySessionList: document.querySelector("#security-session-list"),
  securityEventCount: document.querySelector("#security-event-count"),
  securityEventList: document.querySelector("#security-event-list"),
  securityWindow: document.querySelector("#security-window"),
  securityOutcome: document.querySelector("#security-outcome"),
  securityEventType: document.querySelector("#security-event-type"),
  securityUsername: document.querySelector("#security-username"),
  securityApplyFilters: document.querySelector("#security-apply-filters"),
  securityExportCsv: document.querySelector("#security-export-csv"),
  securityExportJson: document.querySelector("#security-export-json"),
  trackCount: document.querySelector("#track-count"),
  sensorCount: document.querySelector("#sensor-count"),
  alertCount: document.querySelector("#alert-count"),
  zoneCount: document.querySelector("#zone-count"),
  auditCount: document.querySelector("#audit-count"),
  trackList: document.querySelector("#track-list"),
  archivedTracksSection: document.querySelector('[data-section-key="archived-tracks"]'),
  archivedTrackCount: document.querySelector("#archived-track-count"),
  archivedTrackList: document.querySelector("#archived-track-list"),
  sensorList: document.querySelector("#sensor-list"),
  sensorHealthBanner: document.querySelector("#sensor-health-banner"),
  alertList: document.querySelector("#alert-list"),
  alertsSection: document.querySelector('[data-section-key="alerts"]'),
  closedAlertsSection: document.querySelector('[data-section-key="closed-alerts"]'),
  closedAlertCount: document.querySelector("#closed-alert-count"),
  closedAlertList: document.querySelector("#closed-alert-list"),
  closedAlertFrom: document.querySelector("#closed-alert-from"),
  closedAlertTo: document.querySelector("#closed-alert-to"),
  closedAlertApply: document.querySelector("#closed-alert-apply"),
  closedAlertReset: document.querySelector("#closed-alert-reset"),
  sensorsSection: document.querySelector('[data-section-key="sensors"]'),
  zonesSection: document.querySelector('[data-section-key="zones"]'),
  zoneList: document.querySelector("#zone-list"),
  auditList: document.querySelector("#audit-list"),
  auditCategory: document.querySelector("#audit-category"),
  auditRefresh: document.querySelector("#audit-refresh"),
  auditExportCsv: document.querySelector("#audit-export-csv"),
  auditExportJson: document.querySelector("#audit-export-json"),
  fitMap: document.querySelector("#fit-map"),
  selectionPanel: document.querySelector("#selection-panel"),
  selectionEyebrow: document.querySelector("#selection-eyebrow"),
  selectionTitle: document.querySelector("#selection-title"),
  selectionDetails: document.querySelector("#selection-details"),
  selectionTimelineTitle: document.querySelector("#selection-timeline-title"),
  incidentControls: document.querySelector("#incident-controls"),
  incidentShowEntry: document.querySelector("#incident-show-entry"),
  incidentShowLive: document.querySelector("#incident-show-live"),
  incidentShowRoute: document.querySelector("#incident-show-route"),
  trackControls: document.querySelector("#track-controls"),
  trackFollowLive: document.querySelector("#track-follow-live"),
  trackReplay: document.querySelector("#track-replay"),
  trackPlayer: document.querySelector("#track-player"),
  trackReplaySeek: document.querySelector("#track-replay-seek"),
  trackReplayStartTime: document.querySelector("#track-replay-start-time"),
  trackReplayCurrentTime: document.querySelector("#track-replay-current-time"),
  trackReplayEndTime: document.querySelector("#track-replay-end-time"),
  trackReplayBack: document.querySelector("#track-replay-back"),
  trackReplayPause: document.querySelector("#track-replay-pause"),
  trackReplayForward: document.querySelector("#track-replay-forward"),
  trackReplayStop: document.querySelector("#track-replay-stop"),
  trackReplaySpeed: document.querySelector("#track-replay-speed"),
  trackReplayStatus: document.querySelector("#track-replay-status"),
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
const liveTrailLayers = new Map();
const zoneLayers = new Map();
let currentSensors = [];
let currentTracks = [];
let currentLiveTracks = [];
let currentArchivedTracks = [];
let currentLiveTrails = [];
let currentZones = [];
let currentAlerts = [];
let currentOpenAlerts = [];
let currentClosedAlerts = [];
const pendingAlertActions = new Map();
let alertDataRevision = 0;
let currentAuditEvents = [];
let currentAuditTotal = 0;
let selectedTrackId = null;
let selectedTrackSnapshot = null;
let selectedSensorId = null;
let selectedZoneId = null;
let selectedAuditEvent = null;
let selectedAlertId = null;
let selectedAlertSnapshot = null;
let sidebarResizeTimer = null;
let liveFollowTrackId = null;
let replayTrackId = null;
let replayObservations = [];
let replayTotalObservations = 0;
let replayIndex = 0;
let replayRenderedIndex = -1;
let replayAnimationFrame = null;
let replayClockTimeMs = 0;
let replayLastFrameAt = null;
let replayPaused = false;
let replayCompleted = false;
let replayMarker = null;
let replayPilotMarker = null;
let replayOperatorLine = null;
let replayTrail = null;
let archivePreviewMarker = null;
let archivePreviewPilotMarker = null;
let archivePreviewOperatorLine = null;
let incidentTrail = null;
let incidentEntryMarker = null;
let alertAudioContext = null;
let alertAudioMasterGain = null;
let activeAlertOscillators = new Set();
let alertAudioBaselineReady = false;
let knownAlertIds = new Set();
let trackAudioBaselineReady = false;
let knownTrackIds = new Set();
let sensorHealthBaselineReady = false;
let knownSensorIssueIds = new Set();
let alertAudioSettings = {
  enabled: false,
  volume: 0.8,
  repeatCritical: true,
};
let initialFitComplete = false;
let initialLiveDataLoaded = false;
let refreshInProgress = false;
let archiveLoadInProgress = false;
let archivedTracksLoaded = false;
let closedAlertsLoadInProgress = false;
let closedAlertsLoaded = false;
let zonesLoadInProgress = false;
let auditLoadInProgress = false;
let zonesLoaded = false;
let storageRefreshInProgress = false;
let lastStorageRefreshAt = 0;
let lastSecuritySummaryAt = 0;
let securitySummaryInProgress = false;
let securityCenterLoadInProgress = false;
let currentUser = null;
let csrfToken = null;
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
  if (value >= 1024 ** 4) {
    return `${(value / 1024 ** 4).toFixed(2)} TiB`;
  }
  if (value >= 1024 ** 3) {
    return `${(value / 1024 ** 3).toFixed(2)} GiB`;
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
  if (minutes === 0) {
    return `${seconds} s`;
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

function formatCompactDateTime(value) {
  if (!value) {
    return "—";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "—";
  }
  return date.toLocaleString("pl-PL", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
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

function sensorHealthReasonLabel(reason) {
  return sensorHealthReasonLabels[reason] ?? reason ?? "brak danych diagnostycznych";
}

function sourceConnectionLabel(value) {
  if (value === true) return "połączone";
  if (value === false) return "rozłączone";
  return "brak telemetrii";
}

function alertStateLabel(state) {
  return alertStateLabels[state] ?? stateLabel(state);
}

function severityLabel(severity) {
  return severityLabels[severity] ?? severity ?? "—";
}

function presenceLabel(presence) {
  return presenceLabels[presence] ?? presence ?? "—";
}

function readAlertAudioSettings() {
  try {
    const stored = JSON.parse(localStorage.getItem(ALERT_AUDIO_SETTINGS_KEY) || "{}");
    const storedVolume = Number(stored.volume);
    return {
      enabled: stored.enabled === true,
      volume: Number.isFinite(storedVolume)
        ? Math.min(1, Math.max(0, storedVolume))
        : 0.8,
      repeatCritical: stored.repeatCritical !== false,
    };
  } catch {
    return { enabled: false, volume: 0.8, repeatCritical: true };
  }
}

function writeAlertAudioSettings() {
  try {
    localStorage.setItem(ALERT_AUDIO_SETTINGS_KEY, JSON.stringify(alertAudioSettings));
  } catch {
    // Powiadomienia nadal działają w bieżącej karcie bez localStorage.
  }
}

function renderAlertAudioSettings() {
  elements.alarmAudioToggle.classList.toggle("muted", !alertAudioSettings.enabled);
  elements.alarmAudioToggle.classList.toggle("enabled", alertAudioSettings.enabled);
  elements.alarmAudioToggle.setAttribute("aria-pressed", String(!alertAudioSettings.enabled));
  elements.alarmAudioToggle.textContent = alertAudioSettings.enabled
    ? "Wycisz alarmy"
    : "Alarmy wyciszone";
  elements.alarmAudioToggle.title = alertAudioSettings.enabled
    ? "Natychmiast zatrzymaj i wycisz alarmy"
    : "Włącz alarmy wykrycia i naruszenia stref";
  elements.alarmAudioVolume.value = String(alertAudioSettings.volume);
  elements.alarmAudioVolumeValue.textContent = `${Math.round(
    alertAudioSettings.volume * 100,
  )}%`;
  elements.alarmAudioTest.disabled = !alertAudioSettings.enabled;
  elements.alarmAudioTestProfile.disabled = !alertAudioSettings.enabled;
  elements.alarmAudioRepeat.checked = alertAudioSettings.repeatCritical;
}

function updateAlertAudioMasterVolume() {
  if (!alertAudioContext || !alertAudioMasterGain) return;
  const now = alertAudioContext.currentTime;
  alertAudioMasterGain.gain.cancelScheduledValues(now);
  alertAudioMasterGain.gain.setTargetAtTime(
    alertAudioSettings.volume,
    now,
    0.01,
  );
}

async function ensureAlertAudioContext() {
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  if (!AudioContextClass) {
    throw new Error("Ta przeglądarka nie obsługuje dźwięku alarmowego");
  }
  if (!alertAudioContext) {
    alertAudioContext = new AudioContextClass();
    alertAudioMasterGain = alertAudioContext.createGain();
    alertAudioMasterGain.gain.setValueAtTime(
      alertAudioSettings.volume,
      alertAudioContext.currentTime,
    );
    alertAudioMasterGain.connect(alertAudioContext.destination);
  }
  if (alertAudioContext.state === "suspended") {
    await alertAudioContext.resume();
  }
  return alertAudioContext;
}

function stopActiveAlertSounds() {
  for (const oscillator of activeAlertOscillators) {
    oscillator.onended = null;
    try {
      oscillator.stop();
    } catch {
      // Oscylator mógł zakończyć się pomiędzy iteracjami.
    }
  }
  activeAlertOscillators = new Set();
}

async function playAlertSound(profileName = "high") {
  if (!alertAudioSettings.enabled) return;
  const profile = ALERT_SOUND_PROFILES[profileName] ?? ALERT_SOUND_PROFILES.high;
  try {
    const context = await ensureAlertAudioContext();
    if (!alertAudioSettings.enabled) return;
    stopActiveAlertSounds();
    updateAlertAudioMasterVolume();
    const start = context.currentTime + 0.02;
    let offset = 0;
    profile.steps.forEach((step) => {
      const oscillator = context.createOscillator();
      const gain = context.createGain();
      const toneStart = start + offset;
      const toneEnd = toneStart + step.duration;
      const attackSeconds = Math.min(
        profile.attackSeconds ?? 0.02,
        step.duration / 4,
      );
      const releaseSeconds = Math.min(
        profile.releaseSeconds ?? 0.06,
        step.duration / 4,
      );
      oscillator.type = profile.waveform;
      oscillator.frequency.setValueAtTime(step.frequency, toneStart);
      if (step.endFrequency && step.endFrequency !== step.frequency) {
        oscillator.frequency.exponentialRampToValueAtTime(
          step.endFrequency,
          toneEnd - releaseSeconds,
        );
      }
      gain.gain.setValueAtTime(0.0001, toneStart);
      gain.gain.exponentialRampToValueAtTime(
        profile.gain,
        toneStart + attackSeconds,
      );
      gain.gain.setValueAtTime(profile.gain, toneEnd - releaseSeconds);
      gain.gain.exponentialRampToValueAtTime(0.0001, toneEnd);
      oscillator.connect(gain);
      gain.connect(alertAudioMasterGain);
      activeAlertOscillators.add(oscillator);
      oscillator.onended = () => activeAlertOscillators.delete(oscillator);
      oscillator.start(toneStart);
      oscillator.stop(toneEnd + 0.03);
      offset += step.duration + step.gap;
    });
  } catch (error) {
    showToast(`Nie udało się odtworzyć alarmu: ${error.message}`, true);
  }
}

function highestAlertSeverity(alerts) {
  const order = { low: 0, medium: 1, high: 2, critical: 3 };
  return alerts.reduce(
    (highest, alert) => order[alert.severity] > order[highest] ? alert.severity : highest,
    "low",
  );
}

function processOperationalSounds(tracks, alerts) {
  const audibleTracks = tracks.filter(
    (track) => ["new", "active", "anomalous"].includes(track.state),
  );
  const trackIds = audibleTracks.map((track) => String(track.id));
  const alertIds = alerts.map((alert) => String(alert.id));
  if (!alertAudioBaselineReady || !trackAudioBaselineReady) {
    knownAlertIds = new Set(alertIds);
    knownTrackIds = new Set(trackIds);
    alertAudioBaselineReady = true;
    trackAudioBaselineReady = true;
    return;
  }
  const newAlerts = alerts.filter(
    (alert) => alert.state === "active" && !knownAlertIds.has(String(alert.id)),
  );
  const newTracks = audibleTracks.filter(
    (track) => !knownTrackIds.has(String(track.id)),
  );
  alertIds.forEach((id) => knownAlertIds.add(id));
  trackIds.forEach((id) => knownTrackIds.add(id));
  if (newAlerts.length > 0) {
    revealAlertsSectionForNewAlarm();
    void playAlertSound(highestAlertSeverity(newAlerts));
  } else if (newTracks.length > 0) {
    void playAlertSound("detected");
  }
}

function initializeAlertAudioSettings() {
  alertAudioSettings = readAlertAudioSettings();
  renderAlertAudioSettings();
  document.addEventListener(
    "pointerdown",
    () => {
      if (alertAudioSettings.enabled) {
        void ensureAlertAudioContext();
      }
    },
    { once: true, capture: true },
  );
}

async function toggleAlertAudio() {
  if (!alertAudioSettings.enabled) {
    try {
      await ensureAlertAudioContext();
      alertAudioSettings.enabled = true;
      updateAlertAudioMasterVolume();
      showToast("Alarmy dźwiękowe zostały włączone.");
    } catch (error) {
      alertAudioSettings.enabled = false;
      showToast(`Nie udało się włączyć dźwięku: ${error.message}`, true);
    }
  } else {
    alertAudioSettings.enabled = false;
    stopActiveAlertSounds();
    showToast("Bieżący alarm zatrzymano. Następne alarmy są wyciszone.");
  }
  writeAlertAudioSettings();
  renderAlertAudioSettings();
}

function repeatCriticalAlertSound() {
  if (
    alertAudioSettings.enabled &&
    alertAudioSettings.repeatCritical &&
    activeAlertOscillators.size === 0 &&
    currentOpenAlerts.some(
      (alert) => alert.state === "active" && alert.severity === "critical",
    )
  ) {
    void playAlertSound("critical");
  }
}

function auditEventLabel(eventType) {
  return auditEventLabels[eventType] ?? eventType ?? "—";
}

function auditEventCategory(event) {
  const eventType = event?.event_type ?? "";
  if (eventType.startsWith("track_")) return "track";
  if (eventType.startsWith("alert_")) return "alert";
  if (eventType.startsWith("zone_")) return "zone";
  if (eventType.startsWith("sensor_")) return "sensor";
  if (eventType.startsWith("operator_")) return "account";
  return "system";
}

function auditTimelineTitle(event) {
  if (event?.alert_id || auditEventCategory(event) === "alert") {
    return "Historia alarmu strefowego";
  }
  if (event?.track_id || auditEventCategory(event) === "track") {
    return "Historia wykrycia drona";
  }
  if (event?.sensor_id || auditEventCategory(event) === "sensor") {
    return "Historia sensora";
  }
  if (event?.operator_account_id || auditEventCategory(event) === "account") {
    return "Historia konta RDDS";
  }
  if (event?.zone_id || auditEventCategory(event) === "zone") {
    return "Historia strefy chronionej";
  }
  return "Powiązane zdarzenia";
}

function openAlertCountForTrack(trackId) {
  return currentOpenAlerts.filter((alert) => alert.track_id === trackId).length;
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
  { method = "GET", body = null, csrf = false } = {},
) {
  const headers = { Accept: "application/json" };
  if (body !== null) {
    headers["Content-Type"] = "application/json";
  }
  if (csrf && csrfToken) {
    headers["X-RDDS-CSRF-Token"] = csrfToken;
  }

  const response = await fetch(path, {
    method,
    headers,
    body: body === null ? null : JSON.stringify(body),
    cache: "no-store",
    credentials: "same-origin",
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

function renderLoadingCards(list, count = 3) {
  list.replaceChildren();
  list.classList.remove("empty-state");
  list.classList.add("loading-list");
  list.setAttribute("aria-busy", "true");
  for (let index = 0; index < count; index += 1) {
    const card = document.createElement("div");
    card.className = "loading-card";
    card.setAttribute("aria-hidden", "true");
    const title = document.createElement("span");
    title.className = "loading-line loading-line-title";
    const meta = document.createElement("span");
    meta.className = "loading-line loading-line-meta";
    card.append(title, meta);
    list.append(card);
  }
}

function finishListLoading(list) {
  list.classList.remove("loading-list");
  list.removeAttribute("aria-busy");
}

function renderListFailure(list, message) {
  list.replaceChildren();
  finishListLoading(list);
  list.classList.add("empty-state");
  list.textContent = message;
}

function storageStatusMessage(status, thresholds) {
  if (status === "warning") {
    return `Przekroczono próg ostrzegawczy ${thresholds.warning_percent}%.`;
  }
  if (status === "critical") {
    return `Przekroczono próg krytyczny ${thresholds.critical_percent}%.`;
  }
  if (status === "exceeded") {
    return "Skonfigurowany budżet bazy został przekroczony.";
  }
  if (status === "unconfigured") {
    return "Ustaw RDDS_DATABASE_CAPACITY_GB, aby włączyć procent wykorzystania.";
  }
  return "Wykorzystanie mieści się poniżej progu ostrzegawczego.";
}

function renderStorageUsage(payload) {
  const status = payload.status ?? "unconfigured";
  const usedPercent = payload.used_percent;
  const capacityBytes = payload.capacity_bytes;
  const largestTable = payload.largest_tables?.[0];

  elements.storagePanel.classList.remove(
    "storage-ok",
    "storage-warning",
    "storage-critical",
    "storage-exceeded",
    "storage-unconfigured",
  );
  elements.storagePanel.classList.add(`storage-${status}`);
  elements.storageMeter.classList.toggle("unconfigured", usedPercent === null);
  elements.storageBar.style.width = `${Math.min(100, Math.max(0, usedPercent ?? 0))}%`;
  elements.storageUsage.textContent = capacityBytes
    ? `${formatBytes(payload.database_size_bytes)} / ${formatBytes(capacityBytes)}`
    : `${formatBytes(payload.database_size_bytes)} · limit nieustawiony`;
  elements.storagePercent.textContent = usedPercent === null
    ? "Brak limitu"
    : `${usedPercent.toLocaleString("pl-PL", { maximumFractionDigits: 2 })}%`;
  elements.storageLargestTable.textContent = largestTable
    ? `Największa: ${largestTable.table_name} · ${formatBytes(largestTable.size_bytes)}`
    : "Brak tabel użytkownika";
  elements.storageMessage.textContent = storageStatusMessage(
    status,
    payload.thresholds,
  );
  if (usedPercent === null) {
    elements.storageMeter.removeAttribute("aria-valuenow");
  } else {
    elements.storageMeter.setAttribute("aria-valuenow", String(usedPercent));
  }
}

async function loadStorageUsage(force = false) {
  if (!canAdminister() || storageRefreshInProgress) {
    return;
  }
  if (
    !force &&
    lastStorageRefreshAt > 0 &&
    Date.now() - lastStorageRefreshAt < STORAGE_REFRESH_INTERVAL_MS
  ) {
    return;
  }

  storageRefreshInProgress = true;
  elements.storageRefresh.disabled = true;
  elements.storageRefresh.setAttribute("aria-busy", "true");
  elements.storagePanel.setAttribute("aria-busy", "true");
  if (lastStorageRefreshAt === 0) {
    elements.storageUsage.textContent = "Wczytywanie…";
    elements.storageMessage.textContent = "Pobieranie informacji o bazie…";
  }
  try {
    const payload = await fetchJson("/api/v1/system/storage");
    renderStorageUsage(payload);
    lastStorageRefreshAt = Date.now();
  } catch (error) {
    elements.storagePanel.classList.remove(
      "storage-ok",
      "storage-warning",
      "storage-critical",
      "storage-exceeded",
      "storage-unconfigured",
    );
    elements.storagePanel.classList.add("storage-critical");
    elements.storageMessage.textContent = `Nie udało się pobrać danych: ${error.message}`;
  } finally {
    storageRefreshInProgress = false;
    elements.storageRefresh.disabled = false;
    elements.storageRefresh.removeAttribute("aria-busy");
    elements.storagePanel.removeAttribute("aria-busy");
  }
}

function renderSecuritySummary(summary) {
  elements.securityActiveSessions.textContent = formatInteger(summary.active_sessions);
  elements.securityRecentFailures.textContent = formatInteger(summary.recent_failures);
  elements.securityLockedAccounts.textContent = formatInteger(summary.locked_accounts);
  elements.securitySourceAddresses.textContent = formatInteger(summary.source_addresses);
  const alertActive = Boolean(summary.alert_active);
  elements.operatorMenuToggle.classList.toggle("security-alert", alertActive);
  elements.securityAlertMessage.classList.toggle("active", alertActive);
  elements.securityAlertMessage.textContent = alertActive
    ? `${summary.recent_failures} nieudanych logowań w ciągu ${summary.failure_window_minutes} min — przekroczono próg ${summary.failure_alert_count}.`
    : `Brak ostrzeżenia: ${summary.recent_failures} nieudanych logowań w ciągu ${summary.failure_window_minutes} min.`;
}

async function loadSecurityIndicator(force = false) {
  if (!canAdminister() || securitySummaryInProgress) {
    return;
  }
  if (
    !force &&
    lastSecuritySummaryAt > 0 &&
    Date.now() - lastSecuritySummaryAt < SECURITY_SUMMARY_INTERVAL_MS
  ) {
    return;
  }
  securitySummaryInProgress = true;
  try {
    const payload = await fetchJson("/api/v1/security/summary");
    renderSecuritySummary(payload.summary ?? {});
    lastSecuritySummaryAt = Date.now();
  } catch (error) {
    console.error("Nie udało się pobrać podsumowania bezpieczeństwa", error);
  } finally {
    securitySummaryInProgress = false;
  }
}

function securityQueryString() {
  const parameters = new URLSearchParams();
  const outcome = elements.securityOutcome.value;
  const eventType = elements.securityEventType.value;
  const username = elements.securityUsername.value.trim();
  const windowMinutes = elements.securityWindow.value;
  if (outcome) parameters.set("outcome", outcome);
  if (eventType) parameters.set("event_type", eventType);
  if (username) parameters.set("username", username);
  if (windowMinutes !== "all") {
    const occurredAfter = new Date(
      Date.now() - Number(windowMinutes) * 60 * 1000,
    );
    parameters.set("occurred_after", occurredAfter.toISOString());
  }
  return parameters;
}

function securityReasonLabel(reason) {
  const labels = {
    unknown_account: "nieznane konto",
    invalid_credentials: "nieprawidłowe dane logowania",
    account_disabled: "konto wyłączone",
    account_locked: "konto czasowo zablokowane",
    password_change: "zmiana hasła",
    password_reset: "reset hasła",
    role_changed: "zmiana roli",
    account_deleted: "usunięcie konta",
  };
  return labels[reason] ?? reason ?? "—";
}

function renderSecuritySessions(sessions) {
  elements.securitySessionList.replaceChildren();
  elements.securitySessionList.classList.toggle("empty-state", sessions.length === 0);
  elements.securitySessionCount.textContent = String(sessions.length);
  if (sessions.length === 0) {
    elements.securitySessionList.textContent = "Brak aktywnych sesji";
    return;
  }

  const accountActions = new Set();
  const accountSessionCounts = sessions.reduce((counts, session) => {
    counts.set(session.operator_id, (counts.get(session.operator_id) ?? 0) + 1);
    return counts;
  }, new Map());
  for (const session of sessions) {
    const card = document.createElement("div");
    card.className = `entity-card managed-card security-session${session.is_current ? " current" : ""}`;
    const main = document.createElement("div");
    main.className = "managed-card-main";
    const titleRow = document.createElement("div");
    titleRow.className = "entity-title-row";
    const title = document.createElement("strong");
    title.textContent = `${session.display_name} (${session.username})`;
    const badge = document.createElement("span");
    badge.className = "state-badge state-active";
    badge.textContent = session.is_current ? "bieżąca" : "aktywna";
    titleRow.append(title, badge);
    const meta = document.createElement("div");
    meta.className = "entity-meta security-session-meta";
    const address = document.createElement("span");
    address.textContent = `IP: ${session.remote_address || "—"}`;
    const lastSeen = document.createElement("span");
    lastSeen.textContent = `Aktywność: ${formatDateTime(session.last_seen_at)}`;
    const expires = document.createElement("span");
    expires.textContent = `Wygaśnie: ${formatDateTime(session.idle_expires_at)}`;
    const agent = document.createElement("span");
    agent.className = "security-user-agent";
    agent.textContent = session.user_agent || "Nieznana przeglądarka";
    meta.append(address, lastSeen, expires, agent);
    main.append(titleRow, meta);
    card.append(main);

    const actions = document.createElement("div");
    actions.className = "managed-actions";
    if (!session.is_current) {
      const revoke = document.createElement("button");
      revoke.type = "button";
      revoke.className = "danger-button";
      revoke.textContent = "Zakończ sesję";
      revoke.addEventListener("click", async () => {
        if (!window.confirm(`Zakończyć tę sesję konta ${session.username}?`)) return;
        revoke.disabled = true;
        try {
          await adminRequest(`/api/v1/security/sessions/${session.id}`, "DELETE", {});
          showToast("Sesja została zakończona.");
          await loadSecurityCenter();
        } catch (error) {
          showToast(`Zakończenie sesji nie powiodło się: ${error.message}`, true);
        } finally {
          revoke.disabled = false;
        }
      });
      actions.append(revoke);
    }
    if (
      accountSessionCounts.get(session.operator_id) > 1 &&
      !accountActions.has(session.operator_id)
    ) {
      accountActions.add(session.operator_id);
      const revokeAll = document.createElement("button");
      revokeAll.type = "button";
      revokeAll.className = "secondary-button";
      revokeAll.textContent = session.operator_id === currentUser.id
        ? "Zakończ pozostałe"
        : "Zakończ wszystkie";
      revokeAll.addEventListener("click", async () => {
        if (!window.confirm(`Zakończyć aktywne sesje konta ${session.username}?`)) return;
        revokeAll.disabled = true;
        try {
          const payload = await adminRequest(
            `/api/v1/security/operators/${session.operator_id}/sessions/revoke`,
            "POST",
            {},
          );
          showToast(`Zakończone sesje: ${payload.revoked_sessions}.`);
          await loadSecurityCenter();
        } catch (error) {
          showToast(`Zakończenie sesji nie powiodło się: ${error.message}`, true);
        } finally {
          revokeAll.disabled = false;
        }
      });
      actions.append(revokeAll);
    }
    if (actions.childElementCount) card.append(actions);
    elements.securitySessionList.append(card);
  }
}

function renderSecurityEvents(events, total) {
  elements.securityEventList.replaceChildren();
  elements.securityEventList.classList.toggle("empty-state", events.length === 0);
  elements.securityEventCount.textContent = String(total);
  if (events.length === 0) {
    elements.securityEventList.textContent = "Brak zdarzeń bezpieczeństwa";
    return;
  }
  for (const event of events) {
    const card = document.createElement("div");
    card.className = `entity-card security-event security-${event.severity}`;
    const titleRow = document.createElement("div");
    titleRow.className = "entity-title-row";
    const title = document.createElement("strong");
    title.textContent = securityEventLabels[event.event_type] ?? event.event_type;
    const outcome = document.createElement("span");
    outcome.className = `state-badge security-outcome-${event.outcome}`;
    outcome.textContent = event.outcome === "success" ? "sukces" : "niepowodzenie";
    titleRow.append(title, outcome);
    const meta = document.createElement("div");
    meta.className = "entity-meta security-event-meta";
    const subject = document.createElement("span");
    subject.textContent = `Konto: ${event.username || "—"}`;
    const source = document.createElement("span");
    source.textContent = `IP: ${event.remote_address || "—"}`;
    const actor = document.createElement("span");
    actor.textContent = `Wykonał: ${event.actor || "system"}`;
    const reason = document.createElement("span");
    reason.textContent = `Powód: ${securityReasonLabel(event.details?.reason)}`;
    const time = document.createElement("span");
    time.textContent = formatDateTime(event.occurred_at);
    meta.append(subject, source, actor, reason, time);
    card.append(titleRow, meta);
    elements.securityEventList.append(card);
  }
}

async function loadSecurityCenter() {
  if (!canAdminister() || securityCenterLoadInProgress) return;
  securityCenterLoadInProgress = true;
  elements.securityRefresh.disabled = true;
  elements.securityRefresh.setAttribute("aria-busy", "true");
  renderLoadingCards(elements.securitySessionList, 3);
  renderLoadingCards(elements.securityEventList, 5);
  try {
    const query = securityQueryString();
    query.set("limit", "500");
    const [summaryPayload, sessionPayload, eventPayload] = await Promise.all([
      fetchJson("/api/v1/security/summary"),
      fetchJson("/api/v1/security/sessions"),
      fetchJson(`/api/v1/security/events?${query.toString()}`),
    ]);
    renderSecuritySummary(summaryPayload.summary ?? {});
    renderSecuritySessions(sessionPayload.sessions ?? []);
    renderSecurityEvents(eventPayload.events ?? [], eventPayload.total ?? 0);
    lastSecuritySummaryAt = Date.now();
  } catch (error) {
    renderListFailure(elements.securitySessionList, "Nie udało się wczytać sesji");
    renderListFailure(elements.securityEventList, "Nie udało się wczytać dziennika");
    showToast(`Pobranie danych bezpieczeństwa nie powiodło się: ${error.message}`, true);
  } finally {
    finishListLoading(elements.securitySessionList);
    finishListLoading(elements.securityEventList);
    elements.securityRefresh.disabled = false;
    elements.securityRefresh.removeAttribute("aria-busy");
    securityCenterLoadInProgress = false;
  }
}

async function openSecurityCenter() {
  if (!canAdminister()) return;
  setOperatorMenuOpen(false);
  elements.operatorEditor.classList.add("hidden");
  elements.securityEditor.classList.remove("hidden");
  await loadSecurityCenter();
}

function downloadSecurityEvents(format) {
  const query = securityQueryString();
  query.set("format", format);
  const link = document.createElement("a");
  link.href = `/api/v1/security/export?${query.toString()}`;
  link.download = "";
  document.body.append(link);
  link.click();
  link.remove();
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
  if (!currentUser || !csrfToken) {
    throw new ApiError("Sesja użytkownika nie jest aktywna", 401);
  }
  try {
    return await requestJson(path, { method, body, csrf: true });
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      clearSession("Sesja wygasła. Zaloguj się ponownie.");
    }
    throw error;
  }
}

function canOperate() {
  return currentUser?.role === "operator" || currentUser?.role === "administrator";
}

function canAdminister() {
  return currentUser?.role === "administrator";
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
  const hasOpenAlert = currentOpenAlerts.some((alert) => alert.track_id === track.id);
  return L.divIcon({
    className: "",
    html: `<div class="drone-marker ${escapeHtml(state)}${hasOpenAlert ? " alerting" : ""}" style="--heading:${heading}deg"></div>`,
    iconSize: [32, 32],
    iconAnchor: [16, 16],
  });
}

function replayDroneIcon(observation) {
  const heading = isCoordinate(observation.heading_deg)
    ? observation.heading_deg
    : 0;
  return L.divIcon({
    className: "",
    html: `<div class="drone-marker replay" style="--heading:${heading}deg"></div>`,
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
      <span>Diagnostyka</span><strong>${escapeHtml(sensorHealthReasonLabel(sensor.health_reason))}</strong>
      <span>Token</span><strong>${sensor.credential_mode === "individual" ? "indywidualny" : "wspólny"}</strong>
      <span>Obserwacje</span><strong>${escapeHtml(formatInteger(sensor.observation_count))}</strong>
      <span>MGRS</span><strong>${escapeHtml(formatMgrs(sensor.latitude, sensor.longitude))}</strong>
      <span>Heartbeat</span><strong>${escapeHtml(formatTime(sensor.last_heartbeat_at))}</strong>
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
    <div class="popup-grid zone-popup-grid">
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
    const severityColor = severityColors[zone.severity] ?? severityColors.high;
    const color = zone.active ? severityColor : "#778292";
    const style = {
      color,
      fillColor: color,
      fillOpacity: hasOpenAlert ? 0.24 : zone.active ? 0.11 : 0.03,
      opacity: zone.active ? 0.9 : 0.45,
      weight: hasOpenAlert ? 3 : 2,
      dashArray: zone.active ? null : "7 6",
    };
    let layer = zoneLayers.get(zone.id);

    if (!layer) {
      layer = L.geoJSON(zone.geometry, { style }).addTo(map);
      layer.on("click", () => focusZoneInSidebar(zone.id));
      zoneLayers.set(zone.id, layer);
    } else {
      layer.setStyle(style);
    }
    layer.bindPopup(zonePopup(zone, hasOpenAlert), {
      minWidth: 260,
      maxWidth: 360,
      className: "zone-map-popup",
    });
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
        `<h3 class="popup-title">Operator drona (Remote ID)</h3><div class="popup-grid"><span>ID</span><strong>${escapeHtml(track.operator_id)}</strong><span>MGRS</span><strong>${escapeHtml(formatMgrs(track.pilot_latitude, track.pilot_longitude))}</strong></div>`,
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

function updateLiveTrailLayers(trails, tracks) {
  const visibleIds = new Set();
  const tracksById = new Map(tracks.map((track) => [track.id, track]));

  for (const trail of trails) {
    const track = tracksById.get(trail.track_id);
    const points = (trail.points ?? [])
      .filter((point) => hasPosition(point))
      .map((point) => [point.latitude, point.longitude]);
    if (!track || points.length < 2) {
      continue;
    }

    visibleIds.add(trail.track_id);
    const color = stateColors[track.state] ?? stateColors.active;
    let layer = liveTrailLayers.get(trail.track_id);
    if (!layer) {
      layer = L.polyline(points, {
        color,
        weight: 3,
        opacity: 0.58,
        interactive: false,
      }).addTo(map);
      liveTrailLayers.set(trail.track_id, layer);
    } else {
      layer.setLatLngs(points);
      layer.setStyle({ color });
    }
  }

  for (const [trackId, layer] of liveTrailLayers) {
    if (!visibleIds.has(trackId)) {
      layer.remove();
      liveTrailLayers.delete(trackId);
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
  badge.textContent = alertStateLabel(state);
  return badge;
}

function selectableOperatorTabs() {
  return [...elements.operatorTabButtons].filter(
    (button) => !button.classList.contains("hidden") && !button.disabled,
  );
}

function selectOperatorTab(tabName, { focus = false } = {}) {
  const availableTabs = selectableOperatorTabs();
  if (availableTabs.length === 0) return;
  const selectedButton = availableTabs.find(
    (button) => button.dataset.operatorTab === tabName,
  ) ?? availableTabs[0];
  const selectedName = selectedButton.dataset.operatorTab;

  for (const button of elements.operatorTabButtons) {
    const selected = button === selectedButton;
    button.classList.toggle("active", selected);
    button.setAttribute("aria-selected", String(selected));
    button.tabIndex = selected ? 0 : -1;
  }
  for (const panel of elements.operatorTabPanels) {
    panel.classList.toggle(
      "hidden",
      panel.dataset.operatorTabPanel !== selectedName,
    );
  }
  if (focus) selectedButton.focus();
}

function handleOperatorTabKeydown(event) {
  if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
  const availableTabs = selectableOperatorTabs();
  if (availableTabs.length === 0) return;
  event.preventDefault();
  const currentIndex = Math.max(0, availableTabs.indexOf(event.currentTarget));
  let nextIndex = currentIndex;
  if (event.key === "Home") nextIndex = 0;
  if (event.key === "End") nextIndex = availableTabs.length - 1;
  if (event.key === "ArrowLeft") {
    nextIndex = (currentIndex - 1 + availableTabs.length) % availableTabs.length;
  }
  if (event.key === "ArrowRight") {
    nextIndex = (currentIndex + 1) % availableTabs.length;
  }
  selectOperatorTab(availableTabs[nextIndex].dataset.operatorTab, { focus: true });
}

function setOperatorMenuOpen(open) {
  if (open) {
    elements.alarmTrainingTools.open = false;
    selectOperatorTab(currentUser?.must_change_password ? "account" : "admin");
  }
  operatorMenuOpen = open;
  elements.operatorMenu.classList.toggle("open", open);
  elements.operatorPanel.classList.toggle("hidden", !open);
  elements.operatorMenuToggle.setAttribute("aria-expanded", String(open));
}

function toggleOperatorMenu() {
  setOperatorMenuOpen(!operatorMenuOpen);
}

function readDisplaySettings() {
  try {
    return JSON.parse(localStorage.getItem(DISPLAY_SETTINGS_KEY) || "{}") ?? {};
  } catch {
    return {};
  }
}

function writeDisplaySettings(changes) {
  displaySettings = { ...displaySettings, ...changes };
  try {
    localStorage.setItem(DISPLAY_SETTINGS_KEY, JSON.stringify(displaySettings));
  } catch {
    // Ustawienia pozostają aktywne do końca bieżącej sesji karty.
  }
}

function setTheme(theme, { persist = true } = {}) {
  currentTheme = theme === "light" ? "light" : "dark";
  const light = currentTheme === "light";
  document.documentElement.dataset.theme = currentTheme;
  document.documentElement.style.colorScheme = currentTheme;
  document.querySelector('meta[name="theme-color"]')?.setAttribute(
    "content",
    light ? "#eef3f7" : "#0a0d12",
  );
  elements.themeToggle.setAttribute("aria-pressed", String(light));
  elements.themeToggle.setAttribute(
    "title",
    light ? "Włącz ciemny motyw" : "Włącz jasny motyw",
  );
  elements.themeToggleIcon.textContent = light ? "☾" : "☀";
  elements.themeToggleLabel.textContent = light ? "Ciemny" : "Jasny";
  if (persist) {
    writeDisplaySettings({ theme: currentTheme });
  }
}

function scheduleMapResize() {
  requestAnimationFrame(() => map.invalidateSize({ animate: false, pan: false }));
  window.clearTimeout(sidebarResizeTimer);
  sidebarResizeTimer = window.setTimeout(
    () => map.invalidateSize({ animate: false, pan: false }),
    240,
  );
}

function setSidebarHidden(hidden, { persist = true } = {}) {
  const wasHidden = elements.workspace.classList.contains("sidebar-hidden");
  elements.workspace.classList.toggle("sidebar-hidden", hidden);
  elements.sidebar.inert = hidden;
  elements.sidebar.setAttribute("aria-hidden", String(hidden));
  elements.sidebarToggle.setAttribute("aria-expanded", String(!hidden));
  elements.sidebarToggle.setAttribute(
    "title",
    hidden ? "Pokaż panel boczny" : "Ukryj panel boczny",
  );
  elements.sidebarToggleLabel.textContent = hidden ? "Pokaż panel" : "Ukryj panel";
  if (persist) {
    writeDisplaySettings({ sidebarHidden: hidden });
  }
  if (wasHidden !== hidden) {
    scheduleMapResize();
  }
}

function initializeDisplaySettings() {
  setTheme(currentTheme, { persist: false });
  setSidebarHidden(Boolean(displaySettings.sidebarHidden), { persist: false });
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
    const storedState = state[section.dataset.sectionKey];
    const initiallyCollapsed = typeof storedState === "boolean"
      ? storedState
      : section.classList.contains("collapsed");
    setSectionCollapsed(section, initiallyCollapsed, false);
    toggle.addEventListener("click", () => {
      const collapsed = !section.classList.contains("collapsed");
      setSectionCollapsed(section, collapsed);
      if (section === elements.closedAlertsSection && !collapsed && !closedAlertsLoaded) {
        void loadClosedAlerts();
      }
      if (
        section === elements.archivedTracksSection
        && !collapsed
        && !archivedTracksLoaded
      ) {
        void loadArchivedTracks();
      }
    });
  }
}

function applyOperationalSidebarOrder() {
  const sectionOrder = [
    "alerts",
    "tracks",
    "zones",
    "sensors",
    "archived-tracks",
    "closed-alerts",
    "audit",
  ];

  for (const sectionKey of sectionOrder) {
    const section = elements.sidebar.querySelector(
      `[data-section-key="${sectionKey}"]`,
    );
    if (section) {
      elements.sidebar.append(section);
    }
  }
}

function revealAlertsSectionForNewAlarm() {
  if (elements.alertsSection?.classList.contains("collapsed")) {
    setSectionCollapsed(elements.alertsSection, false, false);
  }
}

function revealSensorsSectionForIssue() {
  if (elements.sensorsSection?.classList.contains("collapsed")) {
    setSectionCollapsed(elements.sensorsSection, false, false);
  }
}

function processSensorHealth(sensors) {
  const issues = sensors.filter((sensor) =>
    sensor.status === "degraded" || sensor.status === "offline"
  );
  const issueIds = new Set(issues.map((sensor) => String(sensor.id)));

  if (!sensorHealthBaselineReady) {
    sensorHealthBaselineReady = true;
    knownSensorIssueIds = issueIds;
    if (issues.length > 0) {
      revealSensorsSectionForIssue();
    }
    return;
  }

  const newIssue = issues.find(
    (sensor) => !knownSensorIssueIds.has(String(sensor.id)),
  );
  knownSensorIssueIds = issueIds;
  if (newIssue) {
    revealSensorsSectionForIssue();
    showToast(
      `Usterka sensora „${newIssue.display_name || newIssue.sensor_id}”: ` +
        sensorHealthReasonLabel(newIssue.health_reason),
      true,
    );
  }
}

function renderSensorHealthSummary(sensors) {
  const issues = sensors.filter((sensor) =>
    sensor.status === "degraded" || sensor.status === "offline"
  );
  const maintenance = sensors.filter((sensor) => sensor.status === "maintenance");
  elements.sensorHealthBanner.classList.toggle(
    "hidden",
    issues.length === 0 && maintenance.length === 0,
  );
  elements.sensorHealthBanner.classList.toggle("has-issue", issues.length > 0);

  if (issues.length > 0) {
    const offline = issues.filter((sensor) => sensor.status === "offline").length;
    const degraded = issues.length - offline;
    elements.sensorHealthBanner.textContent = [
      offline ? `${offline} offline` : "",
      degraded ? `${degraded} ograniczone` : "",
    ].filter(Boolean).join(" · ");
  } else if (maintenance.length > 0) {
    elements.sensorHealthBanner.textContent =
      `${maintenance.length} w trybie konserwacji`;
  } else {
    elements.sensorHealthBanner.textContent = "";
  }
}

function updateOperatorUi(message = null, error = false) {
  const authenticated = Boolean(currentUser);
  elements.operatorMenu.classList.toggle("unlocked", authenticated);
  elements.operatorPanel.classList.toggle("unlocked", authenticated);
  elements.operatorStatus.classList.toggle("unlocked", authenticated);
  elements.operatorStatus.textContent = currentUser?.display_name ?? "—";
  elements.operatorModeLabel.textContent = currentUser
    ? `${currentUser.display_name} (${currentUser.username})`
    : "—";
  elements.operatorLockIndicator.textContent = currentUser?.role ?? "—";
  elements.drawZone.classList.toggle("hidden", !canOperate());
  elements.registerSensor.classList.toggle("hidden", !canAdminister());
  elements.manageOperators.classList.toggle("hidden", !canAdminister());
  elements.manageSecurity.classList.toggle("hidden", !canAdminister());
  elements.storagePanel.classList.toggle("hidden", !canAdminister());
  elements.operatorAdminTab.classList.toggle("hidden", !canOperate());
  elements.operatorAdminTab.disabled = Boolean(currentUser?.must_change_password);
  if (currentUser?.must_change_password) {
    selectOperatorTab("account");
  } else {
    const selectedTab = [...elements.operatorTabButtons].find(
      (button) => button.getAttribute("aria-selected") === "true",
    );
    if (!selectedTab || selectedTab.classList.contains("hidden")) {
      selectOperatorTab(canOperate() ? "admin" : "account");
    }
  }
  elements.loginScreen.classList.toggle("hidden", authenticated);
  elements.operatorMessage.classList.toggle("error", error);
  if (message !== null) {
    elements.operatorMessage.textContent = message;
  }
}

function acceptSession(payload) {
  currentUser = payload.user;
  csrfToken = payload.csrf_token;
  updateOperatorUi(
    currentUser.must_change_password
      ? "Administrator wymaga zmiany hasła przed użyciem panelu."
      : "Sesja aktywna.",
    currentUser.must_change_password,
  );
  if (currentUser.must_change_password) {
    setOperatorMenuOpen(true);
    elements.currentPassword.focus();
  } else if (canAdminister()) {
    void loadStorageUsage();
    void loadSecurityIndicator();
  }
}

async function login(event) {
  event.preventDefault();
  elements.loginSubmit.disabled = true;
  elements.loginMessage.textContent = "Logowanie…";
  elements.loginMessage.classList.remove("error");
  try {
    const session = await requestJson("/api/v1/auth/login", {
      method: "POST",
      body: {
        username: elements.loginUsername.value.trim().toLowerCase(),
        password: elements.loginPassword.value,
      },
    });
    elements.loginPassword.value = "";
    acceptSession(session);
    renderAlertLists();
    renderSensorList(currentSensors);
    renderZoneList(currentZones, currentAlerts);
    showToast(`Zalogowano jako ${currentUser.display_name}.`);
    if (!currentUser.must_change_password) {
      await loadInitialDashboard();
    }
  } catch (error) {
    currentUser = null;
    csrfToken = null;
    elements.loginPassword.value = "";
    elements.loginMessage.textContent = "Nieprawidłowy login lub hasło.";
    elements.loginMessage.classList.add("error");
  } finally {
    elements.loginSubmit.disabled = false;
  }
}

function clearSession(message = "Zaloguj się, aby otworzyć panel.") {
  cancelZoneDrawing();
  cancelSensorRegistration();
  closeSensorToken();
  elements.operatorEditor.classList.add("hidden");
  elements.securityEditor.classList.add("hidden");
  currentUser = null;
  csrfToken = null;
  initialLiveDataLoaded = false;
  zonesLoaded = false;
  currentSensors = [];
  currentTracks = [];
  currentLiveTracks = [];
  currentArchivedTracks = [];
  currentLiveTrails = [];
  currentZones = [];
  currentAlerts = [];
  currentOpenAlerts = [];
  currentClosedAlerts = [];
  closedAlertsLoaded = false;
  archivedTracksLoaded = false;
  pendingAlertActions.clear();
  alertDataRevision += 1;
  selectedZoneId = null;
  selectedAlertId = null;
  selectedAlertSnapshot = null;
  stopActiveAlertSounds();
  alertAudioBaselineReady = false;
  knownAlertIds = new Set();
  trackAudioBaselineReady = false;
  knownTrackIds = new Set();
  sensorHealthBaselineReady = false;
  knownSensorIssueIds = new Set();
  currentAuditEvents = [];
  currentAuditTotal = 0;
  elements.closedAlertFrom.value = "";
  elements.closedAlertTo.value = "";
  updateSensorMarkers([]);
  updateTrackMarkers([]);
  updateLiveTrailLayers([], []);
  updateZoneLayers([], []);
  removeIncidentLayers();
  lastStorageRefreshAt = 0;
  lastSecuritySummaryAt = 0;
  elements.operatorMenuToggle.classList.remove("security-alert");
  setOperatorMenuOpen(false);
  updateOperatorUi();
  elements.loginMessage.textContent = message;
  elements.loginMessage.classList.remove("error");
  renderAlertLists();
  renderClosedAlertList();
  renderSensorList(currentSensors);
  renderSensorHealthSummary(currentSensors);
  renderTrackList(currentTracks);
  elements.archivedTrackList.classList.add("empty-state");
  elements.archivedTrackList.textContent =
    "Rozwiń sekcję, aby wczytać zakończone trasy";
  renderZoneList(currentZones, currentAlerts);
  renderAuditList(currentAuditEvents);
  elements.onlineSensors.textContent = "0";
  elements.activeTracks.textContent = "0";
  elements.openAlerts.textContent = "0";
  elements.sensorCount.textContent = "0";
  elements.trackCount.textContent = "0";
  elements.archivedTrackCount.textContent = "0";
  elements.alertCount.textContent = "0";
  elements.closedAlertCount.textContent = "0";
  elements.zoneCount.textContent = "0";
  elements.auditCount.textContent = "0";
  elements.loginUsername.focus();
}

async function logout() {
  try {
    await requestJson("/api/v1/auth/logout", {
      method: "POST",
      body: {},
      csrf: true,
    });
  } catch (error) {
    if (!(error instanceof ApiError && error.status === 401)) {
      showToast(`Wylogowanie nie powiodło się: ${error.message}`, true);
      return;
    }
  }
  clearSession("Wylogowano bezpiecznie.");
}

async function changeOwnPassword(event) {
  event.preventDefault();
  elements.passwordSubmit.disabled = true;
  try {
    await requestJson("/api/v1/auth/password", {
      method: "POST",
      body: {
        current_password: elements.currentPassword.value,
        new_password: elements.newPassword.value,
      },
      csrf: true,
    });
    elements.passwordForm.reset();
    const session = await requestJson("/api/v1/auth/me");
    acceptSession(session);
    setOperatorMenuOpen(false);
    showToast("Hasło zostało zmienione. Pozostałe sesje unieważniono.");
    await loadInitialDashboard();
  } catch (error) {
    updateOperatorUi(`Zmiana hasła nie powiodła się: ${error.message}`, true);
  } finally {
    elements.passwordSubmit.disabled = false;
  }
}

function renderOperatorAccounts(accounts) {
  elements.operatorList.replaceChildren();
  elements.operatorList.classList.toggle("empty-state", accounts.length === 0);
  if (accounts.length === 0) {
    elements.operatorList.textContent = "Brak kont operatorów";
    return;
  }

  for (const account of accounts) {
    const card = document.createElement("div");
    card.className = "entity-card managed-card";
    const main = document.createElement("div");
    main.className = "managed-card-main";
    const title = document.createElement("strong");
    title.textContent = `${account.display_name} (${account.username})`;
    const meta = document.createElement("div");
    meta.className = "entity-meta";
    meta.textContent = `${account.role} · ${account.enabled ? "aktywne" : "zablokowane"}${account.must_change_password ? " · wymagana zmiana hasła" : ""}`;
    main.append(title, meta);
    card.append(main);

    const actions = document.createElement("div");
    actions.className = "managed-actions";
    const edit = document.createElement("button");
    edit.type = "button";
    edit.textContent = "Edytuj";
    edit.addEventListener("click", async () => {
      const displayName = window.prompt("Nazwa wyświetlana:", account.display_name);
      if (!displayName) return;
      const role = window.prompt(
        "Rola: viewer, operator lub administrator",
        account.role,
      );
      if (!["viewer", "operator", "administrator"].includes(role)) {
        showToast("Nieprawidłowa rola.", true);
        return;
      }
      try {
        await adminRequest(`/api/v1/operators/${account.id}`, "PUT", {
          display_name: displayName.trim(),
          role,
        });
        await loadOperatorAccounts();
      } catch (error) {
        showToast(`Edycja konta nie powiodła się: ${error.message}`, true);
      }
    });
    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.textContent = account.enabled ? "Zablokuj" : "Odblokuj";
    toggle.disabled = account.id === currentUser.id;
    toggle.addEventListener("click", async () => {
      toggle.disabled = true;
      try {
        await adminRequest(`/api/v1/operators/${account.id}`, "PATCH", {
          enabled: !account.enabled,
        });
        await loadOperatorAccounts();
      } catch (error) {
        showToast(`Zmiana konta nie powiodła się: ${error.message}`, true);
      } finally {
        toggle.disabled = false;
      }
    });

    const reset = document.createElement("button");
    reset.type = "button";
    reset.textContent = "Resetuj hasło";
    reset.disabled = account.id === currentUser.id;
    reset.addEventListener("click", async () => {
      const temporaryPassword = window.prompt(
        `Podaj nowe hasło tymczasowe dla ${account.username} (min. 12 znaków):`,
      );
      if (!temporaryPassword) return;
      try {
        await adminRequest(`/api/v1/operators/${account.id}/password/reset`, "POST", {
          temporary_password: temporaryPassword,
        });
        showToast("Hasło tymczasowe ustawione; aktywne sesje konta unieważniono.");
        await loadOperatorAccounts();
      } catch (error) {
        showToast(`Reset hasła nie powiódł się: ${error.message}`, true);
      }
    });

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "danger-button";
    remove.textContent = "Usuń";
    remove.disabled = account.id === currentUser.id;
    remove.addEventListener("click", async () => {
      if (!window.confirm(`Usunąć konto ${account.username}?`)) return;
      try {
        await adminRequest(`/api/v1/operators/${account.id}`, "DELETE", {});
        await loadOperatorAccounts();
      } catch (error) {
        showToast(`Usunięcie konta nie powiodło się: ${error.message}`, true);
      }
    });
    actions.append(edit, toggle, reset, remove);
    card.append(actions);
    elements.operatorList.append(card);
  }
}

async function loadOperatorAccounts() {
  renderLoadingCards(elements.operatorList, 4);
  try {
    const payload = await fetchJson("/api/v1/operators");
    renderOperatorAccounts(payload.operators ?? []);
  } finally {
    elements.operatorList.classList.remove("loading-list");
    elements.operatorList.removeAttribute("aria-busy");
  }
}

async function openOperatorEditor() {
  if (!canAdminister()) return;
  setOperatorMenuOpen(false);
  elements.securityEditor.classList.add("hidden");
  elements.operatorEditor.classList.remove("hidden");
  try {
    await loadOperatorAccounts();
  } catch (error) {
    showToast(`Nie udało się pobrać kont: ${error.message}`, true);
  }
}

async function createOperatorAccount(event) {
  event.preventDefault();
  elements.accountCreate.disabled = true;
  try {
    await adminRequest("/api/v1/operators", "POST", {
      username: elements.accountUsername.value.trim().toLowerCase(),
      display_name: elements.accountDisplayName.value.trim(),
      role: elements.accountRole.value,
      temporary_password: elements.accountPassword.value,
    });
    elements.operatorCreateForm.reset();
    showToast("Konto utworzone. Przy pierwszym logowaniu użytkownik zmieni hasło.");
    await loadOperatorAccounts();
  } catch (error) {
    showToast(`Utworzenie konta nie powiodło się: ${error.message}`, true);
  } finally {
    elements.accountCreate.disabled = false;
  }
}

async function reloadAlertsAfterAction() {
  alertDataRevision += 1;
  const payload = await fetchJson("/api/v1/alerts?include_closed=false");
  const receivedAlerts = payload.alerts ?? [];
  const receivedOpenAlerts = receivedAlerts.filter(
    (alert) => alert.state !== "closed",
  );
  processOperationalSounds(currentLiveTracks, receivedOpenAlerts);
  currentOpenAlerts = receivedOpenAlerts;
  renderAlertSnapshot();
  if (closedAlertsLoaded) {
    await loadClosedAlerts({ showLoader: false });
  }
}

async function runAlertAction(alert, action) {
  const alertId = String(alert.id);
  if (pendingAlertActions.has(alertId)) return;

  alertDataRevision += 1;
  pendingAlertActions.set(alertId, action);
  renderAlertSnapshot();
  let actionCompleted = false;
  try {
    await adminRequest(
      `/api/v1/alerts/${encodeURIComponent(alert.id)}/${action}`,
      "POST",
      {},
    );
    actionCompleted = true;
    await reloadAlertsAfterAction();
    showToast(
      action === "acknowledge"
        ? `Alarm dla ${alert.basic_id || alert.identity_key} został przyjęty.`
        : `Alarm został zamknięty. Jeśli naruszenie trwa, system otworzy nowy.`,
    );
    if (action === "close" && selectedAlertId === alert.id) {
      clearSelection();
    } else if (selectedAlertId === alert.id) {
      await refreshSelectedIncidentTimeline();
    }
  } catch (error) {
    if (actionCompleted) {
      showToast(
        `Alarm został zmieniony, ale nie udało się odświeżyć widoku: ${error.message}`,
        true,
      );
      void refresh();
    } else {
      showToast(`Operacja na alarmie nie powiodła się: ${error.message}`, true);
    }
  } finally {
    pendingAlertActions.delete(alertId);
    renderAlertSnapshot();
  }
}

function createAlertActionLoader(action) {
  const loader = document.createElement("div");
  loader.className = "alert-action-loader";
  loader.setAttribute("role", "status");
  loader.setAttribute("aria-live", "polite");

  const spinner = document.createElement("span");
  spinner.className = "alert-action-spinner";
  spinner.setAttribute("aria-hidden", "true");

  const copy = document.createElement("span");
  copy.className = "alert-action-loader-copy";
  const title = document.createElement("strong");
  title.textContent = action === "acknowledge"
    ? "Potwierdzanie alarmu…"
    : "Zamykanie alarmu…";
  const detail = document.createElement("small");
  detail.textContent = "Oczekiwanie na zapis i odpowiedź systemu";
  copy.append(title, detail);
  loader.append(spinner, copy);
  return loader;
}

function renderAlertList(
  alerts,
  target = elements.alertList,
  emptyMessage = "Brak otwartych alarmów",
  archive = false,
) {
  target.replaceChildren();
  target.classList.toggle("empty-state", alerts.length === 0);

  if (alerts.length === 0) {
    target.textContent = emptyMessage;
    return;
  }

  for (const alert of alerts) {
    const pendingAction = pendingAlertActions.get(String(alert.id));
    const card = document.createElement("div");
    card.className = `entity-card managed-card alert-card severity-${alert.severity} alert-${alert.state}${alert.id === selectedAlertId ? " selected" : ""}`;
    if (pendingAction) {
      card.classList.add("is-processing");
      card.setAttribute("aria-busy", "true");
    }

    const main = document.createElement("button");
    main.type = "button";
    main.className = "managed-card-main";
    main.disabled = Boolean(pendingAction);
    main.addEventListener("click", () => selectAlert(alert));

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
    time.textContent = archive
      ? `Zamknięto: ${formatDateTime(alert.closed_at)}`
      : formatTime(alert.last_detected_at);
    const presence = document.createElement("span");
    presence.className = `presence-label presence-${alert.presence_state}`;
    presence.textContent = presenceLabel(alert.presence_state);
    meta.append(zone, severity, presence, time);
    main.append(titleRow, meta);
    card.append(main);

    if (canOperate() && alert.state !== "closed") {
      const actions = document.createElement("div");
      actions.className = "managed-actions";
      if (alert.state === "active") {
        const acknowledge = document.createElement("button");
        acknowledge.type = "button";
        acknowledge.textContent = "Potwierdź";
        acknowledge.disabled = Boolean(pendingAction);
        acknowledge.addEventListener("click", () => {
          void runAlertAction(alert, "acknowledge");
        });
        actions.append(acknowledge);
      }
      const close = document.createElement("button");
      close.type = "button";
      close.className = "danger-button";
      close.textContent = "Zamknij";
      close.disabled = Boolean(pendingAction);
      close.addEventListener("click", () => {
        void runAlertAction(alert, "close");
      });
      actions.append(close);
      card.append(actions);
    }

    if (pendingAction) {
      card.append(createAlertActionLoader(pendingAction));
    }

    target.append(card);
  }
}

function renderClosedAlertList() {
  renderAlertList(
    currentClosedAlerts,
    elements.closedAlertList,
    closedAlertsLoaded
      ? "Brak zamkniętych alarmów w wybranym zakresie"
      : "Rozwiń sekcję, aby wczytać archiwum",
    true,
  );
  elements.closedAlertCount.textContent = closedAlertsLoaded
    ? String(currentClosedAlerts.length)
    : "0";
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
    const category = auditEventCategory(event);
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
      event.account_display_name ||
      event.account_username ||
      "system";
    const context = document.createElement("span");
    context.textContent =
      event.zone_name || event.sensor_key || event.account_role || "—";
    const time = document.createElement("span");
    time.textContent = formatDateTime(event.occurred_at);
    meta.append(subject, context, time);

    card.append(titleRow, meta);
    elements.auditList.append(card);
  }
}

function findTrack(trackId) {
  return currentTracks.find((track) => track.id === trackId)
    ?? currentArchivedTracks.find((track) => track.id === trackId);
}

function isArchivedTrack(trackId) {
  return currentArchivedTracks.some((track) => track.id === trackId);
}

function renderTrackList(tracks, { archived = false } = {}) {
  const target = archived ? elements.archivedTrackList : elements.trackList;
  target.replaceChildren();
  target.classList.toggle("empty-state", tracks.length === 0);

  if (tracks.length === 0) {
    target.textContent = archived
      ? "Brak zakończonych tras"
      : "Brak aktywnych śladów";
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
    time.textContent = archived
      ? formatCompactDateTime(track.last_seen_at)
      : formatTime(track.last_seen_at);
    meta.append(altitude, sensors, time);

    card.append(titleRow, meta);
    target.append(card);
  }
}

function renderTrackLists() {
  renderTrackList(currentTracks);
  if (archivedTracksLoaded) {
    renderTrackList(currentArchivedTracks, { archived: true });
  }
}

async function runSensorStateChange(sensor, enabled, button) {
  button.disabled = true;
  try {
    await adminRequest(
      `/api/v1/sensors/${encodeURIComponent(sensor.id)}`,
      "PATCH",
      { enabled },
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
      {},
    );
    showSensorToken(response.sensor, response.credential);
    await refresh();
  } catch (error) {
    showToast(`Nie udało się wydać tokenu: ${error.message}`, true);
  } finally {
    button.disabled = false;
  }
}

async function runSensorMaintenance(sensor, button) {
  const ending = sensor.status === "maintenance";
  let body;
  if (ending) {
    if (!window.confirm(`Zakończyć konserwację sensora „${sensor.display_name}”?`)) {
      return;
    }
    body = { enabled: false };
  } else {
    const reason = window.prompt(
      `Podaj powód konserwacji sensora „${sensor.display_name}”:`,
      "Prace serwisowe",
    );
    if (reason === null) return;
    if (!reason.trim()) {
      showToast("Tryb konserwacji wymaga podania powodu.", true);
      return;
    }
    const durationText = window.prompt(
      "Planowany czas w godzinach (puste pole oznacza brak terminu):",
      "1",
    );
    if (durationText === null) return;
    let until = null;
    if (durationText.trim()) {
      const hours = Number(durationText.replace(",", "."));
      if (!Number.isFinite(hours) || hours <= 0 || hours > 720) {
        showToast("Czas konserwacji musi być większy od 0 i nie przekraczać 720 godzin.", true);
        return;
      }
      until = new Date(Date.now() + hours * 3600000).toISOString();
    }
    body = { enabled: true, reason: reason.trim(), until };
  }

  button.disabled = true;
  try {
    await adminRequest(
      `/api/v1/sensors/${encodeURIComponent(sensor.id)}/maintenance`,
      "PUT",
      body,
    );
    showToast(
      ending
        ? `Zakończono konserwację sensora „${sensor.display_name}”.`
        : `Sensor „${sensor.display_name}” pracuje w trybie konserwacji.`,
    );
    await refresh();
  } catch (error) {
    showToast(`Zmiana trybu konserwacji nie powiodła się: ${error.message}`, true);
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
      {},
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
    card.className = `entity-card managed-card sensor-card sensor-${sensor.status}${sensor.id === selectedSensorId ? " selected" : ""}`;
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
    meta.className = "entity-meta sensor-meta";
    const identifier = document.createElement("span");
    identifier.className = "sensor-meta-identifier";
    identifier.textContent = `ID: ${sensor.sensor_id}`;
    const credential = document.createElement("span");
    credential.className = "sensor-meta-credential";
    credential.textContent =
      sensor.credential_mode === "individual"
        ? `token ${sensor.token_prefix}…`
        : "token wspólny";
    const time = document.createElement("span");
    time.className = "sensor-meta-heartbeat";
    time.textContent = `Heartbeat: ${formatTime(sensor.last_heartbeat_at)}`;
    const health = document.createElement("span");
    health.className = "sensor-health-reason";
    health.textContent = `Tor detekcji: ${sensorHealthReasonLabel(sensor.health_reason)}`;
    meta.append(identifier, credential, time, health);

    main.append(titleRow, meta);
    card.append(main);

    if (canAdminister()) {
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
      const maintenance = document.createElement("button");
      maintenance.type = "button";
      maintenance.className = sensor.status === "maintenance" ? "" : "secondary-button";
      maintenance.textContent =
        sensor.status === "maintenance" ? "Zakończ konserwację" : "Konserwacja";
      maintenance.disabled = sensor.status === "disabled";
      maintenance.addEventListener("click", () => {
        runSensorMaintenance(sensor, maintenance);
      });
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "danger-button";
      remove.textContent = "Usuń";
      remove.addEventListener("click", () => runSensorDeletion(sensor, remove));
      actions.append(edit, toggle, maintenance, rotate, remove);
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
      { active },
    );
    showToast(`Strefa „${zone.name}” została ${active ? "włączona" : "wyłączona"}.`);
    await loadZones();
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
      {},
    );
    showToast(`Strefa „${zone.name}” została usunięta.`);
    await loadZones();
    await refresh();
  } catch (error) {
    showToast(`Nie udało się usunąć strefy: ${error.message}`, true);
  } finally {
    button.disabled = false;
  }
}

function focusZoneInSidebar(zoneId, { scroll = true } = {}) {
  if (
    selectedZoneId !== zoneId
    || selectedTrackId
    || selectedSensorId
    || selectedAlertId
    || selectedAuditEvent
  ) {
    clearSelection();
  }
  selectedZoneId = zoneId;
  setSidebarHidden(false);
  if (elements.zonesSection.classList.contains("collapsed")) {
    setSectionCollapsed(elements.zonesSection, false);
  }

  let selectedCard = null;
  for (const card of elements.zoneList.children) {
    const selected = card.dataset.zoneId === String(zoneId);
    card.classList.toggle("selected", selected);
    if (selected) {
      selectedCard = card;
    }
  }

  if (scroll && selectedCard) {
    requestAnimationFrame(() => {
      selectedCard.scrollIntoView({ behavior: "smooth", block: "center" });
      selectedCard.querySelector(".managed-card-main")?.focus({
        preventScroll: true,
      });
    });
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
    card.className = `entity-card managed-card zone-card zone-severity-${zone.severity}${zone.active ? "" : " zone-inactive"}${zone.id === selectedZoneId ? " selected" : ""}`;
    card.dataset.zoneId = String(zone.id);
    const main = document.createElement("button");
    main.type = "button";
    main.className = "managed-card-main";
    main.addEventListener("click", () => {
      focusZoneInSidebar(zone.id, { scroll: false });
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
    severity.className = `zone-severity-label zone-severity-${zone.severity}`;
    severity.textContent = `Poziom: ${severityLabel(zone.severity)}`;
    const status = document.createElement("span");
    status.textContent = alertingZoneIds.has(zone.id) ? "ALARM" : "spokojnie";
    meta.append(severity, status);

    main.append(titleRow, meta);
    card.append(main);

    if (canOperate()) {
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
      actions.append(edit, toggle);
      if (canAdminister()) {
        actions.append(remove);
      }
      card.append(actions);
    }

    elements.zoneList.append(card);
  }
}

function renderAlertLists() {
  currentAlerts = [...currentOpenAlerts];
  renderAlertList(currentAlerts);
  if (!closedAlertsLoadInProgress) {
    renderClosedAlertList();
  }
  elements.alertCount.textContent = String(currentAlerts.length);
}

function renderAlertSnapshot() {
  renderAlertLists();
  elements.openAlerts.textContent = String(currentOpenAlerts.length);
  if (zonesLoaded) {
    updateZoneLayers(currentZones, currentOpenAlerts);
    renderZoneList(currentZones, currentOpenAlerts);
  }
}

function localDateBoundaryIso(value, addDays = 0) {
  const [year, month, day] = value.split("-").map(Number);
  const date = new Date(year, month - 1, day);
  date.setDate(date.getDate() + addDays);
  return date.toISOString();
}

function closedAlertArchivePath() {
  const from = elements.closedAlertFrom.value;
  const to = elements.closedAlertTo.value;
  if (from && to && from > to) {
    showToast("Data „od” nie może być późniejsza niż data „do”.", true);
    return null;
  }

  const parameters = new URLSearchParams({
    closed_only: "true",
    limit: "1000",
  });
  if (from) {
    parameters.set("closed_from", localDateBoundaryIso(from));
  }
  if (to) {
    parameters.set("closed_before", localDateBoundaryIso(to, 1));
  }
  return `/api/v1/alerts?${parameters.toString()}`;
}

async function loadClosedAlerts({ showLoader = true } = {}) {
  if (closedAlertsLoadInProgress || !currentUser) {
    return;
  }
  const path = closedAlertArchivePath();
  if (path === null) return;

  closedAlertsLoadInProgress = true;
  elements.closedAlertFrom.disabled = true;
  elements.closedAlertTo.disabled = true;
  elements.closedAlertApply.disabled = true;
  elements.closedAlertReset.disabled = true;
  if (showLoader) {
    renderLoadingCards(elements.closedAlertList);
  }
  try {
    const payload = await fetchJson(path);
    currentClosedAlerts = (payload.alerts ?? []).filter(
      (alert) => alert.state === "closed",
    );
    closedAlertsLoaded = true;
    renderClosedAlertList();
  } catch (error) {
    renderListFailure(
      elements.closedAlertList,
      "Nie udało się wczytać archiwum alarmów",
    );
    console.error("Nie udało się pobrać zamkniętych alarmów", error);
  } finally {
    finishListLoading(elements.closedAlertList);
    elements.closedAlertFrom.disabled = false;
    elements.closedAlertTo.disabled = false;
    elements.closedAlertApply.disabled = false;
    elements.closedAlertReset.disabled = false;
    closedAlertsLoadInProgress = false;
  }
}

async function loadArchivedTracks() {
  if (archiveLoadInProgress || !currentUser) {
    return;
  }
  archiveLoadInProgress = true;
  elements.archivedTrackCount.textContent = "…";
  renderLoadingCards(elements.archivedTrackList, 4);
  try {
    const payload = await fetchJson("/api/v1/tracks?include_ended=true");
    currentArchivedTracks = (payload.tracks ?? []).filter(
      (track) => track.state === "ended",
    );
    archivedTracksLoaded = true;
    renderTrackList(currentArchivedTracks, { archived: true });
    elements.archivedTrackCount.textContent = String(currentArchivedTracks.length);
  } catch (error) {
    renderListFailure(
      elements.archivedTrackList,
      "Nie udało się wczytać archiwum tras",
    );
    console.error("Nie udało się pobrać archiwum tras", error);
  } finally {
    finishListLoading(elements.archivedTrackList);
    archiveLoadInProgress = false;
  }
}

async function loadZones({ showLoader = true } = {}) {
  if (zonesLoadInProgress || !currentUser) {
    return;
  }
  zonesLoadInProgress = true;
  if (showLoader) {
    renderLoadingCards(elements.zoneList, 2);
  }
  try {
    const payload = await fetchJson("/api/v1/zones");
    currentZones = payload.zones ?? [];
    if (
      selectedZoneId
      && !currentZones.some((zone) => zone.id === selectedZoneId)
    ) {
      selectedZoneId = null;
    }
    zonesLoaded = true;
    updateZoneLayers(currentZones, currentOpenAlerts);
    renderZoneList(currentZones, currentOpenAlerts);
    elements.zoneCount.textContent = String(currentZones.length);
  } catch (error) {
    if (showLoader) {
      renderListFailure(elements.zoneList, "Nie udało się wczytać stref");
    }
    console.error("Nie udało się pobrać stref", error);
  } finally {
    finishListLoading(elements.zoneList);
    zonesLoadInProgress = false;
  }
}

async function loadAuditEvents() {
  if (auditLoadInProgress || !currentUser) {
    return;
  }
  auditLoadInProgress = true;
  elements.auditCategory.disabled = true;
  elements.auditRefresh.disabled = true;
  elements.auditRefresh.setAttribute("aria-busy", "true");
  renderLoadingCards(elements.auditList, 4);
  try {
    const category = encodeURIComponent(elements.auditCategory.value);
    const payload = await fetchJson(
      `/api/v1/audit/events?category=${category}&limit=100`,
    );
    currentAuditEvents = payload.events ?? [];
    currentAuditTotal = payload.total ?? currentAuditEvents.length;
    renderAuditList(currentAuditEvents);
    elements.auditCount.textContent = String(currentAuditTotal);
  } catch (error) {
    renderListFailure(elements.auditList, "Nie udało się wczytać dziennika");
    console.error("Nie udało się pobrać dziennika zdarzeń", error);
  } finally {
    finishListLoading(elements.auditList);
    elements.auditCategory.disabled = false;
    elements.auditRefresh.disabled = false;
    elements.auditRefresh.removeAttribute("aria-busy");
    auditLoadInProgress = false;
  }
}

async function loadInitialDashboard() {
  const initialLoads = [
    refresh({ initial: true }),
    loadZones(),
    loadAuditEvents(),
  ];
  if (!elements.closedAlertsSection.classList.contains("collapsed")) {
    initialLoads.push(loadClosedAlerts());
  }
  if (!elements.archivedTracksSection.classList.contains("collapsed")) {
    initialLoads.push(loadArchivedTracks());
  }
  await Promise.all(initialLoads);
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

function detailSection(title) {
  const section = document.createElement("h3");
  section.className = "detail-section-title";
  section.textContent = title;
  return section;
}

function renderSelection(track) {
  if (!track) {
    elements.selectionPanel.classList.add("hidden");
    elements.selectionDetails.replaceChildren();
    elements.trackControls.classList.add("hidden");
    elements.incidentControls.classList.add("hidden");
    elements.selectionTimeline.classList.add("hidden");
    elements.selectionTimelineList.replaceChildren();
    return;
  }

  elements.selectionPanel.classList.remove("hidden");
  elements.selectionEyebrow.textContent = track.state === "ended"
    ? "Trasa archiwalna"
    : "Wybrany ślad";
  elements.selectionTitle.textContent = track.basic_id || track.identity_key || track.track_key;
  elements.trackControls.classList.remove("hidden");
  elements.incidentControls.classList.add("hidden");
  elements.selectionTimeline.classList.add("hidden");
  elements.selectionTimelineList.replaceChildren();
  elements.selectionDetails.replaceChildren(
    detailItem("Status", stateLabel(track.state)),
    detailItem("Operator drona (Remote ID)", track.operator_id),
    detailItem("Wysokość", formatNumber(track.altitude_m, 1, " m")),
    detailItem("Prędkość", formatNumber(track.speed_mps, 1, " m/s")),
    detailItem("Kierunek", formatNumber(track.heading_deg, 0, "°")),
    detailItem("Sensory", String(track.contributing_sensors ?? "—")),
    detailItem("Otwarte alarmy", String(openAlertCountForTrack(track.id))),
    detailItem("Obserwacje", String(track.observation_count ?? "—")),
    detailItem("MGRS", formatMgrs(track.latitude, track.longitude)),
    detailItem("Pierwsza obserwacja", formatDateTime(track.first_seen_at)),
    detailItem("Ostatnia obserwacja", formatDateTime(track.last_seen_at)),
  );
  updateTrackModeControls();
}

function renderSensorSelection(sensor) {
  elements.selectionPanel.classList.remove("hidden");
  elements.selectionEyebrow.textContent = "Wybrany sensor";
  elements.selectionTitle.textContent = sensor.display_name || sensor.sensor_id;
  elements.trackControls.classList.add("hidden");
  elements.incidentControls.classList.add("hidden");
  elements.selectionTimeline.classList.add("hidden");
  elements.selectionTimelineList.replaceChildren();
  elements.selectionDetails.replaceChildren(
    detailItem("Status", stateLabel(sensor.status)),
    detailItem("Stan toru detekcji", sensorHealthReasonLabel(sensor.health_reason)),
    detailItem("Zmiana stanu", formatDateTime(sensor.health_changed_at)),
    ...(sensor.health_issue_started_at
      ? [detailItem("Początek usterki", formatDateTime(sensor.health_issue_started_at))]
      : []),
    ...(sensor.status === "maintenance"
      ? [
          detailItem("Powód konserwacji", sensor.maintenance_reason),
          detailItem("Rozpoczął", sensor.maintenance_started_by),
          detailItem("Początek konserwacji", formatDateTime(sensor.maintenance_started_at)),
          detailItem("Planowane zakończenie", formatDateTime(sensor.maintenance_until)),
        ]
      : []),
    detailItem("Identyfikator", sensor.sensor_id),
    detailItem(
      "Uwierzytelnianie",
      sensor.credential_mode === "individual" ? "token indywidualny" : "token wspólny",
    ),
    detailItem("Prefiks tokenu", sensor.token_prefix ? `${sensor.token_prefix}…` : "—"),
    detailItem("Ostatni heartbeat", formatDateTime(sensor.last_heartbeat_at)),
    detailItem("Czas raportu agenta", formatDateTime(sensor.last_heartbeat_reported_at)),
    detailItem("Ostatnia obserwacja", formatDateTime(sensor.last_observation_received_at)),
    detailItem("Połączenie Sky-Spy", sourceConnectionLabel(sensor.source_connected)),
    detailItem("Ostatnia wiadomość Sky-Spy", formatDateTime(sensor.source_last_message_at)),
    detailItem("Wersja agenta", sensor.agent_version),
    detailItem("MGRS", formatMgrs(sensor.latitude, sensor.longitude)),
    detailItem("Obserwacje", formatInteger(sensor.observation_count)),
    detailItem("Heartbeat", formatInteger(sensor.heartbeat_count)),
    detailItem("Uptime", formatDuration(sensor.uptime_seconds)),
    detailItem("RSSI modemu", formatNumber(sensor.cellular_rssi, 0, " dBm")),
    detailItem("Wolna pamięć", formatBytes(sensor.free_heap_bytes)),
    detailItem("Kolejka", formatInteger(sensor.queue_depth)),
    detailItem("Kolejka błędów", formatInteger(sensor.dead_letter_depth)),
  );
}

function renderIncidentSelection(alert) {
  elements.selectionPanel.classList.remove("hidden");
  elements.selectionEyebrow.textContent = "Incydent strefowy";
  elements.selectionTitle.textContent = alert.basic_id || alert.identity_key || alert.track_key;
  elements.trackControls.classList.add("hidden");
  elements.incidentControls.classList.remove("hidden");
  elements.incidentShowEntry.disabled = !hasPosition(alert);
  elements.incidentShowLive.disabled = !hasPosition(alert, "live_");
  elements.incidentShowRoute.disabled = !alert.track_id;
  elements.selectionTimelineTitle.textContent = "Historia alarmu strefowego";
  elements.selectionDetails.replaceChildren(
    detailSection("Incydent"),
    detailItem("Obsługa incydentu", alertStateLabel(alert.state)),
    detailItem("Obecność drona", presenceLabel(alert.presence_state)),
    detailItem("Priorytet", severityLabel(alert.severity)),
    detailItem("Pierwsze wejście", formatDateTime(alert.first_detected_at)),
    detailItem("Ostatnia detekcja", formatDateTime(alert.last_detected_at)),
    detailItem("Wyjście / utrata", formatDateTime(alert.exited_at)),
    detailItem("Czas od wejścia", formatDuration(alert.presence_duration_seconds)),
    ...(alert.acknowledged_at
      ? [
          detailItem("Potwierdził", alert.acknowledged_by),
          detailItem("Czas potwierdzenia", formatDateTime(alert.acknowledged_at)),
        ]
      : []),
    ...(alert.closed_at
      ? [
          detailItem("Zamknął", alert.closed_by),
          detailItem("Czas zamknięcia", formatDateTime(alert.closed_at)),
        ]
      : []),
    detailSection("Zapis w chwili naruszenia"),
    detailItem("Strefa", alert.zone_name),
    detailItem("Opis strefy", alert.zone_description),
    detailItem("Basic ID", alert.basic_id),
    detailItem("Klucz tożsamości", alert.identity_key),
    detailItem("Klucz sesji śladu", alert.track_key),
    detailItem("Operator Remote ID", alert.operator_id),
    detailItem("MAC drona", alert.drone_mac),
    detailItem("Sensor wejścia", alert.sensor_key),
    detailItem("Pozycja wejścia", formatMgrs(alert.latitude, alert.longitude)),
    detailItem(
      "Pozycja pilota przy wejściu",
      formatMgrs(alert.pilot_latitude, alert.pilot_longitude),
    ),
    detailItem("Wysokość przy wejściu", formatNumber(alert.altitude_m, 1, " m")),
    detailItem("Prędkość przy wejściu", formatNumber(alert.speed_mps, 1, " m/s")),
    detailItem("Kierunek przy wejściu", formatNumber(alert.heading_deg, 0, "°")),
    detailSection("Obiekt teraz"),
    detailItem("Stan śladu", stateLabel(alert.track_state)),
    detailItem("Aktualny Basic ID", alert.live_basic_id),
    detailItem("Aktualny operator RID", alert.live_operator_id),
    detailItem("Ostatnia aktywność", formatDateTime(alert.live_last_seen_at)),
    detailItem("Aktualna pozycja", formatMgrs(alert.live_latitude, alert.live_longitude)),
    detailItem("Aktualna wysokość", formatNumber(alert.live_altitude_m, 1, " m")),
    detailItem("Aktualna prędkość", formatNumber(alert.live_speed_mps, 1, " m/s")),
    detailItem("Aktualny kierunek", formatNumber(alert.live_heading_deg, 0, "°")),
    detailItem("Sensory śladu", formatInteger(alert.contributing_sensors)),
  );
  elements.selectionTimeline.classList.remove("hidden");
}

function renderAuditTimeline(events) {
  elements.selectionTimelineList.replaceChildren();
  elements.selectionTimelineList.classList.remove("inline-loading");

  if (events.length === 0) {
    elements.selectionTimelineList.textContent = "Brak zdarzeń w tej historii.";
    return;
  }

  for (const event of [...events].reverse()) {
    const item = document.createElement("div");
    const category = auditEventCategory(event);
    item.className = `timeline-event ${category}`;
    const marker = document.createElement("span");
    marker.className = "timeline-marker";
    const content = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = auditEventLabel(event.event_type);
    const meta = document.createElement("span");
    const presenceChange = event.event_type === "alert_presence_changed"
      ? ` · ${presenceLabel(event.details?.from_presence)} → ${presenceLabel(event.details?.to_presence)}`
      : "";
    meta.textContent = `${formatDateTime(event.occurred_at)} · ${event.actor || "system"}${presenceChange}`;
    content.append(title, meta);
    item.append(marker, content);
    elements.selectionTimelineList.append(item);
  }
}

function renderAuditSelection(event) {
  elements.selectionPanel.classList.remove("hidden");
  elements.selectionEyebrow.textContent = "Zdarzenie audytowe";
  elements.selectionTitle.textContent = auditEventLabel(event.event_type);
  elements.selectionTimelineTitle.textContent = auditTimelineTitle(event);
  elements.trackControls.classList.add("hidden");
  elements.incidentControls.classList.add("hidden");
  elements.selectionDetails.replaceChildren(
    detailItem("Czas", formatDateTime(event.occurred_at)),
    detailItem("Wykonawca zdarzenia", event.actor),
    detailItem("Dron", event.basic_id || event.identity_key),
    detailItem("Operator drona (Remote ID)", event.operator_id),
    detailItem("Strefa", event.zone_name),
    detailItem("Sensor", event.sensor_name || event.sensor_key),
    detailItem("Konto RDDS", event.account_display_name || event.account_username),
    detailItem("Rola konta", event.account_role),
    detailItem("Poziom", severityLabel(event.alert_severity || event.details?.severity)),
    detailItem("Stan alarmu", alertStateLabel(event.alert_state)),
    detailItem("Obecność drona", presenceLabel(event.alert_presence_state)),
  );
  elements.selectionTimeline.classList.remove("hidden");
  elements.selectionTimelineList.classList.add("inline-loading");
  elements.selectionTimelineList.textContent = "Ładowanie historii…";
}

async function refreshSelectedIncidentTimeline() {
  if (!selectedAlertId) return;
  const requestedAlertId = String(selectedAlertId);
  elements.selectionTimelineTitle.textContent = "Historia alarmu strefowego";
  elements.selectionTimeline.classList.remove("hidden");
  elements.selectionTimelineList.classList.add("inline-loading");
  elements.selectionTimelineList.textContent = "Ładowanie historii alarmu…";
  const payload = await fetchJson(
    `/api/v1/audit/events?alert_id=${encodeURIComponent(requestedAlertId)}&limit=200`,
  );
  if (String(selectedAlertId) === requestedAlertId) {
    renderAuditTimeline(payload.events ?? []);
  }
}

function removeIncidentTrail() {
  incidentTrail?.remove();
  incidentTrail = null;
}

function removeIncidentEntryMarker() {
  incidentEntryMarker?.remove();
  incidentEntryMarker = null;
}

function removeIncidentLayers() {
  removeIncidentTrail();
  removeIncidentEntryMarker();
}

function showIncidentEntry() {
  const alert = selectedAlertSnapshot;
  if (alert && hasPosition(alert)) {
    removeIncidentEntryMarker();
    incidentEntryMarker = L.circleMarker(
      [alert.latitude, alert.longitude],
      {
        radius: 8,
        color: severityColors[alert.severity] ?? severityColors.high,
        fillColor: "#101723",
        fillOpacity: 0.92,
        weight: 3,
      },
    )
      .addTo(map)
      .bindPopup(
        `<strong>Punkt wejścia</strong><br>${escapeHtml(
          alert.basic_id || alert.identity_key || alert.track_key,
        )}<br>${escapeHtml(formatDateTime(alert.first_detected_at))}`,
      );
    if (hasPosition(alert, "pilot_")) {
      map.fitBounds(
        [
          [alert.latitude, alert.longitude],
          [alert.pilot_latitude, alert.pilot_longitude],
        ],
        { padding: [55, 55], maxZoom: 16 },
      );
    } else {
      map.setView([alert.latitude, alert.longitude], Math.max(map.getZoom(), 16));
    }
    incidentEntryMarker.openPopup();
  }
}

function showIncidentLivePosition() {
  const alert = selectedAlertSnapshot;
  if (alert && hasPosition(alert, "live_")) {
    map.setView(
      [alert.live_latitude, alert.live_longitude],
      Math.max(map.getZoom(), 15),
    );
    trackLayers.get(alert.track_id)?.marker.openPopup();
  }
}

async function showIncidentRoute() {
  const alert = selectedAlertSnapshot;
  if (!alert?.track_id) return;
  elements.incidentShowRoute.disabled = true;
  elements.incidentShowRoute.setAttribute("aria-busy", "true");
  try {
    const payload = await fetchJson(
      `/api/v1/tracks/${encodeURIComponent(alert.track_id)}/history?limit=10000`,
    );
    if (selectedAlertId !== alert.id) return;
    const start = new Date(alert.first_detected_at).getTime();
    const end = new Date(
      alert.exited_at || alert.last_detected_at || alert.first_detected_at,
    ).getTime();
    const points = (payload.observations ?? []).filter((observation) => {
      const time = new Date(observation.message_time).getTime();
      return hasPosition(observation) && time >= start && time <= end;
    });
    if (points.length < 2) {
      showToast("Za mało zapisanych punktów do pokazania trasy incydentu.", true);
      return;
    }
    removeIncidentTrail();
    incidentTrail = L.polyline(
      points.map((point) => [point.latitude, point.longitude]),
      { color: "#ff4d5e", weight: 4, opacity: 0.88 },
    ).addTo(map);
    map.fitBounds(incidentTrail.getBounds(), { padding: [55, 55], maxZoom: 16 });
  } catch (error) {
    showToast(`Nie udało się pobrać trasy incydentu: ${error.message}`, true);
  } finally {
    elements.incidentShowRoute.disabled = false;
    elements.incidentShowRoute.removeAttribute("aria-busy");
  }
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
  } else if (selectedAuditEvent.track_id) {
    parameter = `track_id=${encodeURIComponent(selectedAuditEvent.track_id)}`;
  } else if (selectedAuditEvent.sensor_id) {
    parameter = `sensor_id=${encodeURIComponent(selectedAuditEvent.sensor_id)}`;
  } else if (selectedAuditEvent.operator_account_id) {
    parameter = `operator_account_id=${encodeURIComponent(selectedAuditEvent.operator_account_id)}`;
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

function clearReplayTimer() {
  if (replayAnimationFrame !== null) {
    cancelAnimationFrame(replayAnimationFrame);
    replayAnimationFrame = null;
  }
}

function removeReplayLayers() {
  replayMarker?.remove();
  replayPilotMarker?.remove();
  replayOperatorLine?.remove();
  replayTrail?.remove();
  replayMarker = null;
  replayPilotMarker = null;
  replayOperatorLine = null;
  replayTrail = null;
}

function removeArchivePreviewLayers() {
  archivePreviewMarker?.remove();
  archivePreviewPilotMarker?.remove();
  archivePreviewOperatorLine?.remove();
  archivePreviewMarker = null;
  archivePreviewPilotMarker = null;
  archivePreviewOperatorLine = null;
}

function showArchivePreview(track) {
  removeArchivePreviewLayers();
  if (!track || !isArchivedTrack(track.id) || !hasPosition(track)) {
    return;
  }

  const droneLatLng = [track.latitude, track.longitude];
  archivePreviewMarker = L.marker(droneLatLng, {
    icon: droneIcon({ ...track, state: "ended" }),
    zIndexOffset: 550,
  }).addTo(map);
  archivePreviewMarker.bindPopup(trackPopup(track));

  if (hasPosition(track, "pilot_")) {
    const pilotLatLng = [track.pilot_latitude, track.pilot_longitude];
    archivePreviewPilotMarker = L.marker(pilotLatLng, {
      icon: pilotIcon(),
      zIndexOffset: 425,
    }).addTo(map);
    archivePreviewPilotMarker.bindPopup(
      `<h3 class="popup-title">Ostatnia pozycja operatora</h3>` +
      `<div class="popup-grid"><span>ID</span><strong>${escapeHtml(track.operator_id)}</strong>` +
      `<span>MGRS</span><strong>${escapeHtml(formatMgrs(track.pilot_latitude, track.pilot_longitude))}</strong></div>`,
    );
    archivePreviewOperatorLine = L.polyline(
      [droneLatLng, pilotLatLng],
      {
        color: "#778292",
        weight: 2,
        opacity: 0.58,
        dashArray: "5 7",
      },
    ).addTo(map);
  }
}

function observationTimeMilliseconds(observation, fallbackIndex = 0) {
  const value = new Date(observation?.message_time).getTime();
  return Number.isFinite(value) ? value : fallbackIndex * 1000;
}

function replaySpeed() {
  return Math.max(1, Number(elements.trackReplaySpeed.value) || 1);
}

function updateTrackModeControls() {
  const trackSelected = Boolean(selectedTrackId);
  elements.trackControls.classList.toggle("hidden", !trackSelected);
  if (!trackSelected) {
    return;
  }

  const followingLive = liveFollowTrackId === selectedTrackId;
  const selectedTrack = findTrack(selectedTrackId);
  const canFollowLive = selectedTrack?.state !== "ended";
  const replayActive = replayTrackId === selectedTrackId && replayObservations.length > 0;
  elements.trackFollowLive.disabled = !canFollowLive;
  elements.trackFollowLive.classList.toggle("active", followingLive);
  elements.trackFollowLive.textContent = followingLive
    ? "Zatrzymaj śledzenie"
    : "Śledź na żywo";
  elements.trackReplay.textContent = replayActive
    ? "Od początku"
    : "Odtwórz trasę";
  elements.trackPlayer.classList.toggle("hidden", !replayActive);
  elements.trackReplayPause.textContent = replayPaused || replayCompleted
    ? replayCompleted
      ? "Od początku"
      : "Wznów"
    : "Pauza";
  elements.trackReplaySpeed.disabled = !replayActive;
}

function stopTrackReplay({ clearStatus = true } = {}) {
  clearReplayTimer();
  removeReplayLayers();
  replayTrackId = null;
  replayObservations = [];
  replayTotalObservations = 0;
  replayIndex = 0;
  replayRenderedIndex = -1;
  replayClockTimeMs = 0;
  replayLastFrameAt = null;
  replayPaused = false;
  replayCompleted = false;
  elements.trackReplaySeek.min = "0";
  elements.trackReplaySeek.max = "1";
  elements.trackReplaySeek.value = "0";
  elements.trackReplayStartTime.textContent = "—";
  elements.trackReplayCurrentTime.textContent = "—";
  elements.trackReplayEndTime.textContent = "—";
  if (clearStatus) {
    elements.trackReplayStatus.textContent = "Wybierz tryb pracy";
  }
  updateTrackModeControls();
  if (
    clearStatus &&
    selectedTrackSnapshot?.id === selectedTrackId
  ) {
    renderSelection(selectedTrackSnapshot);
    showArchivePreview(selectedTrackSnapshot);
  }
}

function renderReplayObservationDetails(observation) {
  const source = observation.replayed
    ? "zaległa kolejka sensora"
    : "dane bieżące";
  elements.selectionEyebrow.textContent = replayPaused
    ? "Odtwarzanie wstrzymane"
    : "Odtwarzanie trasy";
  elements.selectionDetails.replaceChildren(
    detailItem("Czas obserwacji", formatDateTime(observation.message_time)),
    detailItem("Operator drona (Remote ID)", observation.operator_id),
    detailItem("Wysokość", formatNumber(observation.altitude_m, 1, " m")),
    detailItem("Prędkość", formatNumber(observation.speed_mps, 1, " m/s")),
    detailItem("Kierunek", formatNumber(observation.heading_deg, 0, "°")),
    detailItem("Sensor", observation.sensor_id),
    detailItem("MGRS", formatMgrs(observation.latitude, observation.longitude)),
    detailItem("Odebrano przez RDDS", formatDateTime(observation.received_at)),
    detailItem("Źródło", source),
  );
}

function updateReplayMap(index, rebuildTrail = false) {
  const observation = replayObservations[index];
  const droneLatLng = [observation.latitude, observation.longitude];
  replayMarker.setLatLng(droneLatLng);
  replayMarker.setIcon(replayDroneIcon(observation));

  if (hasPosition(observation, "pilot_")) {
    const pilotLatLng = [
      observation.pilot_latitude,
      observation.pilot_longitude,
    ];
    if (!replayPilotMarker) {
      replayPilotMarker = L.marker(pilotLatLng, {
        icon: pilotIcon(),
        zIndexOffset: 450,
      }).addTo(map);
    } else {
      replayPilotMarker.setLatLng(pilotLatLng);
    }
    const connection = [droneLatLng, pilotLatLng];
    if (!replayOperatorLine) {
      replayOperatorLine = L.polyline(connection, {
        color: "#b48cff",
        weight: 2,
        opacity: 0.65,
        dashArray: "5 7",
      }).addTo(map);
    } else {
      replayOperatorLine.setLatLngs(connection);
    }
  } else {
    replayPilotMarker?.remove();
    replayOperatorLine?.remove();
    replayPilotMarker = null;
    replayOperatorLine = null;
  }

  if (rebuildTrail || index < replayRenderedIndex) {
    replayTrail.setLatLngs(
      replayObservations
        .slice(0, index + 1)
        .map((point) => [point.latitude, point.longitude]),
    );
  } else {
    for (let pointIndex = replayRenderedIndex + 1; pointIndex <= index; pointIndex += 1) {
      const point = replayObservations[pointIndex];
      replayTrail.addLatLng([point.latitude, point.longitude]);
    }
  }
  replayRenderedIndex = index;
}

function replayStatusText(observation) {
  const sourceLabel = observation.replayed ? " · dane z kolejki" : "";
  const sampleLabel = replayTotalObservations > replayObservations.length
    ? ` · próbka z ${formatInteger(replayTotalObservations)}`
    : "";
  const stateLabelText = replayCompleted
    ? " · zakończono"
    : replayPaused
      ? " · pauza"
      : "";
  return (
    `Punkt ${replayIndex + 1}/${replayObservations.length}` +
    `${sampleLabel}${sourceLabel}${stateLabelText}`
  );
}

function renderReplayIndex(index, rebuildTrail = false) {
  if (replayObservations.length === 0) {
    return;
  }
  replayIndex = Math.max(0, Math.min(index, replayObservations.length - 1));
  const observation = replayObservations[replayIndex];
  updateReplayMap(replayIndex, rebuildTrail);
  renderReplayObservationDetails(observation);
  elements.trackReplaySeek.value = String(replayIndex);
  elements.trackReplayCurrentTime.textContent = formatCompactDateTime(
    observation.message_time,
  );
  elements.trackReplayStatus.textContent = replayStatusText(observation);
}

function replayIndexAtTime(targetTimeMs) {
  let low = 0;
  let high = replayObservations.length - 1;
  let match = 0;
  while (low <= high) {
    const middle = Math.floor((low + high) / 2);
    if (observationTimeMilliseconds(replayObservations[middle], middle) <= targetTimeMs) {
      match = middle;
      low = middle + 1;
    } else {
      high = middle - 1;
    }
  }
  return match;
}

function replayIndexAtOrAfterTime(targetTimeMs) {
  let low = 0;
  let high = replayObservations.length - 1;
  let match = high;
  while (low <= high) {
    const middle = Math.floor((low + high) / 2);
    if (observationTimeMilliseconds(replayObservations[middle], middle) >= targetTimeMs) {
      match = middle;
      high = middle - 1;
    } else {
      low = middle + 1;
    }
  }
  return match;
}

function scheduleReplayFrame() {
  clearReplayTimer();
  if (!replayPaused && !replayCompleted) {
    replayAnimationFrame = requestAnimationFrame(advanceTrackReplay);
  }
}

function advanceTrackReplay(frameTime) {
  replayAnimationFrame = null;
  if (
    replayPaused ||
    replayCompleted ||
    replayTrackId !== selectedTrackId ||
    replayObservations.length === 0
  ) {
    return;
  }

  if (replayLastFrameAt === null) {
    replayLastFrameAt = frameTime;
  } else {
    const elapsed = Math.min(500, Math.max(0, frameTime - replayLastFrameAt));
    replayLastFrameAt = frameTime;
    replayClockTimeMs += elapsed * replaySpeed();
  }

  const endIndex = replayObservations.length - 1;
  const endTime = observationTimeMilliseconds(replayObservations[endIndex], endIndex);
  if (replayClockTimeMs >= endTime) {
    replayClockTimeMs = endTime;
    replayCompleted = true;
    renderReplayIndex(endIndex);
    updateTrackModeControls();
    return;
  }

  const nextIndex = replayIndexAtTime(replayClockTimeMs);
  if (nextIndex !== replayIndex) {
    renderReplayIndex(nextIndex);
  }
  scheduleReplayFrame();
}

function seekTrackReplay(index) {
  if (replayObservations.length === 0) {
    return;
  }
  clearReplayTimer();
  const boundedIndex = Math.max(
    0,
    Math.min(Number(index) || 0, replayObservations.length - 1),
  );
  replayClockTimeMs = observationTimeMilliseconds(
    replayObservations[boundedIndex],
    boundedIndex,
  );
  replayLastFrameAt = null;
  replayCompleted = boundedIndex === replayObservations.length - 1;
  renderReplayIndex(boundedIndex, true);
  updateTrackModeControls();
  scheduleReplayFrame();
}

function stepTrackReplay(seconds) {
  if (replayObservations.length === 0) {
    return;
  }
  const firstTime = observationTimeMilliseconds(replayObservations[0], 0);
  const lastIndex = replayObservations.length - 1;
  const lastTime = observationTimeMilliseconds(
    replayObservations[lastIndex],
    lastIndex,
  );
  const currentTime = observationTimeMilliseconds(
    replayObservations[replayIndex],
    replayIndex,
  );
  const target = Math.max(
    firstTime,
    Math.min(lastTime, currentTime + seconds * 1000),
  );
  const targetIndex = seconds > 0
    ? replayIndexAtOrAfterTime(target)
    : replayIndexAtTime(target);
  seekTrackReplay(targetIndex);
}

async function startTrackReplay() {
  if (!selectedTrackId) {
    return;
  }
  const requestedTrackId = selectedTrackId;
  liveFollowTrackId = null;
  stopTrackReplay({ clearStatus: false });
  removeArchivePreviewLayers();
  replayTrackId = requestedTrackId;
  elements.trackReplayStatus.textContent = "Pobieranie historii trasy…";
  elements.trackReplayStatus.classList.add("inline-loading");
  updateTrackModeControls();
  elements.trackReplay.disabled = true;
  elements.trackReplay.setAttribute("aria-busy", "true");

  try {
    const payload = await fetchJson(
      `/api/v1/tracks/${encodeURIComponent(requestedTrackId)}/history?limit=10000`,
    );
    if (selectedTrackId !== requestedTrackId) {
      return;
    }
    const observations = (payload.observations ?? []).filter((observation) =>
      hasPosition(observation),
    );
    if (observations.length < 2) {
      stopTrackReplay({ clearStatus: false });
      elements.trackReplayStatus.textContent = "Za mało punktów do odtworzenia trasy";
      return;
    }

    replayTrackId = requestedTrackId;
    replayObservations = observations;
    replayTotalObservations = payload.total_observations ?? observations.length;
    replayIndex = 0;
    replayRenderedIndex = -1;
    replayPaused = false;
    replayCompleted = false;
    replayLastFrameAt = null;
    replayClockTimeMs = observationTimeMilliseconds(observations[0], 0);
    const firstPoint = [observations[0].latitude, observations[0].longitude];
    replayMarker = L.marker(firstPoint, {
      icon: replayDroneIcon(observations[0]),
      zIndexOffset: 600,
    }).addTo(map);
    replayTrail = L.polyline([], {
      color: "#b48cff",
      weight: 3,
      opacity: 0.82,
    }).addTo(map);

    elements.trackReplaySeek.min = "0";
    elements.trackReplaySeek.max = String(observations.length - 1);
    elements.trackReplaySeek.value = "0";
    elements.trackReplayStartTime.textContent = formatCompactDateTime(
      observations[0].message_time,
    );
    elements.trackReplayEndTime.textContent = formatCompactDateTime(
      observations[observations.length - 1].message_time,
    );

    const bounds = L.latLngBounds(
      observations.map((observation) => [
        observation.latitude,
        observation.longitude,
      ]),
    );
    if (bounds.isValid()) {
      map.fitBounds(bounds, { padding: [50, 50], maxZoom: 15 });
    }
    renderReplayIndex(0, true);
    updateTrackModeControls();
    scheduleReplayFrame();
  } catch (error) {
    if (selectedTrackId === requestedTrackId) {
      stopTrackReplay({ clearStatus: false });
      elements.trackReplayStatus.textContent = "Nie udało się pobrać trasy";
    }
    console.error("Nie udało się pobrać historii śladu", error);
  } finally {
    elements.trackReplayStatus.classList.remove("inline-loading");
    elements.trackReplay.removeAttribute("aria-busy");
    elements.trackReplay.disabled = false;
    updateTrackModeControls();
  }
}

function toggleTrackReplayPause() {
  if (replayTrackId !== selectedTrackId || replayObservations.length === 0) {
    return;
  }

  if (replayCompleted) {
    replayPaused = false;
    seekTrackReplay(0);
  } else if (replayPaused) {
    replayPaused = false;
    replayLastFrameAt = null;
    renderReplayIndex(replayIndex);
    scheduleReplayFrame();
  } else {
    replayPaused = true;
    clearReplayTimer();
    renderReplayIndex(replayIndex);
  }
  updateTrackModeControls();
}

function toggleLiveTracking() {
  if (!selectedTrackId) {
    return;
  }
  const selectedTrack = findTrack(selectedTrackId);
  if (selectedTrack?.state === "ended") {
    elements.trackReplayStatus.textContent =
      "Trasa archiwalna — użyj odtwarzania";
    updateTrackModeControls();
    return;
  }
  if (liveFollowTrackId === selectedTrackId) {
    liveFollowTrackId = null;
    elements.trackReplayStatus.textContent = "Śledzenie na żywo zatrzymane";
  } else {
    stopTrackReplay({ clearStatus: false });
    liveFollowTrackId = selectedTrackId;
    elements.trackReplayStatus.textContent = "Śledzenie pozycji na żywo";
    const track = findTrack(selectedTrackId);
    if (track && hasPosition(track)) {
      map.panTo([track.latitude, track.longitude]);
    }
  }
  updateTrackModeControls();
}

function selectTrack(trackId) {
  if (
    !elements.zoneEditor.classList.contains("hidden") ||
    !elements.sensorEditor.classList.contains("hidden") ||
    !elements.sensorTokenPanel.classList.contains("hidden")
  ) {
    return;
  }
  if (selectedTrackId !== trackId) {
    liveFollowTrackId = null;
    stopTrackReplay();
    removeArchivePreviewLayers();
    removeIncidentLayers();
  }
  selectedAuditEvent = null;
  selectedAlertId = null;
  selectedAlertSnapshot = null;
  selectedSensorId = null;
  selectedTrackId = trackId;
  const track = findTrack(trackId);
  const archived = isArchivedTrack(trackId);
  selectedTrackSnapshot = track ? { ...track } : null;
  renderAuditList(currentAuditEvents);
  renderSensorList(currentSensors);
  renderTrackLists();
  renderAlertLists();
  renderSelection(track);

  if (track && hasPosition(track)) {
    showArchivePreview(track);
    if (archived && hasPosition(track, "pilot_")) {
      map.fitBounds(
        [
          [track.latitude, track.longitude],
          [track.pilot_latitude, track.pilot_longitude],
        ],
        { padding: [55, 55], maxZoom: 15 },
      );
    } else {
      map.panTo([track.latitude, track.longitude]);
    }
    const marker = archived
      ? archivePreviewMarker
      : trackLayers.get(track.id)?.marker;
    marker?.openPopup();
  }

}

function selectAlert(alert) {
  if (
    !elements.zoneEditor.classList.contains("hidden") ||
    !elements.sensorEditor.classList.contains("hidden") ||
    !elements.sensorTokenPanel.classList.contains("hidden")
  ) {
    return;
  }
  selectedTrackId = null;
  selectedTrackSnapshot = null;
  selectedSensorId = null;
  selectedAuditEvent = null;
  selectedAlertId = alert.id;
  selectedAlertSnapshot = { ...alert };
  liveFollowTrackId = null;
  stopTrackReplay();
  removeArchivePreviewLayers();
  removeIncidentLayers();
  renderTrackLists();
  renderSensorList(currentSensors);
  renderAlertLists();
  renderAuditList(currentAuditEvents);
  renderIncidentSelection(selectedAlertSnapshot);
  if (alert.presence_state === "inside" && hasPosition(alert, "live_")) {
    showIncidentLivePosition();
  } else {
    showIncidentEntry();
  }
  refreshSelectedIncidentTimeline().catch((error) => {
    elements.selectionTimelineList.classList.remove("inline-loading");
    elements.selectionTimelineList.textContent = "Nie udało się pobrać historii incydentu.";
    console.error("Nie udało się pobrać historii incydentu", error);
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
  selectedTrackSnapshot = null;
  selectedAuditEvent = null;
  selectedAlertId = null;
  selectedAlertSnapshot = null;
  selectedSensorId = sensorId;
  liveFollowTrackId = null;
  stopTrackReplay();
  removeArchivePreviewLayers();
  removeIncidentLayers();
  const sensor = currentSensors.find((candidate) => candidate.id === sensorId);
  renderTrackLists();
  renderAuditList(currentAuditEvents);
  renderSensorList(currentSensors);
  renderAlertLists();
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
  selectedTrackSnapshot = null;
  selectedSensorId = null;
  selectedAlertId = null;
  selectedAlertSnapshot = null;
  liveFollowTrackId = null;
  stopTrackReplay();
  removeArchivePreviewLayers();
  removeIncidentLayers();
  selectedAuditEvent = event;
  renderTrackLists();
  renderSensorList(currentSensors);
  renderAuditList(currentAuditEvents);
  renderAlertLists();
  renderAuditSelection(event);

  const track = findTrack(event.track_id);
  if (track && hasPosition(track)) {
    map.panTo([track.latitude, track.longitude]);
    trackLayers.get(track.id)?.marker.openPopup();
  }

  refreshSelectedAuditTimeline().catch((error) => {
    elements.selectionTimelineList.classList.remove("inline-loading");
    elements.selectionTimelineList.textContent = "Nie udało się pobrać historii.";
    console.error("Nie udało się pobrać historii audytu", error);
  });
}

function clearSelection() {
  selectedTrackId = null;
  selectedTrackSnapshot = null;
  selectedSensorId = null;
  selectedZoneId = null;
  selectedAuditEvent = null;
  selectedAlertId = null;
  selectedAlertSnapshot = null;
  liveFollowTrackId = null;
  stopTrackReplay();
  removeArchivePreviewLayers();
  removeIncidentLayers();
  renderSelection(null);
  renderTrackLists();
  renderSensorList(currentSensors);
  renderZoneList(currentZones, currentOpenAlerts);
  renderAuditList(currentAuditEvents);
  renderAlertLists();
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
  if (!canOperate()) {
    showToast("Ta operacja wymaga roli operator lub administrator.", true);
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
  if (!canOperate()) {
    showToast("Ta operacja wymaga roli operator lub administrator.", true);
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
  selectedZoneId = zone.id;
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
  if (!canAdminister()) {
    showToast("Ta operacja wymaga roli administrator.", true);
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
  if (!canAdminister()) {
    showToast("Ta operacja wymaga roli administrator.", true);
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
  if (!canAdminister()) {
    showToast("Ta operacja wymaga roli administrator.", true);
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
  if (!canOperate() || drawingPoints.length < 3) {
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
    await loadZones();
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

async function refresh({ initial = false } = {}) {
  if (refreshInProgress || !currentUser || currentUser.must_change_password) {
    return;
  }
  refreshInProgress = true;
  const alertRevisionAtStart = alertDataRevision;
  const firstLiveLoad = initial || !initialLiveDataLoaded;
  if (firstLiveLoad) {
    renderLoadingCards(elements.sensorList, 3);
    renderLoadingCards(elements.trackList, 3);
    renderLoadingCards(elements.alertList, 3);
  }

  try {
    const [sensorPayload, trackPayload, trailPayload, alertPayload] = await Promise.all([
      fetchJson("/api/v1/sensors"),
      fetchJson("/api/v1/tracks?include_ended=false"),
      fetchJson(
        `/api/v1/tracks/trails?seconds=${LIVE_TRAIL_SECONDS}&limit=${LIVE_TRAIL_POINT_LIMIT}`,
      ),
      fetchJson("/api/v1/alerts?include_closed=false"),
    ]);

    currentSensors = sensorPayload.sensors ?? [];
    processSensorHealth(currentSensors);
    currentLiveTracks = (trackPayload.tracks ?? []).filter(
      (track) => track.state !== "ended",
    );
    currentLiveTrails = trailPayload.trails ?? [];
    const incomingOpenAlerts = (alertPayload.alerts ?? []).filter(
      (alert) => alert.state !== "closed",
    );
    const alertPayloadIsCurrent = alertRevisionAtStart === alertDataRevision;
    if (alertPayloadIsCurrent) {
      processOperationalSounds(currentLiveTracks, incomingOpenAlerts);
      currentOpenAlerts = incomingOpenAlerts;
      currentAlerts = [...currentOpenAlerts];
    }
    currentTracks = [...currentLiveTracks];

    updateSensorMarkers(currentSensors);
    updateTrackMarkers(currentTracks);
    updateLiveTrailLayers(currentLiveTrails, currentTracks);
    if (liveFollowTrackId) {
      const followedTrack = currentLiveTracks.find(
        (track) => track.id === liveFollowTrackId,
      );
      if (followedTrack && hasPosition(followedTrack)) {
        map.panTo([followedTrack.latitude, followedTrack.longitude]);
      } else {
        liveFollowTrackId = null;
        elements.trackReplayStatus.textContent = "Ślad nie jest już dostępny na żywo";
        updateTrackModeControls();
      }
    }
    renderSensorList(currentSensors);
    renderSensorHealthSummary(currentSensors);
    renderTrackList(currentTracks);
    elements.trackCount.textContent = String(currentTracks.length);
    if (alertPayloadIsCurrent) {
      renderAlertLists();
    }
    if (zonesLoaded) {
      updateZoneLayers(currentZones, currentOpenAlerts);
      renderZoneList(currentZones, currentOpenAlerts);
    }

    const onlineSensors = currentSensors.filter((sensor) => sensor.status === "online").length;
    const monitoredSensors = currentSensors.filter(
      (sensor) => sensor.status !== "disabled" && sensor.status !== "maintenance",
    ).length;
    const activeTracks = currentLiveTracks.filter((track) => track.state === "active").length;
    elements.onlineSensors.textContent = `${onlineSensors}/${monitoredSensors}`;
    elements.activeTracks.textContent = String(activeTracks);
    elements.openAlerts.textContent = String(currentOpenAlerts.length);
    elements.sensorCount.textContent = String(currentSensors.length);
    initialLiveDataLoaded = true;

    if (selectedTrackId) {
      const selected = findTrack(selectedTrackId);
      const archived = isArchivedTrack(selectedTrackId);
      const replayActive = (
        replayTrackId === selectedTrackId && replayObservations.length > 0
      );
      if (replayActive) {
        renderReplayIndex(replayIndex);
      } else if (selected && archived) {
        selectedTrackSnapshot ??= { ...selected };
        renderSelection(selectedTrackSnapshot);
      } else if (selected) {
        selectedTrackSnapshot = { ...selected };
        renderSelection(selected);
      } else if (selectedTrackSnapshot?.state === "ended") {
        renderSelection(selectedTrackSnapshot);
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
    } else if (selectedAlertId) {
      const selected = currentOpenAlerts.find((alert) => alert.id === selectedAlertId)
        ?? currentClosedAlerts.find((alert) => alert.id === selectedAlertId);
      if (selected) {
        selectedAlertSnapshot = { ...selected };
        renderIncidentSelection(selectedAlertSnapshot);
      } else if (selectedAlertSnapshot) {
        renderIncidentSelection(selectedAlertSnapshot);
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
    if (canAdminister()) {
      void loadStorageUsage();
      void loadSecurityIndicator();
    }
  } catch (error) {
    console.error("Odświeżenie mapy nie powiodło się", error);
    if (error instanceof ApiError && error.status === 401) {
      clearSession("Sesja wygasła. Zaloguj się ponownie.");
    } else {
      setConnection(false, "Brak połączenia z API");
      if (firstLiveLoad) {
        renderListFailure(elements.sensorList, "Nie udało się wczytać sensorów");
        renderListFailure(elements.trackList, "Nie udało się wczytać obiektów");
        renderListFailure(elements.alertList, "Nie udało się wczytać alarmów");
      }
    }
  } finally {
    finishListLoading(elements.sensorList);
    finishListLoading(elements.trackList);
    finishListLoading(elements.alertList);
    refreshInProgress = false;
  }
}

elements.closedAlertApply.addEventListener("click", () => {
  clearSelection();
  void loadClosedAlerts();
});
elements.closedAlertReset.addEventListener("click", () => {
  elements.closedAlertFrom.value = "";
  elements.closedAlertTo.value = "";
  clearSelection();
  void loadClosedAlerts();
});
elements.auditCategory.addEventListener("change", () => {
  clearSelection();
  void loadAuditEvents();
});
elements.auditRefresh.addEventListener("click", () => void loadAuditEvents());
elements.auditExportCsv.addEventListener("click", () => downloadAudit("csv"));
elements.auditExportJson.addEventListener("click", () => downloadAudit("json"));
elements.fitMap.addEventListener("click", fitAllEntities);
elements.closeSelection.addEventListener("click", clearSelection);
elements.incidentShowEntry.addEventListener("click", showIncidentEntry);
elements.incidentShowLive.addEventListener("click", showIncidentLivePosition);
elements.incidentShowRoute.addEventListener("click", () => void showIncidentRoute());
elements.trackFollowLive.addEventListener("click", toggleLiveTracking);
elements.trackReplay.addEventListener("click", startTrackReplay);
elements.trackReplaySeek.addEventListener("input", () => {
  seekTrackReplay(elements.trackReplaySeek.value);
});
elements.trackReplayBack.addEventListener("click", () => stepTrackReplay(-10));
elements.trackReplayPause.addEventListener("click", toggleTrackReplayPause);
elements.trackReplayForward.addEventListener("click", () => stepTrackReplay(10));
elements.trackReplayStop.addEventListener("click", () => stopTrackReplay());
elements.trackReplaySpeed.addEventListener("change", () => {
  replayLastFrameAt = null;
});
elements.operatorMenuToggle.addEventListener("click", toggleOperatorMenu);
elements.alarmAudioToggle.addEventListener("click", () => void toggleAlertAudio());
elements.alarmAudioTest.addEventListener("click", () => {
  void playAlertSound(elements.alarmAudioTestProfile.value);
});
elements.alarmAudioVolume.addEventListener("input", () => {
  alertAudioSettings.volume = Math.min(
    1,
    Math.max(0, Number(elements.alarmAudioVolume.value)),
  );
  updateAlertAudioMasterVolume();
  elements.alarmAudioVolumeValue.textContent = `${Math.round(
    alertAudioSettings.volume * 100,
  )}%`;
  writeAlertAudioSettings();
});
elements.alarmAudioRepeat.addEventListener("change", () => {
  alertAudioSettings.repeatCritical = elements.alarmAudioRepeat.checked;
  writeAlertAudioSettings();
});
elements.loginForm.addEventListener("submit", login);
elements.passwordForm.addEventListener("submit", changeOwnPassword);
elements.operatorLock.addEventListener("click", logout);
for (const button of elements.operatorTabButtons) {
  button.addEventListener("click", () => {
    selectOperatorTab(button.dataset.operatorTab);
  });
  button.addEventListener("keydown", handleOperatorTabKeydown);
}
elements.drawZone.addEventListener("click", startZoneDrawing);
elements.registerSensor.addEventListener("click", startSensorRegistration);
elements.manageOperators.addEventListener("click", openOperatorEditor);
elements.manageSecurity.addEventListener("click", () => void openSecurityCenter());
elements.storageRefresh.addEventListener("click", () => {
  void loadStorageUsage(true);
});
elements.operatorEditorClose.addEventListener("click", () => {
  elements.operatorEditor.classList.add("hidden");
});
elements.themeToggle.addEventListener("click", () => {
  setTheme(currentTheme === "dark" ? "light" : "dark");
});
elements.sidebarToggle.addEventListener("click", () => {
  setSidebarHidden(!elements.workspace.classList.contains("sidebar-hidden"));
});
elements.securityEditorClose.addEventListener("click", () => {
  elements.securityEditor.classList.add("hidden");
});
elements.securityRefresh.addEventListener("click", () => void loadSecurityCenter());
elements.securityApplyFilters.addEventListener("click", () => void loadSecurityCenter());
elements.securityExportCsv.addEventListener("click", () => downloadSecurityEvents("csv"));
elements.securityExportJson.addEventListener("click", () => downloadSecurityEvents("json"));
elements.operatorCreateForm.addEventListener("submit", createOperatorAccount);
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
  } else if (
    event.key === "Escape" &&
    !elements.securityEditor.classList.contains("hidden")
  ) {
    elements.securityEditor.classList.add("hidden");
  } else if (
    event.key === "Escape" &&
    !elements.operatorEditor.classList.contains("hidden")
  ) {
    elements.operatorEditor.classList.add("hidden");
  } else if (event.key === "Escape" && operatorMenuOpen) {
    setOperatorMenuOpen(false);
  }
});

applyOperationalSidebarOrder();
initializeDisplaySettings();
initializeCollapsibleSections();
initializeAlertAudioSettings();
updateOperatorUi();
setOperatorMenuOpen(false);

async function restoreSession() {
  try {
    const session = await requestJson("/api/v1/auth/me");
    acceptSession(session);
    if (!currentUser.must_change_password) {
      await loadInitialDashboard();
    }
  } catch (error) {
    clearSession(
      error instanceof ApiError && error.status === 401
        ? "Zaloguj się kontem RDDS."
        : "API uwierzytelniania jest niedostępne.",
    );
  }
}

restoreSession();
setInterval(refresh, REFRESH_INTERVAL_MS);
setInterval(repeatCriticalAlertSound, CRITICAL_REPEAT_INTERVAL_MS);
