#!/bin/bash
# הקמת המיני-אפ: פתיחת פורטים 80/443, התקנת Caddy (https אוטומטי), עדכון הבוט.
# להריץ ב-Oracle Cloud Shell עם AK AS TT TC (ו-REF).
set -e
: "${AK:?}" "${AS:?}" "${TT:?}" "${TC:?}"
REF="${REF:-gapbot}"
C="${OCI_TENANCY:?}"
ID=$(oci compute instance list -c "$C" --display-name gapbot --lifecycle-state RUNNING --query 'data[0].id' --raw-output)
VNIC=$(oci compute instance list-vnics --instance-id "$ID" --query 'data[0]' 2>/dev/null)
IP=$(echo "$VNIC" | python3 -c 'import json,sys;print(json.load(sys.stdin)["public-ip"])')
SUB=$(echo "$VNIC" | python3 -c 'import json,sys;print(json.load(sys.stdin)["subnet-id"])')
HOST="$(echo "$IP" | tr . -).sslip.io"
echo "== פותח פורטים 80/443 ברשת של אורקל..."
for SL in $(oci network subnet get --subnet-id "$SUB" --query 'data."security-list-ids"' | python3 -c 'import json,sys;print(" ".join(json.load(sys.stdin)))'); do
  oci network security-list get --security-list-id "$SL" --query 'data."ingress-security-rules"' > /tmp/ing.json
  python3 - <<'PY'
import json
r = json.load(open("/tmp/ing.json"))
have = {(x.get("tcp-options") or {}).get("destination-port-range", {}).get("min") for x in r if x.get("protocol") == "6"}
for port in (80, 443):
    if port not in have:
        r.append({"protocol": "6", "source": "0.0.0.0/0", "isStateless": False,
                  "tcpOptions": {"destinationPortRange": {"min": port, "max": port}}})
# המרת מפתחות לפורמט שה-CLI מצפה לו
def camel(o):
    if isinstance(o, dict):
        return {"".join(w if i == 0 else w.title() for i, w in enumerate(k.split("-"))): camel(v) for k, v in o.items() if v is not None}
    if isinstance(o, list):
        return [camel(x) for x in o]
    return o
json.dump(camel(r), open("/tmp/ing2.json", "w"))
PY
  oci network security-list update --security-list-id "$SL" --ingress-security-rules file:///tmp/ing2.json --force >/dev/null
done
echo "== מתקין https על השרת ($HOST)..."
ssh -o StrictHostKeyChecking=no -i ~/.ssh/gapbot ubuntu@"$IP" "set -e
sudo iptables -C INPUT -p tcp --dport 80 -j ACCEPT 2>/dev/null || sudo iptables -I INPUT 1 -p tcp --dport 80 -j ACCEPT
sudo iptables -C INPUT -p tcp --dport 443 -j ACCEPT 2>/dev/null || sudo iptables -I INPUT 1 -p tcp --dport 443 -j ACCEPT
sudo sh -c 'command -v netfilter-persistent >/dev/null && netfilter-persistent save || true'
if ! command -v caddy >/dev/null; then
  sudo apt-get install -y debian-keyring debian-archive-keyring apt-transport-https curl gnupg >/dev/null
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/gpg.key | sudo gpg --batch --yes --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt | sudo tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
  sudo apt-get update >/dev/null && sudo apt-get install -y caddy >/dev/null
fi
echo '$HOST {
  reverse_proxy 127.0.0.1:8080
}' | sudo tee /etc/caddy/Caddyfile >/dev/null
sudo systemctl restart caddy
echo 'https://$HOST/' | sudo tee /opt/gapbot/webapp_url.txt >/dev/null"
echo "== מעדכן את הבוט..."
bash <(curl -sL "https://raw.githubusercontent.com/inondayan2003-cell/inon/$REF/gapbot/update.sh")
echo ""
echo "✅ המיני-אפ: https://$HOST/"
echo "בטלגרם: כפתור '📊 אפליקציה' ליד שורת ההקלדה בבוט (לפעמים צריך לסגור ולפתוח את הצ'אט)."
