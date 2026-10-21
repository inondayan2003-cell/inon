#!/usr/bin/env bash
# התקנה/עדכון של אנליסט הזהב על שרת לינוקס (Ubuntu או Oracle Linux).
# שימוש:  curl -fsSL https://raw.githubusercontent.com/inondayan2003-cell/inon/claude/telegram-stocks-gold-analyzer-akepc8/deploy/install.sh | sudo bash
set -euo pipefail

REPO="https://github.com/inondayan2003-cell/inon.git"
BRANCH="claude/telegram-stocks-gold-analyzer-akepc8"
DIR="/opt/gold-analyzer"

say() { printf '\n\033[1;33m==> %s\033[0m\n' "$*"; }
die() { printf '\n\033[1;31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "צריך להריץ עם sudo"
. /etc/os-release

say "מתקין כלים (git, curl)"
if command -v apt-get >/dev/null; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq git curl ca-certificates >/dev/null
else
  dnf install -y -q git curl ca-certificates >/dev/null
fi

if ! docker compose version >/dev/null 2>&1; then
  say "מתקין Docker"
  if [[ " ol rhel centos rocky almalinux " == *" ${ID} "* ]]; then
    dnf install -y -q dnf-plugins-core >/dev/null
    dnf config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
    dnf install -y -q docker-ce docker-ce-cli containerd.io docker-compose-plugin >/dev/null
  else
    curl -fsSL https://get.docker.com | sh >/dev/null
  fi
  systemctl enable --now docker
fi

say "מוריד את הקוד"
if [ -d "$DIR/.git" ]; then
  git -C "$DIR" fetch -q origin "$BRANCH"
  git -C "$DIR" reset -q --hard "origin/$BRANCH"
else
  git clone -q -b "$BRANCH" "$REPO" "$DIR"
fi
cd "$DIR"
mkdir -p data

IP="$(curl -fsS https://api.ipify.org || curl -fsS https://ifconfig.me)"
[ -n "$IP" ] || die "לא הצלחתי לזהות את ה-IP הציבורי של השרת"
DOMAIN="${IP//./-}.sslip.io"

if [ ! -f .env ]; then
  say "הגדרות (ההקלדה מוסתרת, הדבק ולחץ Enter)"
  read -rsp "BOT_TOKEN מ-BotFather: " BOT_TOKEN </dev/tty; echo
  [[ "$BOT_TOKEN" == *:* ]] || die "הטוקן לא נראה תקין (צריך להיות בפורמט 123456:ABC...)"
  read -rsp "TWELVEDATA_API_KEY (אפשר להשאיר ריק): " TD_KEY </dev/tty; echo
  umask 077
  cat > .env <<ENV
BOT_TOKEN=${BOT_TOKEN}
TWELVEDATA_API_KEY=${TD_KEY}
ALLOWED_USER_IDS=
ENV
fi
# הכתובת נקבעת לפי ה-IP, מתעדכנת בכל הרצה
sed -i '/^WEBAPP_URL=/d; /^DOMAIN=/d' .env
printf 'WEBAPP_URL=https://%s\nDOMAIN=%s\n' "$DOMAIN" "$DOMAIN" >> .env

say "פותח פורטים 80/443 בחומת האש של השרת"
if command -v firewall-cmd >/dev/null && systemctl is-active -q firewalld; then
  firewall-cmd -q --permanent --add-service=http --add-service=https
  firewall-cmd -q --reload
elif command -v iptables >/dev/null; then
  for p in 80 443; do
    iptables -C INPUT -p tcp --dport "$p" -j ACCEPT 2>/dev/null || iptables -I INPUT -p tcp --dport "$p" -j ACCEPT
  done
  if command -v netfilter-persistent >/dev/null; then netfilter-persistent save >/dev/null 2>&1 || true; fi
fi

# לא דורסים שירות אחר שכבר יושב על 80/443 (למשל בוט אחר באותו שרת)
if ! docker compose ps -q caddy 2>/dev/null | grep -q .; then
  busy="$(ss -ltnp 2>/dev/null | awk '$4 ~ /:(80|443)$/' || true)"
  [ -z "$busy" ] || die "פורט 80/443 כבר תפוס ע\"י שירות אחר בשרת:
$busy
לא נגעתי בכלום. שלח את ההודעה הזאת ל-Claude."
fi

say "בונה ומפעיל (בפעם הראשונה זה לוקח כמה דקות)"
docker compose up -d --build

say "בודק שהבוט עלה"
for _ in $(seq 1 30); do
  if docker compose exec -T app python -c "import urllib.request;urllib.request.urlopen('http://localhost:8000/health')" 2>/dev/null; then
    printf '\n\033[1;32m✓ הבוט רץ!\033[0m\n'
    printf 'כתובת האפליקציה: https://%s\n' "$DOMAIN"
    printf 'בדיקה: https://%s/health\n' "$DOMAIN"
    printf 'לוגים: cd %s && docker compose logs -f app\n\n' "$DIR"
    exit 0
  fi
  sleep 4
done
docker compose logs --tail 40 app
die "הבוט לא עלה, שלח את הלוג שלמעלה"
