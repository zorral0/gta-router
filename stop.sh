#!/bin/bash
# GTA Router - stop everything run.sh started, from any Terminal window.
# Same as pressing Ctrl+C in the window where run.sh is running, for when
# you can't find that window (or a copy is still running in the background).

cd "$(dirname "$0")"

# run.sh stops its own engine, page server and feed filters when told to
if [ -f run.pid ] && kill -0 "$(cat run.pid)" 2>/dev/null; then
  kill "$(cat run.pid)"
fi

# Then anything left over: from a run.sh that was force-quit, or started
# before run.pid existed. These patterns only match this app's processes.
sleep 2
for p in "engine/otp.jar --load engine" "engine/otp25.jar" "scripts/web-server.py" \
         "http.server 8081" "scripts/go-alerts-filter.py" "scripts/drt-rt-filter.py"; do
  pkill -f "$p"
done

# the engines can take a few seconds to let go of their ports
for i in $(seq 15); do
  busy=""
  for port in 8080 8081 8090; do
    lsof -nP -iTCP:$port -sTCP:LISTEN -t >/dev/null 2>&1 && busy="$busy $port"
  done
  [ -z "$busy" ] && { rm -f run.pid; echo "GTA Router is stopped."; exit 0; }
  sleep 1
done
echo "Something else is still using port(s)$busy. It may not be GTA Router."
exit 1
