#!/bin/bash
# Runs ON the Oracle cloud computer (push-engine.sh calls it for you).
# Installs Java, Python and Caddy, opens the firewall, and starts both engines and the two feed filters as
# services that come back by themselves after a reboot or crash.
# Usage: bash server-setup.sh <engine-host>
set -euo pipefail
HOST="$1"
APP=/home/ubuntu/gta-router

sudo apt-get update -q
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -q caddy curl gpg python3

# otp.jar is built for Java 25. Newer Ubuntu has it; older Ubuntu gets
# Adoptium's Temurin build instead. (The reach engine runs on 25 too.)
if ! sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -q openjdk-25-jre-headless; then
  curl -fsSL https://packages.adoptium.net/artifactory/api/gpg/key/public \
    | sudo gpg --dearmor --yes -o /usr/share/keyrings/adoptium.gpg
  echo "deb [signed-by=/usr/share/keyrings/adoptium.gpg] https://packages.adoptium.net/artifactory/deb $(. /etc/os-release; echo "$VERSION_CODENAME") main" \
    | sudo tee /etc/apt/sources.list.d/adoptium.list >/dev/null
  sudo apt-get update -q
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -q temurin-25-jdk
fi
java -version 2>&1 | head -1

# Oracle's Ubuntu images block web traffic in the computer's own firewall,
# on top of the security list in the Oracle console. Open 80 and 443 here.
for p in 80 443; do
  sudo iptables -C INPUT -p tcp --dport $p -j ACCEPT 2>/dev/null \
    || sudo iptables -I INPUT 1 -p tcp --dport $p -j ACCEPT
done
command -v netfilter-persistent >/dev/null && sudo netfilter-persistent save

sed "s/ENGINE_HOST/$HOST/" $APP/deploy/Caddyfile | sudo tee /etc/caddy/Caddyfile >/dev/null
sudo cp $APP/deploy/gta-otp.service $APP/deploy/gta-reach.service \
  $APP/deploy/gta-go-alerts.service $APP/deploy/gta-drt-rt.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable -q gta-otp gta-reach gta-go-alerts gta-drt-rt caddy

# The engine reads go-alerts-filtered.pb and drt-rt-filtered.pb at startup,
# so they must exist first (same order as run.sh): one pass of each filter
# now, then the filter services, then the engine. A failed pass is not fatal.
(cd $APP && python3 scripts/go-alerts-filter.py --once) \
  || echo "Note: GO service alerts could not be fetched. Everything else still works."
(cd $APP && python3 scripts/drt-rt-filter.py --once) \
  || echo "Note: Durham live delays could not be fetched. Everything else still works."
sudo systemctl restart gta-go-alerts gta-drt-rt
sudo systemctl restart gta-otp gta-reach caddy

echo "Loading the transit network (takes ~30-60 seconds)..."
for i in $(seq 1 90); do
  curl -s -m 2 -o /dev/null http://localhost:8080/otp/routers/default && { echo "READY: https://$HOST"; exit 0; }
  sleep 2
done
echo "Engine didn't answer after 3 minutes. See: sudo journalctl -u gta-otp -n 50"
exit 1
