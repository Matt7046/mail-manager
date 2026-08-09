#!/bin/bash
set -e
docker cp /tmp/push_notify.py mail-manager:/app/push_notify.py
docker cp /tmp/server.py mail-manager:/app/server.py
# Also keep copies under deploy path for reference
mkdir -p /root/mail-manager/backend
cp -f /tmp/push_notify.py /root/mail-manager/backend/push_notify.py
cp -f /tmp/server.py /root/mail-manager/backend/server.py
docker restart mail-manager
echo "waiting for healthy..."
for i in 1 2 3 4 5 6 7 8 9 10 11 12; do
  sleep 3
  if docker exec mail-manager python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')" 2>/dev/null; then
    echo "health ok"
    docker ps --filter name=mail-manager --format '{{.Names}} {{.Status}}'
    exit 0
  fi
  echo "retry $i"
done
echo "health check failed"
docker logs --tail 40 mail-manager
exit 1
