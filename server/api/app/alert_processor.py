import logging
import time

import psycopg

from app.alert_store import evaluate_intrusions
from app.config import settings

logging.basicConfig(
    level=getattr(logging, settings.log_level, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("rdds.alert-processor")


def main() -> None:
    logger.info(
        "Alert processor started: poll=%ss",
        settings.alert_poll_seconds,
    )

    while True:
        try:
            detected, closed = evaluate_intrusions()
            if detected or closed:
                logger.info(
                    "Alert cycle: detected_or_refreshed=%s closed=%s",
                    detected,
                    closed,
                )
        except (psycopg.Error, RuntimeError):
            logger.exception("Alert processing cycle failed")
            time.sleep(5)
            continue

        time.sleep(settings.alert_poll_seconds)


if __name__ == "__main__":
    main()
