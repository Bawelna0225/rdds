#!/bin/sh
set -eu

interval=${RDDS_BACKUP_INTERVAL_SECONDS:-86400}
case "$interval" in
    ''|*[!0-9]*)
        echo "RDDS_BACKUP_INTERVAL_SECONDS must be a positive integer" >&2
        exit 2
        ;;
esac
if [ "$interval" -lt 300 ]; then
    echo "RDDS_BACKUP_INTERVAL_SECONDS must be at least 300" >&2
    exit 2
fi

while true; do
    /usr/local/bin/backup.sh
    sleep "$interval"
done
