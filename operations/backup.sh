#!/bin/sh
set -eu

umask 077

: "${PGHOST:?PGHOST is required}"
: "${PGDATABASE:?PGDATABASE is required}"
: "${PGUSER:?PGUSER is required}"

backup_directory=${RDDS_BACKUP_DIRECTORY:-/backups}
retention_days=${RDDS_BACKUP_RETENTION_DAYS:-30}

case "$PGDATABASE" in
    *[!A-Za-z0-9_.-]*)
        echo "POSTGRES_DB contains characters unsafe for a backup filename" >&2
        exit 2
        ;;
esac
case "$retention_days" in
    ''|*[!0-9]*)
        echo "RDDS_BACKUP_RETENTION_DAYS must be a positive integer" >&2
        exit 2
        ;;
esac
if [ "$retention_days" -lt 1 ]; then
    echo "RDDS_BACKUP_RETENTION_DAYS must be at least 1" >&2
    exit 2
fi

mkdir -p "$backup_directory"
if [ ! -w "$backup_directory" ]; then
    echo "Backup directory is not writable: $backup_directory" >&2
    exit 1
fi

timestamp=$(date -u +%Y%m%dT%H%M%SZ)
filename="rdds_${PGDATABASE}_${timestamp}.dump"
destination="$backup_directory/$filename"
temporary="$backup_directory/.${filename}.partial"

cleanup() {
    rm -f "$temporary" "$temporary.sha256"
}
trap cleanup EXIT HUP INT TERM

if [ -e "$destination" ]; then
    echo "Backup destination already exists: $destination" >&2
    exit 1
fi

echo "Creating PostgreSQL backup: $destination"
pg_dump \
    --format=custom \
    --compress=6 \
    --no-owner \
    --no-privileges \
    --file="$temporary"

pg_restore --list "$temporary" >/dev/null
mv "$temporary" "$destination"

(
    cd "$backup_directory"
    sha256sum "$filename" >"$filename.sha256"
)

date -u +%s >"$backup_directory/.last-success"

find "$backup_directory" \
    -maxdepth 1 \
    -type f \
    -name 'rdds_*.dump' \
    -mtime "+$retention_days" \
    -print | while IFS= read -r expired; do
        echo "Removing expired backup: $expired"
        rm -f "$expired" "$expired.sha256"
    done

trap - EXIT HUP INT TERM
echo "Backup completed and verified: $destination"
