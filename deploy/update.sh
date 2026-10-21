#!/usr/bin/env bash
# עדכון אוטומטי: אם יש קוד חדש ב-GitHub, מושכים ובונים מחדש. רץ מ-gold-update.timer.
set -euo pipefail
cd /opt/gold-analyzer
branch="$(git rev-parse --abbrev-ref HEAD)"
git fetch -q origin "$branch"
[ "$(git rev-parse HEAD)" = "$(git rev-parse FETCH_HEAD)" ] && exit 0
git reset -q --hard FETCH_HEAD
docker compose up -d --build
docker image prune -f >/dev/null
echo "עודכן לגרסה $(git rev-parse --short HEAD)"
