# RDDS Stage 27B — Fleet Agent Release Compliance

Stage 27B connects the Stage 27A release catalog with the agent versions already
reported by sensor heartbeats. It is a read-only assessment layer. It does not
assign, download, install, or execute an agent release.

## Purpose

The fleet console now answers four operational questions:

1. What is the newest published `stable` release?
2. Which release version does each sensor report?
3. Which sensors are current, behind, ahead, on a candidate, or on a withdrawn
   release?
4. Which online sensors satisfy the minimum direct-upgrade path declared by the
   newest stable release?

The result is informational and creates no desired agent version.

## Classification

Each non-deleted sensor receives one `release_state`:

- `current` — reported version equals the latest published stable version;
- `upgrade_available` — an older version can move directly to latest stable;
- `upgrade_blocked` — reported version is below the stable release's declared
  minimum source version;
- `candidate` — a published candidate newer than stable is installed;
- `ahead` — reported version is newer than stable but is not a published
  candidate;
- `withdrawn` — the exact installed version is withdrawn in the catalog;
- `unreported` — heartbeat version is absent or not strict numeric SemVer;
- `no_stable_release` — no published stable target exists.

`update_eligible` is calculated separately from the classification. It is true
only when the reported version is within the latest stable release's declared
upgrade path and the sensor is `online` or `degraded`. A withdrawn version may
therefore remain technically eligible while still retaining its higher-risk
`withdrawn` state.

Version comparisons are numeric tuples, so `0.10.0` correctly sorts after
`0.9.0`; SQL or string ordering is never used to select the newest release.

## API

The viewer endpoint is:

```text
GET /api/v1/sensor-fleet/agent-release-compliance
```

It returns:

- catalog counts and latest published stable/candidate references;
- state and eligibility totals;
- the full assessment for every non-deleted sensor.

Only release references are returned for comparison. No artifact URL, artifact
body, credential, command, or desired-update instruction exists in the payload.

## Web UI

The **Wydania agentów** tab includes an adoption summary and per-sensor list.
Risk states are placed first. The UI explicitly labels eligibility as
informational and does not expose any update or assignment action.

## Database and agent compatibility

Stage 27B requires no migration. It reads `sensor_agent_releases` and `sensors`
through two bounded fleet inventory queries. The sensor agent, heartbeat schema,
configuration control plane, fleet readiness policy, and rollout engine are
unchanged.

The application version remains `0.26.0` until the complete Stage 27 scope is
implemented and validated.
