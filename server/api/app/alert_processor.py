import logging
import time

import psycopg

from app.alert_store import evaluate_intrusions
from app.sensor_alert_store import (
    evaluate_sensor_alerts,
    evaluate_sensor_readiness_alerts,
)
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
            detected, presence_changes = evaluate_intrusions()
            sensor_alerts, sensor_alerts_closed = evaluate_sensor_alerts()
            readiness_alerts, readiness_alerts_closed = (
                evaluate_sensor_readiness_alerts()
            )
            if (
                detected
                or presence_changes
                or sensor_alerts
                or sensor_alerts_closed
                or readiness_alerts
                or readiness_alerts_closed
            ):
                logger.info(
                    "Alert cycle: detected_or_refreshed=%s presence_changes=%s "
                    "sensor_alerts=%s sensor_alerts_closed=%s "
                    "readiness_alerts=%s readiness_alerts_closed=%s",
                    detected,
                    presence_changes,
                    sensor_alerts,
                    sensor_alerts_closed,
                    readiness_alerts,
                    readiness_alerts_closed,
                )
        except (psycopg.Error, RuntimeError):
            logger.exception("Alert processing cycle failed")
            time.sleep(5)
            continue

        time.sleep(settings.alert_poll_seconds)


if __name__ == "__main__":
    main()
