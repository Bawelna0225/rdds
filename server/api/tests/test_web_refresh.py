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


class WebRefreshBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = WEB_SOURCE.read_text(encoding="utf-8")
        cls.index = WEB_INDEX.read_text(encoding="utf-8")
        cls.styles = WEB_STYLES.read_text(encoding="utf-8")
        cls.track_detection_migration = TRACK_DETECTION_MIGRATION.read_text(
            encoding="utf-8"
        )
        match = re.search(
            r"async function refresh\(.*?\n}\n\nelements\.showEnded",
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
            'include_closed=true',
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
        self.assertIn('/api/v1/alerts?include_closed=true&limit=1000', action_reload)
        self.assertNotIn("await refresh()", action_reload)

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
