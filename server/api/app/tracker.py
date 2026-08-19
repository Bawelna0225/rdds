import logging
import time

import psycopg

from app.config import settings
from app.track_store import process_observation_batch, update_track_states

logging.basicConfig(
    level=getattr(logging, settings.log_level, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("rdds.tracker")


def main() -> None:
    logger.info(
        "Track processor started: batch=%s stale=%ss ended=%ss",
        settings.track_batch_size,
        settings.track_stale_after_seconds,
        settings.track_ended_after_seconds,
    )

    while True:
        try:
            linked, rejected = process_observation_batch()
            state_changes = update_track_states()

            if linked or rejected or state_changes:
                logger.info(
                    "Track cycle: linked=%s rejected=%s state_changes=%s",
                    linked,
                    rejected,
                    state_changes,
                )

            if linked == settings.track_batch_size:
                continue
        except (psycopg.Error, RuntimeError):
            logger.exception("Track processing cycle failed")
            time.sleep(5)
            continue

        time.sleep(settings.track_poll_seconds)


if __name__ == "__main__":
    main()
