FROM postgis/postgis:16-3.5-alpine

COPY backup.sh backup-loop.sh backup-health.sh restore.sh /usr/local/bin/

RUN chmod 0555 \
        /usr/local/bin/backup.sh \
        /usr/local/bin/backup-loop.sh \
        /usr/local/bin/backup-health.sh \
        /usr/local/bin/restore.sh

ENV HOME=/tmp

ENTRYPOINT ["/usr/local/bin/backup-loop.sh"]
