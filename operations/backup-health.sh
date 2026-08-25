#!/bin/sh
set -eu

backup_directory=${RDDS_BACKUP_DIRECTORY:-/backups}
interval=${RDDS_BACKUP_INTERVAL_SECONDS:-86400}
marker="$backup_directory/.last-success"

test -r "$marker"
last_success=$(cat "$marker")
case "$last_success" in
    ''|*[!0-9]*) exit 1 ;;
esac

now=$(date -u +%s)
maximum_age=$((interval * 2 + 3600))
age=$((now - last_success))
test "$age" -ge 0
test "$age" -le "$maximum_age"
