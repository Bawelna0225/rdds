#!/bin/sh
set -eu

test_root=$(mktemp -d)
trap 'rm -rf "$test_root"' EXIT HUP INT TERM

fake_bin="$test_root/bin"
backup_directory="$test_root/backups"
mkdir -p "$fake_bin" "$backup_directory"

cat >"$fake_bin/pg_dump" <<'EOF'
#!/bin/sh
set -eu
destination=
for argument in "$@"; do
    case "$argument" in
        --file=*) destination=${argument#--file=} ;;
    esac
done
test -n "$destination"
printf 'fake-postgresql-custom-archive\n' >"$destination"
EOF

cat >"$fake_bin/pg_restore" <<'EOF'
#!/bin/sh
set -eu
if [ "${1:-}" = "--list" ]; then
    test -r "$2"
    exit 0
fi
test -n "${FAKE_RESTORE_LOG:-}"
printf '%s\n' "$*" >"$FAKE_RESTORE_LOG"
EOF

chmod 0700 "$fake_bin/pg_dump" "$fake_bin/pg_restore"

export PATH="$fake_bin:$PATH"
export PGHOST=database
export PGDATABASE=rdds
export PGUSER=rdds
export RDDS_BACKUP_DIRECTORY="$backup_directory"
export RDDS_BACKUP_RETENTION_DAYS=30

sh operations/backup.sh >/dev/null
backup_file=$(find "$backup_directory" -maxdepth 1 -name 'rdds_*.dump' -type f)
test -n "$backup_file"
test -r "$backup_file.sha256"
(
    cd "$backup_directory"
    sha256sum -c "$(basename "$backup_file").sha256" >/dev/null
)
RDDS_BACKUP_INTERVAL_SECONDS=86400 sh operations/backup-health.sh

if RDDS_RESTORE_CONFIRM=RESTORE_RDDS \
    RDDS_RESTORE_FILE="$backup_directory/../forbidden.dump" \
    sh operations/restore.sh >/dev/null 2>&1; then
    echo "Restore accepted a path outside /backups" >&2
    exit 1
fi

export FAKE_RESTORE_LOG="$test_root/restore.log"
RDDS_RESTORE_CONFIRM=RESTORE_RDDS \
RDDS_RESTORE_FILE="$backup_directory/$(basename "$backup_file")" \
sh operations/restore.sh >/dev/null
test -s "$FAKE_RESTORE_LOG"

echo "operations tests: ok"
