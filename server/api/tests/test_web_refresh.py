import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
WEB_SOURCE = PROJECT_ROOT / "web" / "src" / "main.js"
WEB_INDEX = PROJECT_ROOT / "web" / "index.html"
WEB_STYLES = PROJECT_ROOT / "web" / "src" / "styles.css"
TRACK_DETECTION_MIGRATION = (
    PROJECT_ROOT / "database" / "migrations" / "014_track_detection_audit.sql"
)
SENSOR_SUPERVISION_MIGRATION = (
    PROJECT_ROOT / "database" / "migrations" / "015_sensor_supervision.sql"
)
SENSOR_DIAGNOSTICS_MIGRATION = (
    PROJECT_ROOT / "database" / "migrations" / "016_sensor_diagnostics.sql"
)
SENSOR_STREAM_QUALITY_MIGRATION = (
    PROJECT_ROOT / "database" / "migrations" / "017_sensor_stream_quality.sql"
)
SKYSPY_EMULATOR = PROJECT_ROOT / "skyspy-emulator" / "main.py"
COMPOSE_SOURCE = PROJECT_ROOT / "compose.yaml"


class WebRefreshBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = WEB_SOURCE.read_text(encoding="utf-8")
        cls.index = WEB_INDEX.read_text(encoding="utf-8")
        cls.styles = WEB_STYLES.read_text(encoding="utf-8")
        cls.track_detection_migration = TRACK_DETECTION_MIGRATION.read_text(
            encoding="utf-8"
        )
        cls.sensor_supervision_migration = SENSOR_SUPERVISION_MIGRATION.read_text(
            encoding="utf-8"
        )
        cls.sensor_diagnostics_migration = SENSOR_DIAGNOSTICS_MIGRATION.read_text(
            encoding="utf-8"
        )
        cls.sensor_stream_quality_migration = (
            SENSOR_STREAM_QUALITY_MIGRATION.read_text(encoding="utf-8")
        )
        cls.skyspy_emulator = SKYSPY_EMULATOR.read_text(encoding="utf-8")
        cls.compose_source = COMPOSE_SOURCE.read_text(encoding="utf-8")
        match = re.search(
            r"async function refresh\(.*?\n}\n\nelements\.closedAlertApply",
            cls.source,
            flags=re.DOTALL,
        )
        if match is None:
            raise AssertionError("Could not isolate the live refresh function")
        cls.live_refresh = match.group(0)

    def test_periodic_refresh_only_fetches_live_operational_data(self) -> None:
        expected_live_paths = (
            '/api/v1/sensors',
            '/api/v1/tracks?include_ended=false',
            '/api/v1/tracks/trails?seconds=',
            '/api/v1/alerts?include_closed=false',
        )
        for path in expected_live_paths:
            with self.subTest(path=path):
                self.assertIn(path, self.live_refresh)

        stored_paths = (
            '/api/v1/zones',
            '/api/v1/audit/events',
            '/api/v1/security/events',
            '/api/v1/security/sessions',
            'include_ended=true',
            'closed_only',
        )
        for path in stored_paths:
            with self.subTest(path=path):
                self.assertNotIn(path, self.live_refresh)

    def test_stored_views_have_dedicated_on_demand_loaders(self) -> None:
        for function_name in (
            "loadArchivedTracks",
            "loadClosedAlerts",
            "loadZones",
            "loadAuditEvents",
        ):
            with self.subTest(function=function_name):
                self.assertIn(f"async function {function_name}", self.source)

    def test_track_archive_is_a_separate_on_demand_section(self) -> None:
        self.assertNotIn('id="show-ended"', self.index)
        self.assertIn('data-section-key="archived-tracks"', self.index)
        self.assertIn('id="archived-track-count"', self.index)
        self.assertIn('id="archived-track-list"', self.index)
        self.assertIn("currentArchivedTracks", self.source)
        self.assertIn("section === elements.archivedTracksSection", self.source)
        self.assertIn("!archivedTracksLoaded", self.source)
        self.assertNotIn("showEnded", self.source)
        self.assertNotIn("include_ended=true", self.live_refresh)

    def test_map_fit_action_and_zone_severity_colors_are_explicit(self) -> None:
        self.assertIn("Dopasuj mapę", self.index)
        self.assertNotIn(">Pokaż wszystkie</button>", self.index)
        for severity in ("low", "medium", "high", "critical"):
            with self.subTest(severity=severity):
                self.assertIn(f"legend-symbol zone-{severity}", self.index)
                self.assertIn(f".zone-card.zone-severity-{severity}", self.styles)
        self.assertIn("? severityColor(zone.severity)", self.source)
        self.assertIn('themeColor("--zone-inactive"', self.source)
        self.assertIn("zone-card zone-severity-${zone.severity}", self.source)

    def test_zone_popup_is_readable_and_map_click_focuses_sidebar_card(self) -> None:
        self.assertIn("zone-popup-grid", self.source)
        self.assertIn("minWidth: 260", self.source)
        self.assertIn(".zone-popup-grid {", self.styles)
        self.assertIn(
            "grid-template-columns: max-content minmax(150px, 1fr)",
            self.styles,
        )
        self.assertIn(
            'layer.on("click", () => focusZoneInSidebar(zone.id))',
            self.source,
        )
        self.assertIn("function focusZoneInSidebar", self.source)
        self.assertIn(
            "setSectionCollapsed(elements.zonesSection, false)",
            self.source,
        )
        self.assertIn("card.dataset.zoneId = String(zone.id)", self.source)

    def test_sensor_map_click_reveals_matching_sidebar_card(self) -> None:
        self.assertIn(
            'marker.on("click", () => focusSensorInSidebar(sensor.id))',
            self.source,
        )
        self.assertIn("function focusSensorInSidebar", self.source)
        self.assertIn(
            "setSectionCollapsed(elements.sensorsSection, false)",
            self.source,
        )
        self.assertIn("selectSensor(sensorId)", self.source)
        self.assertIn("card.dataset.sensorId = String(sensor.id)", self.source)
        sensor_focus = self.source.split(
            "function focusSensorInSidebar", 1,
        )[1].split("function renderZoneList", 1)[0]
        self.assertIn("setSidebarHidden(false)", sensor_focus)
        self.assertIn("scrollIntoView", sensor_focus)

    def test_sensor_quality_history_is_on_demand_and_explains_failures(self) -> None:
        self.assertIn("function renderSensorQualityHistory", self.source)
        self.assertIn("async function refreshSelectedSensorQualityHistory", self.source)
        self.assertIn("/quality-history?limit=18", self.source)
        self.assertNotIn("/quality-history", self.live_refresh)
        self.assertIn("source_data_invalid", self.source)
        self.assertIn("source_unstable", self.source)
        self.assertIn("quality_ignored_ratio", self.source)
        self.assertIn("quality_reconnects", self.source)
        self.assertIn("quality_window_seconds", self.sensor_stream_quality_migration)
        self.assertIn("reported_quality_ignored_ratio", self.sensor_stream_quality_migration)
        self.assertIn("OLD.health_reason IS DISTINCT FROM NEW.health_reason", self.sensor_stream_quality_migration)

    def test_sensor_health_overview_is_loaded_only_on_demand(self) -> None:
        self.assertIn('id="sensor-overview-open"', self.index)
        self.assertIn('id="sensor-overview-panel"', self.index)
        self.assertIn('id="sensor-overview-list"', self.index)
        self.assertIn("async function loadSensorOverview", self.source)
        self.assertIn('/api/v1/sensors/health-overview', self.source)
        self.assertNotIn('/api/v1/sensors/health-overview', self.live_refresh)
        self.assertIn("mergeSensorOverviewWithLive", self.live_refresh)

    def test_sensor_health_overview_prioritizes_issues_and_opens_sensor(self) -> None:
        self.assertIn("function sensorOverviewPriority", self.source)
        priority = self.source.split(
            "function sensorOverviewPriority", 1,
        )[1].split("function sensorOverviewQuality", 1)[0]
        self.assertLess(priority.index("offline: 0"), priority.index("degraded: 1"))
        self.assertLess(priority.index("degraded: 1"), priority.index("online: 3"))
        self.assertIn('row.dataset.sensorId = String(sensor.id)', self.source)
        self.assertIn("closeSensorOverview({ restoreFocus: false });", self.source)
        self.assertIn("focusSensorInSidebar(sensor.id);", self.source)

    def test_sensor_health_overview_has_filters_sticky_header_and_theme(self) -> None:
        for control in (
            "sensor-overview-search",
            "sensor-overview-filter",
            "sensor-overview-sort",
            "sensor-overview-refresh",
        ):
            with self.subTest(control=control):
                self.assertIn(f'id="{control}"', self.index)
        overview_header = self.styles.split(
            ".sensor-overview-header {", 1,
        )[1].split("}", 1)[0]
        self.assertIn("position: sticky", overview_header)
        self.assertIn('html[data-theme="light"] .sensor-overview-panel', self.styles)
        self.assertIn('html[data-theme="light"] .sensor-overview-row', self.styles)

    def test_selection_close_action_stays_visible_while_details_scroll(self) -> None:
        self.assertIn('class="selection-header"', self.index)
        self.assertIn('id="close-selection"', self.index)
        selection_header = self.styles.split(".selection-header {", 1)[1].split(
            "}", 1
        )[0]
        self.assertIn("position: sticky", selection_header)
        self.assertIn("top: -16px", selection_header)
        self.assertIn("background:", selection_header)
        self.assertIn("box-shadow:", selection_header)
        self.assertIn(
            'html[data-theme="light"] .selection-header {',
            self.styles,
        )

    def test_light_theme_uses_distinct_map_and_status_palette(self) -> None:
        light_theme = self.styles.split('html[data-theme="light"] {', 1)[1]
        for variable in (
            "--zone-low",
            "--zone-medium",
            "--zone-high",
            "--zone-critical",
            "--zone-inactive",
        ):
            with self.subTest(variable=variable):
                self.assertIn(variable, light_theme)
        self.assertIn("function severityColor(severity)", self.source)
        self.assertIn("function refreshMapThemeColors()", self.source)
        self.assertIn("refreshMapThemeColors();", self.source)
        self.assertIn(
            'html[data-theme="light"] .sensor-card.selected',
            self.styles,
        )
        self.assertIn(
            'html[data-theme="light"] .sensor-diagnostic-check.diagnostic-error',
            self.styles,
        )
        for category in ("alert", "track", "sensor", "account", "zone", "system"):
            with self.subTest(audit_category=category):
                self.assertIn(
                    f'html[data-theme="light"] .audit-card.audit-{category}',
                    self.styles,
                )
        diagnostic_ok = self.styles.split(
            'html[data-theme="light"] .sensor-diagnostic-check.diagnostic-ok {',
            1,
        )[1].split("}", 1)[0]
        self.assertIn("border-left-color: var(--green)", diagnostic_ok)
        self.assertIn(
            'html[data-theme="light"] .sensor-diagnostic-check.diagnostic-ok strong',
            self.styles,
        )

    def test_sidebar_uses_operational_priority_order(self) -> None:
        order_source = self.source.split(
            "function applyOperationalSidebarOrder()", 1
        )[1].split("function revealAlertsSectionForNewAlarm()", 1)[0]
        expected_order = (
            '"alerts"',
            '"tracks"',
            '"zones"',
            '"sensors"',
            '"archived-tracks"',
            '"closed-alerts"',
            '"audit"',
        )
        positions = [order_source.index(section) for section in expected_order]
        self.assertEqual(positions, sorted(positions))
        self.assertLess(
            self.source.index("applyOperationalSidebarOrder();"),
            self.source.index("initializeCollapsibleSections();"),
        )

    def test_theme_switch_covers_interface_map_and_persists_choice(self) -> None:
        self.assertIn('id="theme-toggle"', self.index)
        self.assertIn('meta name="color-scheme" content="dark light"', self.index)
        self.assertIn('const DISPLAY_SETTINGS_KEY = "rdds.display.v1"', self.source)
        self.assertIn("function setTheme(theme", self.source)
        self.assertIn("document.documentElement.dataset.theme = currentTheme", self.source)
        self.assertIn("writeDisplaySettings({ theme: currentTheme })", self.source)
        self.assertIn('html[data-theme="light"] {', self.styles)
        self.assertIn('html[data-theme="light"] .leaflet-tile-pane', self.styles)
        self.assertIn("filter: none", self.styles)

    def test_sidebar_can_be_hidden_restored_and_reopened_from_zone(self) -> None:
        self.assertIn('id="sidebar-toggle"', self.index)
        self.assertIn('aria-controls="sidebar"', self.index)
        self.assertIn("function setSidebarHidden(hidden", self.source)
        self.assertIn('writeDisplaySettings({ sidebarHidden: hidden })', self.source)
        self.assertIn('elements.sidebar.inert = hidden', self.source)
        self.assertIn("scheduleMapResize()", self.source)
        self.assertIn("map.invalidateSize", self.source)
        self.assertIn("setSidebarHidden(false);", self.source)
        self.assertIn(".workspace.sidebar-hidden {", self.styles)
        self.assertIn("grid-template-columns: 0 minmax(0, 1fr)", self.styles)

    def test_global_telemetry_loader_is_not_present(self) -> None:
        self.assertNotIn("global-loading", self.source)
        self.assertNotIn("setDashboardLoading", self.source)

    def test_security_event_log_is_loaded_only_on_demand(self) -> None:
        self.assertIn("async function loadSecurityCenter", self.source)
        self.assertIn('fetchJson("/api/v1/security/sessions")', self.source)
        self.assertIn("/api/v1/security/events?", self.source)
        self.assertNotIn("/api/v1/security/events?", self.live_refresh)

    def test_incident_history_and_route_are_loaded_only_on_demand(self) -> None:
        self.assertIn("async function refreshSelectedIncidentTimeline", self.source)
        self.assertIn("async function showIncidentRoute", self.source)
        self.assertIn("/api/v1/audit/events?alert_id=", self.source)
        self.assertNotIn("/api/v1/audit/events?alert_id=", self.live_refresh)
        self.assertNotIn("/history?limit=10000", self.live_refresh)

    def test_operational_sounds_use_track_and_alert_baselines(self) -> None:
        self.assertIn("function processOperationalSounds", self.source)
        self.assertIn("!trackAudioBaselineReady", self.source)
        self.assertIn("!knownTrackIds.has(String(track.id))", self.source)
        self.assertIn("!knownAlertIds.has(String(alert.id))", self.source)
        self.assertIn(
            "processOperationalSounds(currentLiveTracks, incomingOpenAlerts)",
            self.live_refresh,
        )
        self.assertIn("if (newAlerts.length > 0)", self.source)
        self.assertIn("else if (newTracks.length > 0)", self.source)

    def test_every_severity_has_a_prominent_audible_profile(self) -> None:
        for severity in ("detected", "low", "medium", "high", "critical"):
            with self.subTest(severity=severity):
                self.assertIn(f"{severity}: {{", self.source)
        self.assertNotIn("low: []", self.source)
        self.assertIn("profile.steps.forEach", self.source)
        self.assertIn("step.duration + step.gap", self.source)
        self.assertIn("profile.gain", self.source)
        self.assertIn("profile.attackSeconds", self.source)
        self.assertIn("profile.releaseSeconds", self.source)
        self.assertIn("endFrequency: 720", self.source)
        self.assertIn("endFrequency: 260", self.source)
        self.assertIn("endFrequency: 1450", self.source)
        self.assertIn("Array.from({ length: 18 }", self.source)

    def test_new_track_sound_is_an_alarm_not_a_startup_chime(self) -> None:
        detected_profile = self.source.split("detected: {", 1)[1].split(
            "\n  low: {", 1
        )[0]
        self.assertIn('waveform: "sawtooth"', detected_profile)
        self.assertIn("frequency: 1350", detected_profile)
        self.assertIn("endFrequency: 720", detected_profile)
        self.assertGreaterEqual(detected_profile.count("frequency: 1350"), 4)
        self.assertNotIn('waveform: "triangle"', detected_profile)

    def test_mute_and_volume_control_the_active_sound(self) -> None:
        self.assertIn("function stopActiveAlertSounds", self.source)
        self.assertIn("oscillator.stop()", self.source)
        self.assertIn("function updateAlertAudioMasterVolume", self.source)
        self.assertIn("gain.connect(alertAudioMasterGain)", self.source)
        self.assertIn("Math.max(0, storedVolume)", self.source)
        self.assertIn(
            "elements.alarmAudioTest.disabled = !alertAudioSettings.enabled",
            self.source,
        )
        self.assertIn(
            "elements.alarmAudioTestProfile.disabled = !alertAudioSettings.enabled",
            self.source,
        )
        self.assertIn(
            'setAttribute("aria-pressed", String(!alertAudioSettings.enabled))',
            self.source,
        )
        self.assertNotIn(
            'async function playAlertSound(profileName = "high", force = false)',
            self.source,
        )

    def test_alert_actions_lock_the_card_until_write_and_reload_finish(self) -> None:
        self.assertIn("const pendingAlertActions = new Map()", self.source)
        self.assertIn("pendingAlertActions.has(alertId)", self.source)
        self.assertIn("pendingAlertActions.set(alertId, action)", self.source)
        self.assertIn("await reloadAlertsAfterAction()", self.source)
        self.assertIn("pendingAlertActions.delete(alertId)", self.source)
        self.assertIn('card.setAttribute("aria-busy", "true")', self.source)
        self.assertIn('loader.className = "alert-action-loader"', self.source)
        self.assertIn('spinner.className = "alert-action-spinner"', self.source)
        self.assertIn("main.disabled = Boolean(pendingAction)", self.source)
        self.assertIn("acknowledge.disabled = Boolean(pendingAction)", self.source)
        self.assertIn("close.disabled = Boolean(pendingAction)", self.source)

    def test_alert_action_reload_is_scoped_to_alert_data(self) -> None:
        match = re.search(
            r"async function reloadAlertsAfterAction\(\).*?\n}",
            self.source,
            flags=re.DOTALL,
        )
        if match is None:
            raise AssertionError("Could not isolate alert action reload")
        action_reload = match.group(0)
        self.assertIn('/api/v1/alerts?include_closed=false', action_reload)
        self.assertIn("if (closedAlertsLoaded)", action_reload)
        self.assertIn("await loadClosedAlerts({ showLoader: false })", action_reload)
        self.assertNotIn("await refresh()", action_reload)

    def test_closed_alert_archive_is_collapsible_filtered_and_not_live(self) -> None:
        self.assertNotIn('id="show-closed-alerts"', self.index)
        self.assertIn('data-section-key="closed-alerts"', self.index)
        self.assertIn('id="closed-alert-from"', self.index)
        self.assertIn('id="closed-alert-to"', self.index)
        self.assertIn('id="closed-alert-list"', self.index)
        self.assertIn('closed_only: "true"', self.source)
        self.assertIn('parameters.set("closed_from"', self.source)
        self.assertIn('parameters.set("closed_before"', self.source)
        self.assertNotIn("closed_only", self.live_refresh)
        self.assertIn(".closed-alert-list .alert-card + .alert-card", self.styles)

    def test_stale_live_alert_payload_cannot_restore_a_closed_card(self) -> None:
        self.assertIn("let alertDataRevision = 0", self.source)
        self.assertIn("const alertRevisionAtStart = alertDataRevision", self.live_refresh)
        self.assertIn(
            "const alertPayloadIsCurrent = alertRevisionAtStart === alertDataRevision",
            self.live_refresh,
        )
        self.assertIn("if (alertPayloadIsCurrent)", self.live_refresh)
        self.assertGreaterEqual(self.source.count("alertDataRevision += 1"), 3)

    def test_incident_details_preserve_acknowledgement_and_closure_actors(self) -> None:
        self.assertIn('detailItem("Potwierdził", alert.acknowledged_by)', self.source)
        self.assertIn(
            'detailItem("Czas potwierdzenia", formatDateTime(alert.acknowledged_at))',
            self.source,
        )
        self.assertIn('detailItem("Zamknął", alert.closed_by)', self.source)
        self.assertIn(
            'detailItem("Czas zamknięcia", formatDateTime(alert.closed_at))',
            self.source,
        )

    def test_rdds_accounts_are_distinct_from_remote_id_operators(self) -> None:
        self.assertIn(
            '<option value="operators">Konta i sesje RDDS</option>',
            self.index,
        )
        self.assertIn('legend-symbol pilot"></span>Operator drona', self.index)
        self.assertIn('if (eventType.startsWith("operator_")) return "account"', self.source)
        self.assertIn('detailItem("Wykonawca zdarzenia", event.actor)', self.source)
        self.assertIn(
            'detailItem("Operator drona (Remote ID)", event.operator_id)',
            self.source,
        )
        self.assertIn(
            '<h3 class="popup-title">Operator drona (Remote ID)</h3>',
            self.source,
        )
        self.assertNotIn('detailItem("Operator", track.operator_id)', self.source)
        self.assertNotIn('detailItem("Operator", observation.operator_id)', self.source)
        self.assertIn(".audit-card.audit-account", self.styles)
        self.assertIn("border-left-color: var(--account-blue)", self.styles)
        self.assertNotIn(".audit-card.audit-operator", self.styles)

    def test_audit_timeline_heading_matches_its_subject(self) -> None:
        self.assertIn('id="selection-timeline-title"', self.index)
        for title in (
            "Historia alarmu strefowego",
            "Historia sensora",
            "Historia konta RDDS",
            "Historia strefy chronionej",
            "Powiązane zdarzenia",
        ):
            with self.subTest(title=title):
                self.assertIn(title, self.source)
        self.assertNotIn("<h3>Historia incydentu</h3>", self.index)

    def test_new_active_alert_expands_only_the_alert_section(self) -> None:
        self.assertIn("function revealAlertsSectionForNewAlarm()", self.source)
        self.assertIn(
            "setSectionCollapsed(elements.alertsSection, false, false)",
            self.source,
        )
        process_match = re.search(
            r"function processOperationalSounds\(.*?\n}",
            self.source,
            flags=re.DOTALL,
        )
        if process_match is None:
            raise AssertionError("Could not isolate operational sound processing")
        process_source = process_match.group(0)
        self.assertIn("if (newAlerts.length > 0)", process_source)
        self.assertIn("revealAlertsSectionForNewAlarm()", process_source)

    def test_new_track_detection_is_a_single_session_audit_event(self) -> None:
        self.assertIn('track_detected: "Nowy dron w zasięgu sensora"', self.source)
        self.assertIn('option value="detections"', self.index)
        self.assertIn('eventType.startsWith("track_")', self.source)
        self.assertIn(
            'parameter = `track_id=${encodeURIComponent(selectedAuditEvent.track_id)}`',
            self.source,
        )
        self.assertIn("AFTER INSERT ON tracks", self.track_detection_migration)
        self.assertNotIn("AFTER INSERT OR UPDATE ON tracks", self.track_detection_migration)
        self.assertIn("uq_audit_events_track_detected", self.track_detection_migration)
        self.assertIn("WHERE event_type = 'track_detected'", self.track_detection_migration)
        self.assertIn("ON CONFLICT DO NOTHING", self.track_detection_migration)

    def test_sensor_supervision_separates_agent_source_and_queue_health(self) -> None:
        for field in (
            "source_connected",
            "source_last_message_at",
            "reported_queue_depth",
            "reported_dead_letter_depth",
            "last_heartbeat_received_at",
        ):
            with self.subTest(field=field):
                self.assertIn(field, self.sensor_supervision_migration)
        self.assertIn("health_issue_started_at IS NOT NULL", self.sensor_supervision_migration)
        self.assertIn("sensor_health_changed", self.sensor_supervision_migration)

    def test_sensor_health_is_live_and_maintenance_is_administrative(self) -> None:
        self.assertIn("function processSensorHealth", self.source)
        self.assertIn("function renderSensorHealthSummary", self.source)
        self.assertIn('id="sensor-health-banner"', self.index)
        self.assertIn("/maintenance`,", self.source)
        self.assertIn("runSensorMaintenance", self.source)
        self.assertIn("sensor.status === \"degraded\"", self.source)

    def test_sensor_card_gives_health_diagnostics_a_separate_wrapping_row(self) -> None:
        self.assertIn('meta.className = "entity-meta sensor-meta"', self.source)
        self.assertIn('health.textContent = `Tor detekcji:', self.source)
        self.assertIn(".sensor-meta {", self.styles)
        self.assertIn("grid-template-columns: minmax(0, 1fr) auto", self.styles)
        self.assertIn("overflow-wrap: anywhere", self.styles)

    def test_sensor_diagnostics_are_grouped_and_exportable(self) -> None:
        self.assertIn('id="sensor-controls"', self.index)
        self.assertIn('id="sensor-diagnostics-export"', self.index)
        self.assertIn("function sensorDiagnosticSummary(sensor)", self.source)
        self.assertIn("function downloadSelectedSensorDiagnostics()", self.source)
        for heading in ("Stan operacyjny", "Agent", "Sky-Spy → agent", "Agent → RDDS"):
            with self.subTest(heading=heading):
                self.assertIn(f'detailSection("{heading}")', self.source)
        self.assertIn("sensor-diagnostic-summary", self.styles)
        self.assertNotIn('"token_prefix",', self.source.split("const fields = [", 1)[1].split("];", 1)[0])

    def test_sensor_diagnostic_migration_keeps_counters_in_heartbeats(self) -> None:
        for field in (
            "input_lines_total",
            "parsed_detections_total",
            "enqueued_observations_total",
            "delivery_success_total",
            "delivery_retry_total",
            "queue_oldest_age_seconds",
            "last_delivery_error_reason",
        ):
            with self.subTest(field=field):
                self.assertIn(field, self.sensor_diagnostics_migration)
        self.assertNotIn("ALTER TABLE sensors\n", self.sensor_diagnostics_migration)

    def test_skyspy_emulator_has_controlled_fault_modes(self) -> None:
        for mode in ("normal", "silent", "malformed", "disconnect"):
            with self.subTest(mode=mode):
                self.assertIn(f'"{mode}"', self.skyspy_emulator)
        self.assertIn("RDDS_SKYSPY_EMULATOR_FAULT_MODE", self.compose_source)
        self.assertIn(
            "RDDS_SKYSPY_EMULATOR_DISCONNECT_AFTER_MESSAGES",
            self.compose_source,
        )

    def test_sidebar_lists_scroll_without_squashing_cards_and_sections_are_divided(self) -> None:
        self.assertIn(".entity-list > .entity-card", self.styles)
        self.assertIn("flex: 0 0 auto", self.styles)
        self.assertIn(".sidebar-section + .sidebar-section", self.styles)
        self.assertIn("border-top: 1px solid rgba(67, 213, 255, 0.34)", self.styles)

    def test_account_menu_keeps_audio_training_out_of_primary_tabs(self) -> None:
        for tab_name in ("admin", "account"):
            with self.subTest(tab=tab_name):
                self.assertIn(f'data-operator-tab="{tab_name}"', self.index)
                self.assertIn(f'data-operator-tab-panel="{tab_name}"', self.index)
        self.assertNotIn('data-operator-tab="alerts"', self.index)
        self.assertNotIn('data-operator-tab-panel="alerts"', self.index)
        self.assertIn('class="operator-tab active hidden"', self.index)
        self.assertIn("Administracja", self.index)
        self.assertIn("Konto", self.index)
        self.assertIn('class="operator-quick-volume"', self.index)
        self.assertIn('id="alarm-audio-volume"', self.index)
        account_panel = self.index.split(
            'data-operator-tab-panel="account"', 1
        )[1]
        self.assertIn('id="password-form"', account_panel)
        self.assertIn('id="operator-lock"', account_panel)
        admin_panel = self.index.split(
            'data-operator-tab-panel="admin"', 1
        )[1].split('data-operator-tab-panel="account"', 1)[0]
        self.assertIn('id="alarm-training-tools"', admin_panel)
        self.assertIn("Narzędzia szkoleniowe dźwięków", admin_panel)
        self.assertIn('id="alarm-audio-test-profile"', admin_panel)
        self.assertIn('id="alarm-audio-test"', admin_panel)
        self.assertIn('id="alarm-audio-repeat"', admin_panel)

    def test_account_menu_role_and_password_rules_are_enforced(self) -> None:
        self.assertIn("function selectOperatorTab(tabName", self.source)
        self.assertIn(
            'selectOperatorTab(currentUser?.must_change_password ? "account" : "admin")',
            self.source,
        )
        self.assertIn(
            'elements.operatorAdminTab.classList.toggle("hidden", !canOperate())',
            self.source,
        )
        self.assertNotIn("operatorAlertsTab", self.source)
        self.assertIn("elements.alarmTrainingTools.open = false", self.source)
        self.assertIn('selectOperatorTab("account")', self.source)
        self.assertIn(
            'selectOperatorTab(canOperate() ? "admin" : "account")',
            self.source,
        )
        self.assertIn("function handleOperatorTabKeydown(event)", self.source)


if __name__ == "__main__":
    unittest.main()
