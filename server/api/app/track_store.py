from typing import Any
from uuid import UUID

from app.config import settings
from app.database import connection
from app.track_identity import resolve_track_identity


def process_observation_batch(limit: int | None = None) -> tuple[int, int]:
    batch_limit = limit or settings.track_batch_size
    linked = 0
    rejected = 0

    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                o.id,
                o.sensor_id,
                o.sensor_boot_id,
                o.message_time,
                o.received_at,
                o.drone_mac,
                o.basic_id,
                o.operator_id,
                o.session_id,
                ST_Y(o.drone_position::geometry) AS drone_latitude,
                ST_X(o.drone_position::geometry) AS drone_longitude,
                ST_Y(o.pilot_position::geometry) AS pilot_latitude,
                ST_X(o.pilot_position::geometry) AS pilot_longitude,
                o.altitude_m,
                o.speed_mps,
                o.heading_deg
            FROM observations o
            WHERE o.processed_at IS NULL
            ORDER BY o.received_at, o.id
            LIMIT %s
            FOR UPDATE OF o SKIP LOCKED
            """,
            (batch_limit,),
        )
        observations = cursor.fetchall()

        for observation in observations:
            identity = resolve_track_identity(observation)
            if identity is None:
                cursor.execute(
                    """
                    UPDATE observations
                    SET
                        processed_at = NOW(),
                        processing_error = 'insufficient_identity'
                    WHERE id = %s
                    """,
                    (observation["id"],),
                )
                rejected += 1
                continue

            cursor.execute(
                """
                INSERT INTO tracks (
                    track_key,
                    identity_key,
                    identity_type,
                    state,
                    last_position,
                    last_pilot_position,
                    last_altitude_m,
                    last_speed_mps,
                    last_heading_deg,
                    last_operator_id,
                    last_basic_id,
                    last_drone_mac,
                    first_seen_at,
                    last_seen_at,
                    observation_count,
                    last_observation_id
                )
                VALUES (
                    %(track_key)s,
                    %(identity_key)s,
                    %(identity_type)s,
                    'new',
                    CASE
                        WHEN CAST(%(drone_longitude)s AS DOUBLE PRECISION) IS NULL
                          OR CAST(%(drone_latitude)s AS DOUBLE PRECISION) IS NULL
                        THEN NULL
                        ELSE ST_SetSRID(
                            ST_MakePoint(
                                CAST(%(drone_longitude)s AS DOUBLE PRECISION),
                                CAST(%(drone_latitude)s AS DOUBLE PRECISION)
                            ),
                            4326
                        )::geography
                    END,
                    CASE
                        WHEN CAST(%(pilot_longitude)s AS DOUBLE PRECISION) IS NULL
                          OR CAST(%(pilot_latitude)s AS DOUBLE PRECISION) IS NULL
                        THEN NULL
                        ELSE ST_SetSRID(
                            ST_MakePoint(
                                CAST(%(pilot_longitude)s AS DOUBLE PRECISION),
                                CAST(%(pilot_latitude)s AS DOUBLE PRECISION)
                            ),
                            4326
                        )::geography
                    END,
                    %(altitude_m)s,
                    %(speed_mps)s,
                    %(heading_deg)s,
                    %(operator_id)s,
                    %(basic_id)s,
                    %(drone_mac)s,
                    %(message_time)s,
                    %(message_time)s,
                    1,
                    %(observation_id)s
                )
                ON CONFLICT (track_key) DO UPDATE SET
                    identity_key = EXCLUDED.identity_key,
                    identity_type = EXCLUDED.identity_type,
                    state = CASE
                        WHEN tracks.state IN ('anomalous', 'no_gps')
                            THEN tracks.state
                        WHEN tracks.observation_count + 1 >= 2
                            THEN 'active'
                        ELSE 'new'
                    END,
                    last_position = CASE
                        WHEN EXCLUDED.last_seen_at >= tracks.last_seen_at
                            THEN COALESCE(
                                EXCLUDED.last_position,
                                tracks.last_position
                            )
                        ELSE tracks.last_position
                    END,
                    last_pilot_position = CASE
                        WHEN EXCLUDED.last_seen_at >= tracks.last_seen_at
                            THEN COALESCE(
                                EXCLUDED.last_pilot_position,
                                tracks.last_pilot_position
                            )
                        ELSE tracks.last_pilot_position
                    END,
                    last_altitude_m = CASE
                        WHEN EXCLUDED.last_seen_at >= tracks.last_seen_at
                            THEN COALESCE(
                                EXCLUDED.last_altitude_m,
                                tracks.last_altitude_m
                            )
                        ELSE tracks.last_altitude_m
                    END,
                    last_speed_mps = CASE
                        WHEN EXCLUDED.last_seen_at >= tracks.last_seen_at
                            THEN COALESCE(
                                EXCLUDED.last_speed_mps,
                                tracks.last_speed_mps
                            )
                        ELSE tracks.last_speed_mps
                    END,
                    last_heading_deg = CASE
                        WHEN EXCLUDED.last_seen_at >= tracks.last_seen_at
                            THEN COALESCE(
                                EXCLUDED.last_heading_deg,
                                tracks.last_heading_deg
                            )
                        ELSE tracks.last_heading_deg
                    END,
                    last_operator_id = CASE
                        WHEN EXCLUDED.last_seen_at >= tracks.last_seen_at
                            THEN COALESCE(
                                EXCLUDED.last_operator_id,
                                tracks.last_operator_id
                            )
                        ELSE tracks.last_operator_id
                    END,
                    last_basic_id = CASE
                        WHEN EXCLUDED.last_seen_at >= tracks.last_seen_at
                            THEN COALESCE(
                                EXCLUDED.last_basic_id,
                                tracks.last_basic_id
                            )
                        ELSE tracks.last_basic_id
                    END,
                    last_drone_mac = CASE
                        WHEN EXCLUDED.last_seen_at >= tracks.last_seen_at
                            THEN COALESCE(
                                EXCLUDED.last_drone_mac,
                                tracks.last_drone_mac
                            )
                        ELSE tracks.last_drone_mac
                    END,
                    first_seen_at = LEAST(
                        tracks.first_seen_at,
                        EXCLUDED.first_seen_at
                    ),
                    last_seen_at = GREATEST(
                        tracks.last_seen_at,
                        EXCLUDED.last_seen_at
                    ),
                    ended_at = NULL,
                    observation_count = tracks.observation_count + 1,
                    last_observation_id = CASE
                        WHEN EXCLUDED.last_seen_at >= tracks.last_seen_at
                            THEN EXCLUDED.last_observation_id
                        ELSE tracks.last_observation_id
                    END,
                    updated_at = NOW()
                RETURNING id
                """,
                {
                    "track_key": identity.track_key,
                    "identity_key": identity.identity_value,
                    "identity_type": identity.identity_type,
                    "drone_longitude": observation["drone_longitude"],
                    "drone_latitude": observation["drone_latitude"],
                    "pilot_longitude": observation["pilot_longitude"],
                    "pilot_latitude": observation["pilot_latitude"],
                    "altitude_m": observation["altitude_m"],
                    "speed_mps": observation["speed_mps"],
                    "heading_deg": observation["heading_deg"],
                    "operator_id": observation["operator_id"],
                    "basic_id": observation["basic_id"],
                    "drone_mac": observation["drone_mac"],
                    "message_time": observation["message_time"],
                    "observation_id": observation["id"],
                },
            )
            track = cursor.fetchone()
            if track is None:
                raise RuntimeError("Track upsert returned no row")

            cursor.execute(
                """
                INSERT INTO track_observations (observation_id, track_id)
                VALUES (%s, %s)
                ON CONFLICT (observation_id) DO NOTHING
                """,
                (observation["id"], track["id"]),
            )
            cursor.execute(
                """
                UPDATE observations
                SET processed_at = NOW(), processing_error = NULL
                WHERE id = %s
                """,
                (observation["id"],),
            )
            linked += 1

    return linked, rejected


def update_track_states() -> int:
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            WITH desired AS (
                SELECT
                    id,
                    CASE
                        WHEN last_seen_at < NOW() - (%(ended)s * INTERVAL '1 second')
                            THEN 'ended'
                        WHEN last_seen_at < NOW() - (%(stale)s * INTERVAL '1 second')
                            THEN 'stale'
                        WHEN observation_count >= 2
                            THEN 'active'
                        ELSE 'new'
                    END AS desired_state
                FROM tracks
                WHERE state NOT IN ('anomalous', 'no_gps')
            )
            UPDATE tracks AS track
            SET
                state = desired.desired_state,
                ended_at = CASE
                    WHEN desired.desired_state = 'ended'
                        THEN COALESCE(track.ended_at, NOW())
                    ELSE NULL
                END,
                updated_at = NOW()
            FROM desired
            WHERE track.id = desired.id
              AND track.state IS DISTINCT FROM desired.desired_state
            """,
            {
                "stale": settings.track_stale_after_seconds,
                "ended": settings.track_ended_after_seconds,
            },
        )
        return cursor.rowcount


def list_tracks(include_ended: bool = False) -> list[dict[str, Any]]:
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                track.id,
                track.track_key,
                track.identity_type,
                track.identity_key,
                track.state,
                track.last_basic_id AS basic_id,
                track.last_operator_id AS operator_id,
                track.last_drone_mac AS drone_mac,
                ST_Y(track.last_position::geometry) AS latitude,
                ST_X(track.last_position::geometry) AS longitude,
                ST_Y(track.last_pilot_position::geometry) AS pilot_latitude,
                ST_X(track.last_pilot_position::geometry) AS pilot_longitude,
                track.last_altitude_m AS altitude_m,
                track.last_speed_mps AS speed_mps,
                track.last_heading_deg AS heading_deg,
                track.first_seen_at,
                track.last_seen_at,
                track.ended_at,
                track.observation_count,
                COUNT(DISTINCT observation.sensor_id) AS contributing_sensors
            FROM tracks AS track
            LEFT JOIN track_observations AS link
                ON link.track_id = track.id
            LEFT JOIN observations AS observation
                ON observation.id = link.observation_id
            WHERE (%s OR track.state <> 'ended')
            GROUP BY track.id
            ORDER BY track.last_seen_at DESC
            """,
            (include_ended,),
        )
        return [dict(row) for row in cursor.fetchall()]


def get_track_history(track_id: UUID, limit: int) -> list[dict[str, Any]]:
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT *
            FROM (
                SELECT
                    observation.id AS observation_id,
                    sensor.sensor_key AS sensor_id,
                    observation.message_time,
                    observation.received_at,
                    observation.transport,
                    observation.channel,
                    observation.rssi,
                    ST_Y(observation.drone_position::geometry) AS latitude,
                    ST_X(observation.drone_position::geometry) AS longitude,
                    observation.altitude_m,
                    observation.speed_mps,
                    observation.heading_deg
                FROM track_observations AS link
                JOIN observations AS observation
                    ON observation.id = link.observation_id
                JOIN sensors AS sensor
                    ON sensor.id = observation.sensor_id
                WHERE link.track_id = %s
                ORDER BY observation.message_time DESC, observation.id DESC
                LIMIT %s
            ) AS recent
            ORDER BY recent.message_time, recent.observation_id
            """,
            (track_id, limit),
        )
        return [dict(row) for row in cursor.fetchall()]
