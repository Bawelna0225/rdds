# RDDS 0.16.0: zone incident awareness

RDDS 0.16.0 turns a protected-zone alarm into a persistent incident record.
It preserves what was observed when the drone entered the zone, continues to
show the current track separately and gives the operator a controlled audible
notification for a genuinely new incident.

## Incident model

Two independent states describe each incident:

| Dimension | Values | Meaning |
| --- | --- | --- |
| operator workflow | `active`, `acknowledged`, `closed` | new, confirmed or closed by an operator |
| drone presence | `inside`, `left`, `lost` | currently in the zone, outside it or no longer tracked |

Leaving the zone or losing the track does not automatically close an incident.
The operator can still acknowledge it, inspect its timeline and close it after
the required response is complete. If the drone returns before closure, the
same open incident returns to `inside` and the transition is added to its audit
timeline.

Closing an incident while its track is still inside the zone does not rearm the
same zone-track pair. Continued position updates therefore cannot immediately
create another alarm. The latest closed incident remains the rearm guard until
the processor observes the track definitely outside the zone (or the zone is
disabled); that departure is recorded as `left`. Only a later entry creates a
new incident. A temporary `stale`/`lost` state is not treated as proof that the
drone left, while a genuinely new track session has a different track ID and
can correctly create a new incident.

Acknowledgement and closure provide contextual operation feedback directly on
the affected incident card. Immediately after a click, every action on that
card is disabled and an accessible loading overlay identifies whether RDDS is
confirming or closing the incident. The overlay survives periodic list renders
and remains visible until the API write and the following alert-list read have
completed. A failed write restores the controls and displays the error; a
successful write is never presented as a failure merely because the follow-up
list refresh failed.

The live refresh carries an alert-data revision captured when its request
starts. A confirmation or closure advances this revision before the write and
again before the dedicated post-write read. Consequently, an older two-second
refresh may still finish, but its alert payload is discarded instead of briefly
restoring an incident that has already been closed.

Acknowledgement is an operational hand-off, not incident completion. It stores
the responsible operator and timestamp, moves the workflow from `active` to
`acknowledged`, suppresses optional critical reminder sounds and keeps the same
incident open for continued presence tracking. Closure remains a separate
action. The incident detail view and archived incidents show who acknowledged
and closed the incident and when; direct closure of an active incident leaves
the acknowledgement fields empty by design.

## Operational vocabulary and attention

The audit filter calls RDDS authentication activity **Konta i sesje RDDS**,
while Remote ID people and positions are consistently labelled **Operator
drona**. Account-related audit cards and timeline markers use a dedicated blue
accent rather than the purple used for the drone operator marker. Audit detail
fields distinguish the RDDS event actor from the Remote ID operator.

The detail timeline heading follows its subject: **Historia alarmu strefowego**,
**Historia strefy chronionej**, **Historia sensora** or **Historia konta RDDS**.
Unknown or unlinked entries use the neutral **Powiązane zdarzenia** label and a
neutral colour instead of being treated as zone history.

When a genuinely new active zone alarm appears after the initial silent
baseline, RDDS automatically expands the **Alarmy strefowe** section. The
expansion is independent of audio and does not rewrite the operator's stored
sidebar preference. Track position updates and already-known alarms do not
expand the section.

## Compact account menu

The account popover keeps the alarm volume immediately available and separates
the remaining controls into two accessible tabs:

- **Administracja** contains zone, sensor, RDDS account, security and database
  operations, and is omitted for viewers;
- **Konto** contains the operator's own password change and logout controls.

Choosing and testing individual alarm profiles is an occasional training task,
not a primary account-menu destination. Those controls and the critical-alarm
repeat option are therefore kept in the collapsed **Narzędzia szkoleniowe
dźwięków** section under administration. Opening the account menu collapses the
training section again. The global mute button and the compact volume control
remain available without opening the training tools.

An operator role sees the administration tab with the actions permitted by its
role, while an administrator sees the full set. Administrators and operators
start on **Administracja**; viewers fall back to **Konto**. A mandatory password
change selects **Konto**, disables administration and focuses the
current-password field. The tab list supports mouse, touch, `Home`, `End` and
left/right arrow navigation.

## Immutable entry snapshot

When an incident is opened, migration `013` and the alert processor preserve:

- zone name, description and configured severity;
- track, identity, Basic ID, operator ID and drone MAC identifiers;
- entry position and pilot position;
- altitude, speed and heading;
- the sensor associated with the entry observation;
- first-detection time.

These fields are not overwritten by later track updates or zone edits. The
incident panel displays them under **Zapis w chwili naruszenia** and shows the
current track under **Obiekt teraz**. The operator can center the map on the
entry point, center it on the current position or load the incident route on
demand. The timeline and route are not fetched by the two-second live refresh.

Existing alerts created before 0.16.0 are backfilled on a best-effort basis
from the last alarm and track data available during migration. New incidents
receive an exact entry snapshot from the alert processor.

## Audible notifications

Audio is disabled by default and stored as a browser-local operator preference.
The operator must enable it with **Alarmy wyciszone** in the top bar or in the
operator menu. This interaction also satisfies the browser requirement for a
user gesture before audio playback.

The tones are generated locally with the Web Audio API:

| Severity | Notification |
| --- | --- |
| new track | four harsh descending warning sweeps, approximately 1.4 seconds |
| low | three low descending warning horns, approximately 2.3 seconds |
| medium | four alternating high-low double pulses, approximately 2.4 seconds |
| high | three full rising-and-falling emergency siren cycles, approximately 4.3 seconds |
| critical | rapid high-low emergency klaxon with eighteen pulses, approximately 3.3 seconds |

The profiles deliberately avoid melodic startup-style cues. They use fast
attacks, dissonant changes and repetitive emergency rhythms so that a duty
operator can recognise the approximate incident class without looking at the
screen and is prompted to react instead of treating the sound as background
notification audio.

The first track and alert lists loaded after login establish a silent baseline.
Later notifications are emitted only for previously unseen track or active
alert IDs, never for periodic position changes. If a new track and its zone
alert arrive in the same refresh, the zone alarm takes priority and only one
sound is played. Every severity has an audible profile; severity controls its
duration and urgency rather than whether it is audible.

The operator menu can play each profile independently while audio is enabled.
Its volume slider works through a shared audio gain channel, including while a
sequence is already playing, and `0%` is actual silence. **Wycisz alarmy** is a
strict mute state: it immediately stops all scheduled pulses and blocks every
audio path, including automatic alerts, critical reminders and manual tests.
The test controls remain disabled until audio is enabled again. Enabling audio
is silent. An optional critical reminder repeats every 30 seconds until the
incident is acknowledged. Volume, mute state and the reminder preference are
kept in `localStorage`; the server does not store them.

## Audit trail

Migration `014_track_detection_audit.sql` adds `track_detected` when the track
processor inserts a genuinely new track session. The event is labelled **Nowy
dron w zasięgu sensora**, records the first sensor and appears under the
**Wykrycia dronów** audit filter. It is tied to the track's `first_seen_at`, so
a delayed queued observation retains its original detection time.

The database trigger runs only after `INSERT ON tracks`; position and identity
updates do not invoke it. A partial unique index allows at most one detection
event for each track ID, and the insert is conflict-safe. A drone continuously
observed for an hour therefore creates one detection entry, not one entry per
message. If that session ends and the drone reappears after the configured
session gap, the new session correctly creates a new detection entry. Existing
tracks are deliberately not backfilled during migration.

The new `alert_presence_changed` event records each transition between
`inside`, `left` and `lost`. Alert-linked audit rows use the immutable entry
identity and zone snapshot, so later edits do not rewrite the historical
incident context.

## Upgrade from 0.15.0

Create and verify a backup first. Stop the tracker, alert processor and API
before migrations `013` and `014` so no track can be created before its audit
trigger is installed:

```bash
cd /opt/rdds/source

sudo docker compose run --rm --no-deps \
  --entrypoint /usr/local/bin/backup.sh backup

sudo docker compose stop tracker api alert-processor
sudo docker compose run --rm migrate

sudo docker compose up -d --build --force-recreate \
  api tracker alert-processor web
```

Verify the version, migration and service state:

```bash
curl -fsS http://127.0.0.1:8000/ |
python3 -m json.tool

sudo docker compose exec -T database \
  psql -U rdds -d rdds -Atc \
  "SELECT migration_name FROM rdds_schema_migrations
   WHERE migration_name IN (
     '013_incident_awareness.sql',
     '014_track_detection_audit.sql'
   )
   ORDER BY migration_name;"

sudo docker compose ps -a
sudo docker compose logs --tail=100 api alert-processor web migrate
```

The API root should report `0.16.0`. After a hard browser refresh, create a
test zone and let an emulated drone enter it. Confirm that:

1. the new incident sounds at most once after audio is enabled;
2. entry and live positions are displayed separately;
3. stopping or moving the emulator changes presence to `left` or `lost`
   without closing the incident;
4. the timeline records the presence transition;
5. acknowledgement stops a critical reminder and closure completes the
   workflow;
6. one new track session creates exactly one **Nowy dron w zasięgu sensora**
   audit entry despite subsequent position updates;
7. acknowledging and closing an alarm while the drone remains inside does not
   create another alarm; leaving and entering again does.
