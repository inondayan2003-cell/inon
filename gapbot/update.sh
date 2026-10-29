#!/bin/bash
# עדכון הבוט בשרת - להריץ ב-Oracle Cloud Shell עם AK AS TT TC
set -e
: "${AK:?}" "${AS:?}" "${TT:?}" "${TC:?}"
REF="${REF:-gapbot}"
C="${OCI_TENANCY:?}"
ID=$(oci compute instance list -c "$C" --display-name gapbot --lifecycle-state RUNNING --query 'data[0].id' --raw-output)
IP=$(oci compute instance list-vnics --instance-id "$ID" --query 'data[0]."public-ip"' --raw-output)
echo "== מעדכן את השרת $IP..."
ssh -o StrictHostKeyChecking=no -i ~/.ssh/gapbot ubuntu@"$IP" "set -e
sudo curl -sL https://raw.githubusercontent.com/inondayan2003-cell/inon/$REF/gapbot/gap_alert_bot.py -o /opt/gapbot/gap_alert_bot.py
sudo sed -i 's|YOUR_ALPACA_KEY_ID|$AK|; s|YOUR_ALPACA_SECRET|$AS|; s|YOUR_TELEGRAM_BOT_TOKEN|$TT|; s|YOUR_CHAT_ID|$TC|' /opt/gapbot/gap_alert_bot.py
sudo systemctl restart gapbot
sleep 3; systemctl is-active gapbot"
echo "✅ עודכן. שלח /test לבוט בטלגרם."
