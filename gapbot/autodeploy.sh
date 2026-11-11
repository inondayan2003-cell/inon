#!/bin/bash
# רץ על השרת כל 5 דקות: אם בקובץ DEPLOY ב-GitHub יש גרסה חדשה - מוריד, בודק ומפעיל מחדש.
set -u
BASE="https://raw.githubusercontent.com/inondayan2003-cell/inon"
DIR=/opt/gapbot
source "$DIR/secrets.env" || exit 1
WANT=$(curl -sf "$BASE/gapbot/gapbot/DEPLOY?t=$(date +%s)" | tr -d '[:space:]')
HAVE=$(cat "$DIR/VERSION" 2>/dev/null | tr -d '[:space:]')
[[ "$WANT" =~ ^[0-9a-f]{40}$ ]] || exit 0
[ "$WANT" = "$HAVE" ] && exit 0
TMP=$(mktemp -d)
for f in gap_alert_bot.py webapp.py index.html autodeploy.sh; do
  curl -sfL "$BASE/$WANT/gapbot/$f" -o "$TMP/$f" || { echo "download failed: $f"; rm -rf "$TMP"; exit 1; }
done
python3 -m py_compile "$TMP/gap_alert_bot.py" "$TMP/webapp.py" || { echo "compile failed"; rm -rf "$TMP"; exit 1; }
sed -i "s|YOUR_ALPACA_KEY_ID|$AK|; s|YOUR_ALPACA_SECRET|$AS|; s|YOUR_TELEGRAM_BOT_TOKEN|$TT|; s|YOUR_CHAT_ID|$TC|" "$TMP/gap_alert_bot.py"
cp "$TMP/gap_alert_bot.py" "$TMP/webapp.py" "$TMP/index.html" "$DIR/"
cp "$TMP/autodeploy.sh" "$DIR/autodeploy.sh" && chmod +x "$DIR/autodeploy.sh"
echo "$WANT" > "$DIR/VERSION"
rm -rf "$TMP"
systemctl restart gapbot
echo "deployed $WANT"
