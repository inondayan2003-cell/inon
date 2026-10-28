#!/bin/bash
# Gap Alert Bot - הקמה אוטומטית מתוך Oracle Cloud Shell
# יוצר שרת חינמי חדש, מתקין את הבוט ומפעיל אותו כשירות.
set -e
RAW="https://raw.githubusercontent.com/inondayan2003-cell/inon/gapbot/gapbot"
C="${OCI_TENANCY:?OCI_TENANCY missing - run this inside Oracle Cloud Shell}"

read -p "Alpaca Key ID: " AK </dev/tty
read -p "Alpaca Secret: " AS </dev/tty
read -p "Telegram Bot Token: " TT </dev/tty
read -p "Telegram Chat ID: " TC </dev/tty

echo "== בודק מפתחות..."
curl -sf -H "APCA-API-KEY-ID: $AK" -H "APCA-API-SECRET-KEY: $AS" \
  "https://data.alpaca.markets/v1beta1/screener/stocks/movers?top=5" >/dev/null \
  && echo "Alpaca ✅" || { echo "❌ מפתחות Alpaca לא תקינים"; exit 1; }
curl -sf "https://api.telegram.org/bot$TT/sendMessage" -d chat_id="$TC" \
  -d text="🔧 מתחיל להקים את השרת..." >/dev/null \
  && echo "Telegram ✅" || { echo "❌ Token או Chat ID לא תקינים"; exit 1; }

echo "== רשת..."
SUB=$(oci network subnet list -c "$C" --all \
  --query 'data[?"prohibit-public-ip-on-vnic"==`false` && "lifecycle-state"==`AVAILABLE`].id | [0]' --raw-output 2>/dev/null || true)
if [ -z "$SUB" ] || [ "$SUB" = "null" ]; then
  VCN=$(oci network vcn create -c "$C" --cidr-block 10.0.0.0/16 --display-name gapbot-vcn \
        --wait-for-state AVAILABLE --query data.id --raw-output)
  IG=$(oci network internet-gateway create -c "$C" --vcn-id "$VCN" --is-enabled true \
        --display-name gapbot-ig --wait-for-state AVAILABLE --query data.id --raw-output)
  RT=$(oci network vcn get --vcn-id "$VCN" --query 'data."default-route-table-id"' --raw-output)
  oci network route-table update --rt-id "$RT" --force \
    --route-rules "[{\"destination\":\"0.0.0.0/0\",\"destinationType\":\"CIDR_BLOCK\",\"networkEntityId\":\"$IG\"}]" >/dev/null
  SUB=$(oci network subnet create -c "$C" --vcn-id "$VCN" --cidr-block 10.0.0.0/24 \
        --display-name gapbot-subnet --wait-for-state AVAILABLE --query data.id --raw-output)
fi
echo "subnet ok"

# סקריפט שירוץ בעליית השרת
cat > /tmp/gapbot-ud.sh <<UD
#!/bin/bash
apt-get update -y && apt-get install -y python3-requests curl
mkdir -p /opt/gapbot && cd /opt/gapbot
curl -sL "$RAW/gap_alert_bot.py" -o gap_alert_bot.py
sed -i "s|YOUR_ALPACA_KEY_ID|$AK|; s|YOUR_ALPACA_SECRET|$AS|; s|YOUR_TELEGRAM_BOT_TOKEN|$TT|; s|YOUR_CHAT_ID|$TC|" gap_alert_bot.py
cat > /etc/systemd/system/gapbot.service <<SVC
[Unit]
Description=Gap Alert Bot
After=network-online.target
[Service]
WorkingDirectory=/opt/gapbot
ExecStart=/usr/bin/python3 -u /opt/gapbot/gap_alert_bot.py
Restart=always
RestartSec=10
[Install]
WantedBy=multi-user.target
SVC
systemctl daemon-reload
systemctl enable --now gapbot
UD

[ -f ~/.ssh/gapbot ] || ssh-keygen -q -t ed25519 -N "" -f ~/.ssh/gapbot
AD=$(oci iam availability-domain list -c "$C" --query 'data[0].name' --raw-output)

launch() { # $1 shape, $2 extra args
  IMG=$(oci compute image list -c "$C" --operating-system "Canonical Ubuntu" \
        --operating-system-version "22.04" --shape "$1" --sort-by TIMECREATED \
        --query 'data[0].id' --raw-output)
  oci compute instance launch -c "$C" --availability-domain "$AD" --shape "$1" $2 \
    --image-id "$IMG" --subnet-id "$SUB" --assign-public-ip true --display-name gapbot \
    --user-data-file /tmp/gapbot-ud.sh --ssh-authorized-keys-file ~/.ssh/gapbot.pub \
    --wait-for-state RUNNING --query 'data.id' --raw-output
}

echo "== יוצר שרת (2-3 דקות)..."
ID=$(launch VM.Standard.E2.1.Micro "" 2>/tmp/gapbot-err) || \
ID=$(launch VM.Standard.A1.Flex "--shape-config {\"ocpus\":1,\"memoryInGBs\":6}" 2>>/tmp/gapbot-err) || \
{ echo "❌ לא הצלחתי ליצור שרת:"; tail -5 /tmp/gapbot-err; exit 1; }

IP=$(oci compute instance list-vnics --instance-id "$ID" --query 'data[0]."public-ip"' --raw-output)
echo ""
echo "✅ השרת עלה: $IP"
echo "בעוד 3-5 דקות תגיע הודעה בטלגרם: '✅ הבוט פועל'"
echo "כניסה לשרת בעתיד מכאן:  ssh -i ~/.ssh/gapbot ubuntu@$IP"
