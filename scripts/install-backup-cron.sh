#!/usr/bin/env bash
# Ставит systemd-таймер ежедневного бэкапа в 03:00. Запускать от root.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT="$ROOT/scripts/backup-db.sh"
[[ -x "$SCRIPT" ]] || chmod +x "$SCRIPT"

install -d -m 0750 /var/backups/opora

cat >/etc/systemd/system/opora-backup.service <<EOF
[Unit]
Description=OPORA PostgreSQL daily backup
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
ExecStart=$SCRIPT
Nice=10
EOF

cat >/etc/systemd/system/opora-backup.timer <<'EOF'
[Unit]
Description=OPORA PostgreSQL daily backup at 03:00

[Timer]
OnCalendar=*-*-* 03:00:00
Persistent=true

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now opora-backup.timer
systemctl list-timers opora-backup.timer --no-pager

echo "==> Проверка вручную: $SCRIPT"
