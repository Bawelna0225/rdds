# RDDS Stage 27C — Agent update plan drafts

Stage 27C adds a **draft-only planning layer** between the agent release catalog and any future update execution mechanism. It lets an administrator select one published release and an ordered set of sensors, then records an immutable assessment snapshot for review.

This stage deliberately does not download or install an artifact, does not assign a desired agent version, does not modify sensor configuration, and does not expose approve, start, or execute actions.

## Data model

Migration `030_sensor_agent_update_plans.sql` adds:

- `sensor_agent_update_plans` — revisioned `draft`/`cancelled` lifecycle plus a snapshot of the published release identity;
- `sensor_agent_update_plan_targets` — ordered, immutable snapshots of each selected sensor's status, reported agent version, eligibility state, and reason codes;
- `sensor_agent_update_plan_created` and `sensor_agent_update_plan_cancelled` audit events.

The plan snapshots the release version, channel, SHA-256 digest, minimum agent version, and protocol version. Later edits or withdrawal of the catalog entry therefore cannot rewrite what the operator originally reviewed.

## Eligibility snapshot

Each target is classified at draft creation time as one of:

- `eligible` — online/degraded and running a compatible older version;
- `already_current` — target release already installed;
- `below_minimum` — current version is below the release's supported update floor;
- `ahead` — current version is newer than the selected target;
- `unreported` — missing or invalid reported version;
- `inactive` — sensor is not online or degraded.

Eligibility is planning information only. A target that is not eligible may still be included so the draft provides a complete reviewable snapshot; no runtime action follows.

## API

Viewer endpoints:

- `GET /api/v1/sensor-agent-update-plans`
- `GET /api/v1/sensor-agent-update-plans/{plan_id}`

Administrator write endpoints:

- `POST /api/v1/sensor-agent-update-plans`
- `POST /api/v1/sensor-agent-update-plans/{plan_id}/cancel`

Creation accepts only a currently published release and 1–100 unique, non-deleted sensors. Cancellation uses an expected revision and a database row lock to prevent stale writes.

## Web UI

The **Wydania agentów** tab now contains a separate draft-planning section. It supports:

- selecting a published release;
- selecting target sensors, with currently eligible sensors preselected;
- reviewing the immutable target snapshot;
- showing cancelled plans on demand;
- cancelling a draft with an operator reason.

Both mutations require confirmation and explicitly state that sensor runtime remains unchanged.

## Safety boundary

Stage 27C provides no artifact URL, binary upload, agent command, desired-version assignment, approval, scheduling, rollout start, or installation path. The sensor agent and configuration rollout mechanisms are unchanged.

Any future execution stage must introduce independent artifact authenticity verification, an explicit approval gate, bounded batches, application reporting, timeout handling, automatic pause, and rollback/recovery design before it can modify a sensor.

## Release completion

After runtime validation of draft creation, immutable target assessment, cancellation, and unchanged sensor configuration, Stage 27A–27C completes RDDS `0.27.0`. The product version is finalized in the API and Web package only; the running sensor agent remains on its independently reported version until a future, separately approved update mechanism exists.
