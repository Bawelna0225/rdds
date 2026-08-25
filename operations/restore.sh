#!/bin/sh
set -eu

: "${PGHOST:?PGHOST is required}"
: "${PGDATABASE:?PGDATABASE is required}"
: "${PGUSER:?PGUSER is required}"

if [ "${RDDS_RESTORE_CONFIRM:-}" != "RESTORE_RDDS" ]; then
    echo "Restore refused: set RDDS_RESTORE_CONFIRM=RESTORE_RDDS" >&2
    exit 2
fi

backup_directory=${RDDS_BACKUP_DIRECTORY:-/backups}
restore_file=${RDDS_RESTORE_FILE:-}
filename=$(basename "$restore_file")
if [ -z "$restore_file" ] \
    || [ "$restore_file" != "$backup_directory/$filename" ] \
    || [ "${filename##*.}" != "dump" ]; then
    echo "RDDS_RESTORE_FILE must be an exact $backup_directory/*.dump path" >&2
    exit 2
fi
if [ ! -r "$restore_file" ]; then
    echo "Backup file is not readable: $restore_file" >&2
    exit 1
fi

checksum_file="$restore_file.sha256"
if [ ! -r "$checksum_file" ]; then
    echo "Checksum file is missing: $checksum_file" >&2
    exit 1
fi

(
    cd "$backup_directory"
    sha256sum -c "$filename.sha256"
)
pg_restore --list "$restore_file" >/dev/null

echo "Restoring $restore_file into database $PGDATABASE"
pg_restore \
    --clean \
    --if-exists \
    --no-owner \
    --no-privileges \
    --exit-on-error \
    --single-transaction \
    --dbname="$PGDATABASE" \
    "$restore_file"

echo "Restore completed successfully"
