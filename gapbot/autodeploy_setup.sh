#!/bin/bash
# הפעלה חד-פעמית מ-Cloud Shell: השרת יתעדכן מעכשיו לבד מ-GitHub.
set -e
: "${AK:?}" "${AS:?}" "${TT:?}" "${TC:?}"
C="${OCI_TENANCY:?}"
ID=$(oci compute instance list -c "$C" --display-name gapbot --lifecycle-state RUNNING --query 'data[0].id' --raw-output)
IP=$(oci compute instance list-vnics --instance-id "$ID" --query 'data[0]."public-ip"' --raw-output)
echo "== מגדיר עדכון אוטומטי בשרת $IP..."
ssh -o StrictHostKeyChecking=no -i ~/.ssh/gapbot ubuntu@"$IP" "set -e
printf 'AK=%s\nAS=%s\nTT=%s\nTC=%s\n' '$AK' '$AS' '$TT' '$TC' | sudo tee /opt/gapbot/secrets.env >/dev/null
sudo chmod 600 /opt/gapbot/secrets.env
sudo curl -sfL https://raw.githubusercontent.com/inondayan2003-cell/inon/gapbot/gapbot/autodeploy.sh -o /opt/gapbot/autodeploy.sh
sudo chmod +x /opt/gapbot/autodeploy.sh
sudo tee /etc/systemd/system/gapbot-deploy.service >/dev/null <<'U'
[Unit]
Description=gapbot auto-deploy from GitHub
[Service]
Type=oneshot
ExecStart=/opt/gapbot/autodeploy.sh
U
sudo tee /etc/systemd/system/gapbot-deploy.timer >/dev/null <<'U'
[Unit]
Description=check GitHub for new gapbot version every 5 minutes
[Timer]
OnBootSec=2min
OnUnitActiveSec=5min
[Install]
WantedBy=timers.target
U
sudo systemctl daemon-reload
sudo systemctl enable --now gapbot-deploy.timer
sudo systemctl start gapbot-deploy.service || true
sudo journalctl -u gapbot-deploy -n 3 --no-pager
cat /opt/gapbot/VERSION"
echo "✅ מוכן. מעכשיו כל עדכון שאני מעלה ל-GitHub יגיע לשרת לבד תוך כ-5 דקות."
