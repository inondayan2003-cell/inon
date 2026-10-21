#!/usr/bin/env bash
# יוצר ב-Oracle Cloud שרת חדש ונפרד לבוט הזהב - רשת, פורטים, שרת והתקנה - בפקודה אחת.
# מריצים מתוך Cloud Shell (האייקון >_ למעלה בקונסולה של Oracle):
#   bash <(curl -fsSL https://raw.githubusercontent.com/inondayan2003-cell/inon/claude/telegram-stocks-gold-analyzer-akepc8/deploy/oracle-setup.sh)
# לא נוגע בשום משאב קיים: הכל נוצר חדש עם השמות gold-*. הרצה חוזרת ממשיכה מאיפה שנעצרה.
set -euo pipefail

RAW="https://raw.githubusercontent.com/inondayan2003-cell/inon/claude/telegram-stocks-gold-analyzer-akepc8"
NAME="gold-bot"
KEY="$HOME/.ssh/gold_bot_key"

say() { printf '\n\033[1;33m==> %s\033[0m\n' "$*"; }
ok()  { printf '\033[1;32m✓ %s\033[0m\n' "$*"; }
die() { printf '\n\033[1;31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

command -v oci >/dev/null || die "צריך להריץ את זה בתוך Cloud Shell של Oracle"
C="${OCI_TENANCY:-}"
[ -n "$C" ] || die "לא נמצא OCI_TENANCY - צריך להריץ בתוך Cloud Shell"

q() { oci "$@" 2>/dev/null; }  # שקט, להחזרת ערכים

# ---------- שלב 0: האם השרת כבר קיים? ----------
INST="$(q compute instance list -c "$C" --display-name "$NAME" --lifecycle-state RUNNING --query 'data[0].id' --raw-output || true)"

if [ -z "$INST" ] || [ "$INST" = "null" ]; then
  # אפשר להעביר מראש בשורת הפקודה:  BOT_TOKEN=... TWELVEDATA_API_KEY=... bash <(curl ...)
  BOT_TOKEN="${BOT_TOKEN:-}"
  TD_KEY="${TWELVEDATA_API_KEY:-}"
  if [ -z "$BOT_TOKEN" ]; then
    say "טוקנים (ההקלדה מוסתרת - הדבק ולחץ Enter)"
    read -rsp "הטוקן מ-BotFather: " BOT_TOKEN </dev/tty; echo
    read -rsp "המפתח מ-Twelve Data: " TD_KEY </dev/tty; echo
  fi
  # גם אם הודבקה בטעות שורה שלמה - שולפים ממנה רק את הטוקן ואת המפתח
  ALL="$BOT_TOKEN $TD_KEY"
  BOT_TOKEN="$(grep -oE '[0-9]{6,}:[A-Za-z0-9_-]{30,}' <<<"$ALL" | head -1 || true)"
  TD_KEY="$(grep -oE 'TWELVEDATA_API_KEY=[0-9a-f]{32}' <<<"$ALL" | cut -d= -f2 | head -1 || true)"
  [ -n "$TD_KEY" ] || TD_KEY="$(grep -oE '(^| )[0-9a-f]{32}( |$)' <<<"$ALL" | tr -d ' ' | head -1 || true)"
  [[ "$BOT_TOKEN" == *:* ]] || die "הטוקן לא נראה תקין (צריך להיות בפורמט 123456:ABC...)"

  # ---------- רשת נפרדת ----------
  say "יוצר רשת נפרדת (gold-vcn) - הרשת של השרת הקיים לא משתנה"
  VCN="$(q network vcn list -c "$C" --display-name gold-vcn --lifecycle-state AVAILABLE --query 'data[0].id' --raw-output || true)"
  if [ -z "$VCN" ] || [ "$VCN" = "null" ]; then
    VCN="$(q network vcn create -c "$C" --cidr-blocks '["10.77.0.0/16"]' --display-name gold-vcn --dns-label goldvcn \
      --wait-for-state AVAILABLE --query 'data.id' --raw-output)"
  fi
  [ -n "$VCN" ] || die "יצירת הרשת נכשלה"

  IGW="$(q network internet-gateway list -c "$C" --vcn-id "$VCN" --query 'data[0].id' --raw-output || true)"
  if [ -z "$IGW" ] || [ "$IGW" = "null" ]; then
    IGW="$(q network internet-gateway create -c "$C" --vcn-id "$VCN" --is-enabled true --display-name gold-igw \
      --wait-for-state AVAILABLE --query 'data.id' --raw-output)"
  fi

  RT="$(q network vcn get --vcn-id "$VCN" --query 'data."default-route-table-id"' --raw-output)"
  oci network route-table update --rt-id "$RT" --force --route-rules \
    "[{\"destination\":\"0.0.0.0/0\",\"destinationType\":\"CIDR_BLOCK\",\"networkEntityId\":\"$IGW\"}]" >/dev/null

  say "פותח פורטים 22, 80, 443 ברשת החדשה בלבד"
  SL="$(q network vcn get --vcn-id "$VCN" --query 'data."default-security-list-id"' --raw-output)"
  rule() { printf '{"source":"0.0.0.0/0","protocol":"6","tcpOptions":{"destinationPortRange":{"min":%s,"max":%s}}}' "$1" "$1"; }
  oci network security-list update --security-list-id "$SL" --force \
    --ingress-security-rules "[$(rule 22),$(rule 80),$(rule 443),{\"source\":\"0.0.0.0/0\",\"protocol\":\"1\",\"icmpOptions\":{\"type\":3,\"code\":4}}]" \
    --egress-security-rules '[{"destination":"0.0.0.0/0","protocol":"all"}]' >/dev/null

  SUB="$(q network subnet list -c "$C" --vcn-id "$VCN" --display-name gold-subnet --query 'data[0].id' --raw-output || true)"
  if [ -z "$SUB" ] || [ "$SUB" = "null" ]; then
    SUB="$(q network subnet create -c "$C" --vcn-id "$VCN" --cidr-block 10.77.0.0/24 --display-name gold-subnet \
      --dns-label goldsub --wait-for-state AVAILABLE --query 'data.id' --raw-output)"
  fi
  ok "הרשת מוכנה"

  # ---------- מפתח SSH (נשמר ב-Cloud Shell, לגישה עתידית) ----------
  [ -f "$KEY" ] || ssh-keygen -q -t ed25519 -N "" -f "$KEY"

  # ---------- סקריפט ההתקנה שירוץ בשרת בעלייה הראשונה ----------
  INIT="$(mktemp)"
  chmod 600 "$INIT"
  cat > "$INIT" <<EOF
#!/bin/bash
export BOT_TOKEN='${BOT_TOKEN}'
export TWELVEDATA_API_KEY='${TD_KEY}'
curl -fsSL ${RAW}/deploy/install.sh | bash > /var/log/gold-install.log 2>&1
EOF

  # ---------- יצירת השרת: מנסה ARM חינמי ואם אין מקום - AMD חינמי ----------
  say "יוצר את השרת $NAME (2-5 דקות)"
  ADS="$(q iam availability-domain list -c "$C" --query 'data[].name' --raw-output | tr -d '[]", ' | grep -v '^$')"
  ERR="$(mktemp)"
  for SHAPE in VM.Standard.A1.Flex VM.Standard.E2.1.Micro; do
    IMG="$(q compute image list -c "$C" --operating-system "Canonical Ubuntu" --operating-system-version "24.04" \
      --shape "$SHAPE" --sort-by TIMECREATED --sort-order DESC --limit 1 --query 'data[0].id' --raw-output || true)"
    [ -n "$IMG" ] && [ "$IMG" != "null" ] || continue
    CFG=()
    [ "$SHAPE" = VM.Standard.A1.Flex ] && CFG=(--shape-config '{"ocpus":1,"memoryInGBs":6}')
    for AD in $ADS; do
      printf 'מנסה %s ב-%s... ' "$SHAPE" "$AD"
      if INST="$(oci compute instance launch -c "$C" --availability-domain "$AD" --shape "$SHAPE" "${CFG[@]}" \
          --image-id "$IMG" --subnet-id "$SUB" --assign-public-ip true --display-name "$NAME" \
          --ssh-authorized-keys-file "$KEY.pub" --user-data-file "$INIT" \
          --wait-for-state RUNNING --max-wait-seconds 900 --query 'data.id' --raw-output 2>"$ERR")"; then
        ok "נוצר"
        break 2
      fi
      INST=""
      echo "לא הצליח: $(grep -oE '"message": "[^"]*"' "$ERR" | head -1)"
    done
  done
  rm -f "$INIT"
  [ -n "$INST" ] || die "Oracle לא הצליח ליצור שרת (בדרך כלל: אין מקום פנוי בחבילה החינמית). שלח צילום של ההודעות למעלה ל-Claude."
else
  ok "השרת $NAME כבר קיים - בודק את המצב שלו"
fi

IP="$(q compute instance list-vnics --instance-id "$INST" --query 'data[0]."public-ip"' --raw-output)"
DOMAIN="${IP//./-}.sslip.io"
ok "כתובת השרת: $IP"

# ---------- מחכים שההתקנה בשרת תסתיים ----------
say "השרת מתקין את הבוט לבד (בערך 5-15 דקות). אפשר להשאיר את החלון פתוח..."
for i in $(seq 1 60); do
  if curl -fsS --max-time 8 "https://$DOMAIN/health" 2>/dev/null | grep -q '"ok":true'; then
    printf '\n\033[1;32m════════════════════════════════════\n  ✓ הבוט רץ!\n════════════════════════════════════\033[0m\n'
    echo "האפליקציה: https://$DOMAIN"
    echo "עכשיו פתח את הבוט שלך בטלגרם ושלח /start"
    exit 0
  fi
  printf '.'
  sleep 20
done
echo
echo "ההתקנה עדיין לא הסתיימה. זה תקין אם השרת קטן - הרץ את אותה פקודה שוב בעוד 10 דקות."
echo "לוג ההתקנה מהשרת:"
ssh -i "$KEY" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 "ubuntu@$IP" 'sudo tail -n 25 /var/log/gold-install.log' 2>/dev/null || true
