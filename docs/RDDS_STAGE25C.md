# RDDS Stage 25C — Automatic Rollout Pause and Recovery

Stage 25C adds a safety state between an active and a terminal fleet
configuration rollout. The API background monitor automatically changes an
unsafe active rollout to `paused`, but it never resumes a rollout and never
deploys another batch without an administrator action.

## Pause conditions

The monitor evaluates deployed, non-rolled-back targets under the current
fleet readiness policy. It pauses an active rollout when any deployed target:

- reports a configuration application error;
- no longer owns the desired revision deployed by the rollout;
- exceeds `rollout_application_timeout_seconds` without applying the revision;
- loses operational readiness for a non-configuration reason, including
  offline/degraded health, a disallowed agent version, disconnected source,
  maintenance, or administrative disablement.

A freshly deployed configuration may temporarily be `pending`. The policy
timeout defaults to 120 seconds and is configurable from 30 to 3600 seconds.
During this grace period the pending configuration reason alone does not pause
the rollout. Other readiness failures still pause it immediately.

## Recovery contract

Paused rollouts retain the exact pause time, policy revision, and structured
blockers. They remain visible in the default non-terminal rollout list.

Recovery is deliberately manual:

1. an operator removes the blocker;
2. the detail view reports that recovery is safe;
3. an administrator submits `POST /api/v1/sensor-configuration-rollouts/{id}/resume`;
4. the rollout returns to `active` without deploying another batch;
5. advancing or completing it still requires a separate administrator action.

If a blocker is still present, resume returns structured HTTP 409 with code
`rollout_resume_blocked`, the authoritative policy revision, and the affected
sensors.

## Cancellation and rollback

A paused rollout may be cancelled. It may also be rolled back when every
deployed target still has a safe snapshot and the rollout still owns its
assignment. A direct rollback from `paused` atomically terminates the rollout
as `cancelled` before restoring snapshots with new desired revisions.

## Audit and compatibility

The immutable audit log adds:

- `sensor_configuration_rollout_paused` with the structured safety reason;
- `sensor_configuration_rollout_resumed` with the operator note and previous
  pause reason.

Migration `026_sensor_configuration_rollout_pause.sql` adds the pause metadata,
the `paused` lifecycle state, the policy timeout, and both audit event types.
The sensor agent protocol and managed configuration payload do not change.

Stage 25C closes RDDS `0.25.0`. The API and Web package versions are updated
together after the readiness gate, automatic pause, manual recovery, and
rollback workflow have all been validated end to end.
