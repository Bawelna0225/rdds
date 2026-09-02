# RDDS Stage 24C — Fleet configuration Web console

Stage 24C closes RDDS v0.24.0 by exposing the profile and controlled-rollout
control plane from Stages 24A and 24B in the administrator Web interface.

## Scope

- dedicated **Konfiguracja floty** administrator console;
- configuration profile list, metadata update and enable/disable state;
- profile creation with the first immutable version;
- immutable version history and explicit creation of a new version;
- controlled rollout draft creation for 1–100 sensors;
- pinned profile version and batch size from 1–25;
- detailed rollout counters and per-target state;
- separate, confirmed `start`, `advance` and `cancel` actions;
- explicit, confirmed rollback from a completed or cancelled rollout;
- terminal rollout visibility switch;
- assigned profile and version shown in the single-sensor configuration editor;
- Polish labels for profile and rollout audit events.

Migration `024_sensor_configuration_rollout_rollback.sql` adds explicit rollback
metadata to rollouts and targets and allow-lists the rollback audit event. No
sensor-agent change is introduced in Stage 24C.

## Safety model

Creating a rollout always creates only a `draft`. It never changes sensor
configuration. The administrator must explicitly start the first batch.

`advance` remains disabled until the API returns `can_advance=true`, which means
all previously deployed targets are compliant and none is in error or has been
superseded. The server remains authoritative and re-checks this condition in a
transaction.

Cancelling a rollout does not automatically roll back configurations already
deployed to sensors. The Web confirmation states this explicitly.

Rollback is a separate administrator operation available only for a completed
or cancelled rollout. Before any write, the API locks and validates every
deployed target. It refuses the complete transaction when a sensor was
superseded, its assignment changed, or its pre-rollout snapshot is not a full
managed configuration. The rollback restores the snapshot as a **new**, higher
desired revision; revision numbers never move backwards. The agent then applies
and reports that revision through the existing Stage 23B channel.

Manual editing of a sensor configuration remains available, but the editor now
shows its assigned profile and warns that a manual save detaches the profile
assignment.

## Managed fields

Profiles contain only the established allow-listed agent settings:

- `heartbeat_seconds` (2–3600),
- `reconnect_seconds` (0.5–300),
- `request_timeout_seconds` (1–120),
- `replay_messages_per_second` (0.1–100).

Credentials, API addresses, source devices and arbitrary commands are not part
of fleet profiles.

## Validation

Run the complete API/static Web test suite and the production Web build. Then
open **Konto operatora → Administracja → Konfiguracja floty** and verify profile
history, draft creation and the explicit rollout action controls.
