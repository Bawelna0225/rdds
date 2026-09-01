# RDDS Stage 23C — Web configuration and fleet compliance

Stage 23C completes the first sensor fleet configuration release by exposing
the Stage 23A control-plane and Stage 23B agent reporting in the operator Web UI.

## Operator view

- Every sensor card shows configuration compliance and desired/applied revisions.
- Sensor details include a dedicated configuration section.
- The fleet overview shows a configuration column, a non-compliance counter,
  a filter, and compliance-aware sorting.
- Viewers and operators can see compliance. Only administrators receive the
  configuration action.

## Administrator workflow

The configuration editor reads the latest state from
`GET /api/v1/sensors/{sensor_id}/configuration` and writes through the existing
CSRF-protected administrator request path to the corresponding `PUT` endpoint.
The UI validates the same numeric limits as the API:

| Setting | Minimum | Maximum |
| --- | ---: | ---: |
| `heartbeat_seconds` | 2 | 3600 |
| `reconnect_seconds` | 0.5 | 300 |
| `request_timeout_seconds` | 1 | 120 |
| `replay_messages_per_second` | 0.1 | 100 |

The editor never exposes API URLs, credentials, source paths, serial ports, or
other device-level settings. A write creates a desired revision; it does not
claim success until the agent reports the same applied revision.

## Compliance states

- `unmanaged`: no desired revision has been created.
- `unreported`: desired configuration exists but the agent has not reported.
- `pending`: desired and applied revisions differ.
- `compliant`: desired and applied revisions match and the agent reported success.
- `error`: the agent rejected the desired configuration.

## Release

Stage 23C completes RDDS `0.23.0`. The API and Web package versions are updated
from `0.22.1` to `0.23.0`. Database migrations 020 and 021 remain the only new
migrations in this release.
