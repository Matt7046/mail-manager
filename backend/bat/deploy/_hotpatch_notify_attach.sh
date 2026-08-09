#!/bin/bash
set -e
docker cp /tmp/mail_provider.py mail-manager:/app/mail_provider.py
docker cp /tmp/server.py mail-manager:/app/server.py
mkdir -p /root/mail-manager/backend
cp -f /tmp/mail_provider.py /root/mail-manager/backend/mail_provider.py
cp -f /tmp/server.py /root/mail-manager/backend/server.py
# nginx body size for attachments
if [ -f /tmp/mail.colorsdev.tech.conf ]; then
  cp -f /tmp/mail.colorsdev.tech.conf /root/nginx-apps/mail.colorsdev.tech.conf
  docker exec nginx nginx -t && docker exec nginx nginx -s reload || docker restart nginx
fi
# notify poll env
ENVF=/root/mail-manager/backend/.env
if [ -f "$ENVF" ]; then
  if grep -q '^NOTIFY_POLL_SECONDS=' "$ENVF"; then
    sed -i 's/^NOTIFY_POLL_SECONDS=.*/NOTIFY_POLL_SECONDS=5/' "$ENVF"
  else
    echo 'NOTIFY_POLL_SECONDS=5' >> "$ENVF"
  fi
  if grep -q '^SYNC_INTERVAL_SECONDS=' "$ENVF"; then
    sed -i 's/^SYNC_INTERVAL_SECONDS=.*/SYNC_INTERVAL_SECONDS=120/' "$ENVF"
  else
    echo 'SYNC_INTERVAL_SECONDS=120' >> "$ENVF"
  fi
fi
docker exec mail-manager find /app -name 'mail_provider*.pyc' -delete 2>/dev/null || true
docker exec mail-manager find /app -name 'server*.pyc' -delete 2>/dev/null || true
docker restart mail-manager
echo "waiting for healthy..."
for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
  sleep 3
  if docker exec mail-manager python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')" 2>/dev/null; then
    echo "health ok"
    docker logs --tail 30 mail-manager 2>&1 | grep -E 'Background:|notify ogni|Mail Manager API' | tail -10
    exit 0
  fi
  echo "retry $i"
done
echo "health check failed"
docker logs --tail 50 mail-manager
exit 1
