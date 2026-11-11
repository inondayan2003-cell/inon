#!/usr/bin/env bash
# Creates a new, separate free server for Nails in Oracle Cloud and installs the app on it. One command.
# Run inside Oracle Cloud Shell (the >_ icon at the top of the Oracle console):
#   bash <(curl -fsSL https://raw.githubusercontent.com/inondayan2003-cell/inon/claude/modest-pasteur-2hrgkh/nails/deploy/oracle-setup.sh)
# Touches no existing resource: everything is new and named nails-*. Running it again continues where it stopped.
set -euo pipefail

RAW="https://raw.githubusercontent.com/inondayan2003-cell/inon/claude/modest-pasteur-2hrgkh/nails"
NAME="nails-server"
KEY="$HOME/.ssh/nails_key"

say() { printf '\n\033[1;35m==> %s\033[0m\n' "$*"; }
ok()  { printf '\033[1;32m✓ %s\033[0m\n' "$*"; }
die() { printf '\n\033[1;31m✗ %s\033[0m\n' "$*" >&2; exit 1; }
trap 'printf "\n\033[1;31m✗ נעצר בשורה %s. שלח צילום מסך ל-Claude. (הרצה חוזרת ממשיכה מאיפה שנעצר)\033[0m\n" "$LINENO" >&2' ERR

command -v oci >/dev/null || die "צריך להריץ את זה בתוך Cloud Shell של Oracle"
C="${OCI_TENANCY:-}"
[ -n "$C" ] || die "לא נמצא OCI_TENANCY - צריך להריץ בתוך Cloud Shell"

q() { oci "$@" 2>/dev/null; }

# ---------- 0. does the server already exist? ----------
INST="$(q compute instance list -c "$C" --display-name "$NAME" --lifecycle-state RUNNING --query 'data[0].id' --raw-output || true)"

if [ -z "$INST" ] || [ "$INST" = "null" ]; then
  ADMIN="${NAILS_ADMIN_EMAILS:-}"
  if [ -z "$ADMIN" ]; then
    say "מי המנהל?"
    read -rp "המייל של חשבון הגוגל שאיתו תנהל את Nails: " ADMIN </dev/tty
  fi
  ADMIN="$(printf '%s' "$ADMIN" | tr -d ' \r\n')"
  [[ "$ADMIN" =~ ^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$ ]] || die "המייל לא תקין"

  # ---------- network: our own if possible, otherwise an existing one (left unchanged) ----------
  say "מכין רשת לשרת"
  ERR="$(mktemp)"
  REUSED=""
  VCN="$(q network vcn list -c "$C" --display-name nails-vcn --lifecycle-state AVAILABLE --query 'data[0].id' --raw-output || true)"
  if [ -z "$VCN" ] || [ "$VCN" = "null" ]; then
    VCN="$(oci network vcn create -c "$C" --cidr-blocks '["10.78.0.0/16"]' --display-name nails-vcn --dns-label nailsvcn \
      --wait-for-state AVAILABLE --query 'data.id' --raw-output 2>"$ERR" || true)"
  fi
  if [ -z "$VCN" ] || [ "$VCN" = "null" ]; then
    echo "Oracle לא מאפשר רשת חדשה: $(grep -oE '"message": "[^"]*"' "$ERR" | head -1)"
    say "משתמש ברשת קיימת בלי לשנות בה כלום (רק מוסיף לה שרת)"
    for V in gold-vcn ""; do
      if [ -n "$V" ]; then VCN="$(q network vcn list -c "$C" --display-name "$V" --lifecycle-state AVAILABLE --query 'data[0].id' --raw-output || true)"
      else VCN="$(q network vcn list -c "$C" --lifecycle-state AVAILABLE --query 'data[0].id' --raw-output || true)"; fi
      [ -n "$VCN" ] && [ "$VCN" != "null" ] || continue
      SUB="$(q network subnet list -c "$C" --vcn-id "$VCN" --lifecycle-state AVAILABLE --query 'data[?"prohibit-public-ip-on-vnic"==`false`] | [0].id' --raw-output || true)"
      [ -n "$SUB" ] && [ "$SUB" != "null" ] && break
    done
    [ -n "$SUB" ] && [ "$SUB" != "null" ] || die "לא נמצאה רשת ציבורית קיימת. שלח צילום מסך ל-Claude"
    REUSED=1
    VNAME="$(q network vcn get --vcn-id "$VCN" --query 'data."display-name"' --raw-output)"
    SL="$(q network vcn get --vcn-id "$VCN" --query 'data."default-security-list-id"' --raw-output)"
    PORTS="$(q network security-list get --security-list-id "$SL" --query 'data."ingress-security-rules"[]."tcp-options"."destination-port-range".min' --raw-output | tr -dc '0-9,\n ' || true)"
    OPEN443=""; echo "$PORTS" | grep -qw 443 && OPEN443=1
    ok "הרשת $VNAME"
  else
    IGW="$(q network internet-gateway list -c "$C" --vcn-id "$VCN" --query 'data[0].id' --raw-output || true)"
    if [ -z "$IGW" ] || [ "$IGW" = "null" ]; then
      IGW="$(q network internet-gateway create -c "$C" --vcn-id "$VCN" --is-enabled true --display-name nails-igw \
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

    SUB="$(q network subnet list -c "$C" --vcn-id "$VCN" --display-name nails-subnet --query 'data[0].id' --raw-output || true)"
    if [ -z "$SUB" ] || [ "$SUB" = "null" ]; then
      SUB="$(q network subnet create -c "$C" --vcn-id "$VCN" --cidr-block 10.78.0.0/24 --display-name nails-subnet \
        --dns-label nailssub --wait-for-state AVAILABLE --query 'data.id' --raw-output)"
    fi
    OPEN443=1
    ok "הרשת מוכנה"
  fi
  rm -f "$ERR"

  # ---------- SSH key (kept in Cloud Shell for later access) ----------
  mkdir -p "$HOME/.ssh"
  [ -f "$KEY" ] || ssh-keygen -q -t rsa -b 4096 -N "" -f "$KEY"

  # ---------- first-boot script: runs the regular installer on the new server ----------
  INIT="$(mktemp)"; chmod 600 "$INIT"
  cat > "$INIT" <<EOF
#!/bin/bash
export NAILS_ADMIN_EMAILS='${ADMIN}'
curl -fsSL ${RAW}/deploy/install.sh | bash > /var/log/nails-install.log 2>&1
EOF

  # ---------- create the server: free ARM (1 CPU, 6GB), else the small free AMD ----------
  say "יוצר את השרת $NAME (2-5 דקות)"
  ADS="$(q iam availability-domain list -c "$C" --query 'data[].name' --raw-output | tr -d '[]", ' | grep -v '^$')"
  ERR="$(mktemp)"
  INST=""
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
        ok "נוצר ($SHAPE)"
        break 2
      fi
      INST=""
      echo "לא הצליח: $(grep -oE '"message": "[^"]*"' "$ERR" | head -1)"
    done
  done
  rm -f "$INIT" "$ERR"
  [ -n "$INST" ] || die "Oracle לא הצליח ליצור שרת (בדרך כלל: אין מקום פנוי בחבילה החינמית). שלח צילום של ההודעות למעלה ל-Claude."
else
  ok "השרת $NAME כבר קיים - בודק את המצב שלו"
fi

IP="$(q compute instance list-vnics --instance-id "$INST" --query 'data[0]."public-ip"' --raw-output)"
DOMAIN="nails-${IP//./-}.sslip.io"
ok "כתובת השרת: $IP"

if [ -n "${REUSED:-}" ] && [ -z "${OPEN443:-}" ]; then
  printf '\n\033[1;33m! ברשת הקיימת פורטים 80/443 סגורים. צריך לפתוח אותם:\033[0m\n'
  echo "  Networking > Virtual Cloud Networks > ${VNAME:-} > Security Lists > Default > Add Ingress Rules"
  echo "  Source CIDR: 0.0.0.0/0, IP Protocol: TCP, Destination Port: 80,443"
fi

# ---------- wait for the installer on the server ----------
say "השרת מתקין את Nails לבד (בערך 5-10 דקות). אפשר להשאיר את החלון פתוח..."
for _ in $(seq 1 45); do
  if curl -fsS --max-time 8 "https://$DOMAIN/api/config" 2>/dev/null | grep -q '"firebase"'; then
    printf '\n\033[1;32m════════════════════════════════════\n  ✓ Nails באוויר!\n════════════════════════════════════\033[0m\n'
    echo "הכתובת:  https://$DOMAIN"
    echo
    echo "צעד אחרון ב-Firebase (בלי זה הכניסה עם גוגל לא תעבוד):"
    echo "  Authentication > Settings > Authorized domains > Add domain:"
    echo "      $DOMAIN"
    echo
    echo "כניסה לשרת בעתיד (מתוך Cloud Shell):  ssh -i $KEY ubuntu@$IP"
    exit 0
  fi
  printf '.'
  sleep 20
done
echo
echo "ההתקנה עדיין לא הסתיימה. הרץ את אותה פקודה שוב בעוד 10 דקות."
echo "לוג ההתקנה מהשרת:"
ssh -i "$KEY" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 "ubuntu@$IP" 'sudo tail -n 25 /var/log/nails-install.log' 2>/dev/null || true
