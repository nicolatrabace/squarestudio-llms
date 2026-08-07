#!/usr/bin/env bash
set -euo pipefail
STAMP=$(date +%Y%m%d-%H%M%S)
DEST=/root/backups/documenso
mkdir -p "$DEST"
docker exec documenso-db pg_dump -U documenso -d documenso | gzip > "$DEST/db-$STAMP.sql.gz"
cp -a /opt/documenso/cert.p12 "$DEST/cert-$STAMP.p12"
# keep last 14 dumps
ls -1t "$DEST"/db-*.sql.gz | tail -n +15 | xargs -r rm -f
ls -1t "$DEST"/cert-*.p12 | tail -n +5 | xargs -r rm -f
echo "Backup written to $DEST/db-$STAMP.sql.gz"
