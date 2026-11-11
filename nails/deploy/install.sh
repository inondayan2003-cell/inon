#!/usr/bin/env bash
# Installs (or updates) Nails on an existing server, in its own folder: /opt/nails.
# Does not touch anything else on the server: own user, own folder, own service, own port.
# Run on the server (Ubuntu or Oracle Linux):
#   curl -fsSL https://raw.githubusercontent.com/inondayan2003-cell/inon/claude/modest-pasteur-2hrgkh/nails/deploy/install.sh | sudo bash
# Running it again updates the app to the latest version. Data and settings are kept.
set -euo pipefail

REPO="https://github.com/inondayan2003-cell/inon.git"
BRANCH="claude/modest-pasteur-2hrgkh"
BASE="/opt/nails"          # repo checkout lives here; the app is in $BASE/nails
APP="$BASE/nails"
VENV="$BASE/venv"

say() { printf '\n\033[1;35m==> %s\033[0m\n' "$*"; }
ok()  { printf '\033[1;32m✓ %s\033[0m\n' "$*"; }
die() { printf '\n\033[1;31m✗ %s\033[0m\n' "$*" >&2; exit 1; }
trap 'printf "\n\033[1;31m✗ נעצר בשורה %s. שלח צילום מסך ל-Claude. הרצה חוזרת ממשיכה בבטחה.\033[0m\n" "$LINENO" >&2' ERR

[ "$(id -u)" = 0 ] || die "צריך להריץ עם sudo"

if command -v apt-get >/dev/null; then PM=apt
elif command -v dnf >/dev/null; then PM=dnf
else die "מערכת הפעלה לא מוכרת (צריך Ubuntu או Oracle Linux)"; fi

# ---------- 1. packages ----------
say "מתקין חבילות בסיס (git, python)"
if [ "$PM" = apt ]; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get -o DPkg::Lock::Timeout=600 update -qq
  apt-get -o DPkg::Lock::Timeout=600 install -y -qq git curl python3 python3-venv python3-pip ca-certificates >/dev/null
else
  dnf install -y -q git curl python3 python3-pip ca-certificates >/dev/null
fi
python3 -c 'import sys; assert sys.version_info >= (3, 10)' || die "צריך Python 3.10 ומעלה"
ok "חבילות בסיס"

# ---------- 2. web server (Caddy: HTTPS automatically) ----------
listening() { ss -ltnH "( sport = :$1 )" 2>/dev/null | grep -q .; }
if ! command -v caddy >/dev/null; then
  for p in 80 443; do
    if listening "$p"; then
      die "משהו אחר כבר משתמש בפורט $p בשרת הזה (למשל nginx). שלח ל-Claude את הפלט של: sudo ss -ltnp"
    fi
  done
  say "מתקין Caddy (שרת אינטרנט עם HTTPS אוטומטי)"
  if [ "$PM" = apt ]; then
    apt-get -o DPkg::Lock::Timeout=600 install -y -qq debian-keyring debian-archive-keyring apt-transport-https gnupg >/dev/null
    curl -fsSL 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -fsSL 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
    apt-get -o DPkg::Lock::Timeout=600 update -qq && apt-get -o DPkg::Lock::Timeout=600 install -y -qq caddy >/dev/null
  else
    dnf install -y -q 'dnf-command(copr)' >/dev/null && dnf copr enable -y @caddy/caddy >/dev/null && dnf install -y -q caddy >/dev/null
  fi
  systemctl enable --now caddy >/dev/null
fi
ok "Caddy"

# ---------- 3. app files ----------
say "מוריד את Nails לתיקייה $BASE"
id nails >/dev/null 2>&1 || useradd --system --home-dir "$BASE" --shell /usr/sbin/nologin nails
if [ -d "$BASE/.git" ]; then
  git -C "$BASE" fetch -q origin "$BRANCH"
  git -C "$BASE" checkout -q -B "$BRANCH" "origin/$BRANCH"
  git -C "$BASE" reset -q --hard "origin/$BRANCH"     # code only; data/ and .env are not in git
else
  [ -e "$BASE" ] && [ -n "$(ls -A "$BASE" 2>/dev/null)" ] && die "התיקייה $BASE כבר קיימת ואינה ריקה"
  git clone -q --depth 1 --branch "$BRANCH" "$REPO" "$BASE"
fi
mkdir -p "$APP/data"
chown -R nails:nails "$APP/data"
chmod 750 "$APP/data"
ok "הקבצים ב-$APP"

say "מתקין את החבילות של Python (דקה-שתיים)"
[ -x "$VENV/bin/python" ] || python3 -m venv "$VENV"
"$VENV/bin/pip" install -q --upgrade pip
"$VENV/bin/pip" install -q -r "$APP/requirements.txt"
ok "סביבת Python"

# ---------- 4. settings (.env, kept between runs) ----------
ENV="$APP/.env"
if [ ! -f "$ENV" ]; then
  say "הגדרות"
  ADMIN="${NAILS_ADMIN_EMAILS:-}"
  if [ -z "$ADMIN" ]; then
    read -rp "המייל של המנהל (חשבון הגוגל שאיתו תתחבר): " ADMIN </dev/tty
  fi
  ADMIN="$(printf '%s' "$ADMIN" | tr -d ' \r\n')"
  [[ "$ADMIN" == *@*.* ]] || die "המייל לא תקין"
  umask 077
  cat > "$ENV" <<EOF
# Nails settings. Changing this file: sudo systemctl restart nails
NAILS_ADMIN_EMAILS=$ADMIN
NAILS_SIGNIN_METHODS=google,email
NAILS_SUPPORT_PHONE=0528326523
NAILS_SUPPORT_EMAIL=
NAILS_OPERATOR_NAME=
NAILS_OPERATOR_ID=
NAILS_OPERATOR_ADDRESS=
NAILS_BACKUP_KEEP=7
NAILS_BACKUP_UPLOAD_URL=
NAILS_DATA=data
EOF
  umask 022
  chmod 600 "$ENV"
  ok "ההגדרות נשמרו ב-$ENV"
fi
grep -q '^NAILS_DEV_AUTH=1' "$ENV" && die "NAILS_DEV_AUTH=1 אסור בשרת אמיתי. למחוק את השורה מ-$ENV"

# ---------- 5. address (domain) ----------
PORT_FILE="$BASE/.port"; DOMAIN_FILE="$BASE/.domain"
if [ -n "${NAILS_DOMAIN:-}" ]; then echo "$NAILS_DOMAIN" > "$DOMAIN_FILE"; fi
if [ ! -s "$DOMAIN_FILE" ]; then
  IP="$(curl -4 -fsS --max-time 10 https://api.ipify.org || curl -4 -fsS --max-time 10 https://ifconfig.me)"
  [[ "$IP" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "לא הצלחתי לגלות את כתובת ה-IP של השרת"
  echo "nails-${IP//./-}.sslip.io" > "$DOMAIN_FILE"    # free hostname that points to this IP
fi
DOMAIN="$(cat "$DOMAIN_FILE")"

# ---------- 6. app service on its own free port ----------
if [ -s "$PORT_FILE" ]; then PORT="$(cat "$PORT_FILE")"
else
  PORT=""
  for p in $(seq 8100 8199); do listening "$p" || { PORT=$p; break; }; done
  [ -n "$PORT" ] || die "לא נמצא פורט פנוי"
  echo "$PORT" > "$PORT_FILE"
fi

say "מגדיר את השירות nails (פורט פנימי $PORT)"
cat > /etc/systemd/system/nails.service <<EOF
[Unit]
Description=Nails app
After=network-online.target
Wants=network-online.target

[Service]
User=nails
Group=nails
WorkingDirectory=$APP
EnvironmentFile=$ENV
ExecStart=$VENV/bin/uvicorn app.main:app --host 127.0.0.1 --port $PORT --proxy-headers --forwarded-allow-ips 127.0.0.1 --no-access-log
Restart=always
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$APP/data

[Install]
WantedBy=multi-user.target
EOF
install -m 644 "$APP/deploy/nails-backup.service" /etc/systemd/system/nails-backup.service
install -m 644 "$APP/deploy/nails-backup.timer" /etc/systemd/system/nails-backup.timer
systemctl daemon-reload
systemctl enable -q nails nails-backup.timer
systemctl restart nails
systemctl start nails-backup.timer
for _ in $(seq 1 20); do curl -fsS "http://127.0.0.1:$PORT/api/config" >/dev/null 2>&1 && break; sleep 1; done
curl -fsS "http://127.0.0.1:$PORT/api/config" >/dev/null || { journalctl -u nails -n 30 --no-pager; die "האפליקציה לא עלתה"; }
ok "האפליקציה רצה, גיבוי לילי ב-00:00 מופעל"

# ---------- 7. Caddy site (only our block; the rest of the Caddyfile is kept) ----------
say "מחבר את $DOMAIN ב-Caddy"
CF=/etc/caddy/Caddyfile
mkdir -p /etc/caddy; touch "$CF"
cp "$CF" "$CF.before-nails"
# A fresh Caddy install ships a demo site on :80; it would clash, so comment it out.
if grep -q '^:80 {' "$CF" && grep -q 'file_server' "$CF" && ! grep -q 'NAILS BEGIN' "$CF"; then sed -i 's/^/# /' "$CF"; fi
sed -i '/# NAILS BEGIN/,/# NAILS END/d' "$CF"
cat >> "$CF" <<EOF
# NAILS BEGIN (managed by nails/deploy/install.sh)
$DOMAIN {
	encode zstd gzip
	request_body {
		max_size 60MB
	}
	reverse_proxy 127.0.0.1:$PORT
}
# NAILS END
EOF
if ! caddy validate --config "$CF" --adapter caddyfile >/dev/null 2>&1; then
  cp "$CF.before-nails" "$CF"
  caddy validate --config "$CF" --adapter caddyfile || true
  die "ההגדרות של Caddy לא תקינות. החזרתי את הקובץ הקודם"
fi
systemctl reload caddy || systemctl restart caddy
ok "Caddy"

# ---------- 8. server firewall: open 80/443 ----------
say "פותח פורטים 80 ו-443 בחומת האש של השרת"
if command -v firewall-cmd >/dev/null && systemctl is-active -q firewalld; then
  firewall-cmd -q --permanent --add-service=http --add-service=https && firewall-cmd -q --reload
elif command -v iptables >/dev/null; then
  for p in 80 443; do
    if ! iptables -C INPUT -p tcp -m state --state NEW --dport "$p" -j ACCEPT 2>/dev/null; then
      REJ="$(iptables -L INPUT --line-numbers -n | awk '$2=="REJECT"{print $1; exit}')"
      iptables -I INPUT "${REJ:-1}" -p tcp -m state --state NEW --dport "$p" -j ACCEPT
    fi
  done
  command -v netfilter-persistent >/dev/null && netfilter-persistent save >/dev/null 2>&1 || true
fi
ok "חומת אש בשרת"

# ---------- 9. check from outside ----------
say "בודק שהאתר נגיש מבחוץ (עד דקה, Caddy מוציא תעודת HTTPS)"
UP=""
for _ in $(seq 1 12); do
  if curl -fsS --max-time 8 "https://$DOMAIN/api/config" >/dev/null 2>&1; then UP=1; break; fi
  sleep 5
done

echo
printf '\033[1;35m====================================================\033[0m\n'
if [ -n "$UP" ]; then
  ok "Nails באוויר:  https://$DOMAIN"
else
  printf '\033[1;33m! האפליקציה רצה בשרת, אבל עדיין לא נגישה מבחוץ.\033[0m\n'
  echo "  כנראה צריך לפתוח את פורטים 80 ו-443 ב-Oracle:"
  echo "  Networking > Virtual Cloud Networks > (הרשת של השרת) > Security Lists > Default > Add Ingress Rules"
  echo "  Source CIDR: 0.0.0.0/0, IP Protocol: TCP, Destination Port: 80,443"
  echo "  אחרי זה להריץ את הסקריפט שוב."
  echo "  הכתובת תהיה:  https://$DOMAIN"
fi
echo
echo "  צעד אחרון ב-Firebase (בלי זה הכניסה עם גוגל לא תעבוד):"
echo "  Authentication > Settings > Authorized domains > Add domain:"
echo "      $DOMAIN"
echo
echo "  הגדרות: $ENV   (אחרי שינוי: sudo systemctl restart nails)"
echo "  לוגים:   sudo journalctl -u nails -f"
echo "  עדכון:   להריץ את אותה פקודה שוב"
printf '\033[1;35m====================================================\033[0m\n'
