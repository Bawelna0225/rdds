# RDDS Stage 24A — configuration profiles and immutable history

Stage 24A adds reusable configuration profiles for future controlled rollout to
20–100 sensors. It does not assign profiles to sensors and does not change agent
behavior. Those operations remain explicitly reserved for Stage 24B.

## Data model

`sensor_configuration_profiles` stores profile identity, metadata, enabled
state, and the current version number. `sensor_configuration_profile_versions`
stores immutable configuration snapshots.

The current `(profile_id, version)` pair is protected by a deferred foreign key.
Creating a new version locks the profile row, inserts the next immutable version,
and moves the profile pointer in the same transaction. Concurrent writers cannot
receive the same version number.

Profiles cannot contain arbitrary agent settings. Every version is validated
through the existing `SensorManagedConfiguration` allow-list:

- `heartbeat_seconds`;
- `reconnect_seconds`;
- `request_timeout_seconds`;
- `replay_messages_per_second`.

## API

Viewer access:

```text
GET /api/v1/sensor-configuration-profiles
GET /api/v1/sensor-configuration-profiles/{profile_id}
GET /api/v1/sensor-configuration-profiles/{profile_id}/versions
```

Administrator and CSRF protection required:

```text
POST /api/v1/sensor-configuration-profiles
PUT  /api/v1/sensor-configuration-profiles/{profile_id}
POST /api/v1/sensor-configuration-profiles/{profile_id}/versions
```

The list and version history endpoints support `limit` and `offset`. Disabled
profiles remain in history and can be included explicitly in the list.

## Audit

Migration 022 allow-lists and records:

- `sensor_configuration_profile_created`;
- `sensor_configuration_profile_updated`;
- `sensor_configuration_profile_version_created`.

Every configuration version requires a change note. Profile deletion is not
implemented, so historical versions cannot disappear through the API.

## Release boundary

Stage 24A keeps the public version at `0.23.0`. It adds no sensor assignment,
bulk operation, rollout, rollback, Web UI, or agent update behavior. These are
the safety boundary for Stage 24B and 24C.
