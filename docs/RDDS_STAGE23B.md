# RDDS Stage 23B — Agent configuration fetch, apply and report

Stage 23B connects the Stage 23A configuration control-plane to the sensor
agent. It remains backward compatible with agents that send heartbeats without
a configuration report.

## Behavior

- The agent polls `GET /api/v1/agent/configuration` immediately after startup
  and every 30 seconds.
- Authentication reuses the individual `X-RDDS-Ingest-Token` credential.
- Only `heartbeat_seconds`, `reconnect_seconds`,
  `request_timeout_seconds`, and `replay_messages_per_second` are accepted.
- The configuration is strictly validated and applied atomically in memory.
- Invalid desired configuration never replaces the last working values.
- Every heartbeat contains the desired revision processed by the agent, the
  last successfully applied revision/configuration, and an applied/error state.
- The API ignores reports for a revision that is no longer current and ignores
  reports older than the last accepted sensor timestamp.
- Audit events are emitted only when the reported state changes, not for every
  heartbeat.

## Compatibility and safety

- The optional heartbeat field keeps protocol `rdds/1.0` compatible with older
  agents.
- Revision `0` means unmanaged: local environment values remain authoritative.
- API URL, token, sensor identity, source, baud rate, sensor position, spool
  path, and queue capacity cannot be changed remotely.
- Configuration fetch failure does not stop source reading or outbox delivery.
- Migration `021_sensor_configuration_audit_events.sql` extends the audit allow-list with configuration changed/applied/failed events.

## Scope boundary

Stage 23B does not add Web UI controls. Administrator UI and fleet compliance
presentation belong to the next Stage 23 increment. Do not publish or tag
`v0.23.0` until that release scope is complete and verified.
