#!/bin/bash
# GTA Router - start everything.
# Starts the routing engine AND the app page, then opens the app in your
# browser at http://localhost:8081. Stop it all with Ctrl+C, or with
# bash stop.sh from any Terminal window.

cd "$(dirname "$0")"

# 00) Already running? A second copy can't use the ports the first one
#     holds, but it still loads a whole second engine, about 6 GB of memory
#     (2026-10-04: two copies made every search "take too long").
for port in 8080 8081 8090; do
  if lsof -nP -iTCP:$port -sTCP:LISTEN -t >/dev/null 2>&1; then
    echo "GTA Router is already running (something is using port $port)."
    echo "Open http://localhost:8081, or stop it first with: bash stop.sh"
    exit 1
  fi
done

# 0) The Metrolinx key and GTA_ROUTER_DIR, which router-config.json needs;
#    without them the engine won't start (see scripts/engine-env.sh)
. scripts/engine-env.sh || exit 1

# 0b) Metrolinx's alerts feed ships empty agency_id/route_id fields that make
#     OTP throw once a minute and drop EVERY GO alert. This rewrites a clean
#     copy next to this script; router-config.json reads that file instead of
#     the live URL. One pass now so the file exists before the engine starts,
#     then a loop to keep it fresh.
python3 scripts/go-alerts-filter.py --once >/dev/null 2>&1 \
  || echo "Note: GO service alerts could not be fetched. Everything else still works."
# Its log (one line a minute, errors included) is engine/go-alerts.log.
python3 -u scripts/go-alerts-filter.py >engine/go-alerts.log 2>&1 &
ALERTS_PID=$!

# 0c) Durham's trip updates list stops that are not on the trip, which makes
#     OTP throw out the whole trip (about a fifth of the feed). Same idea as
#     0b: rewrite a clean copy and let router-config.json read that.
python3 scripts/drt-rt-filter.py --once >/dev/null 2>&1 \
  || echo "Note: Durham live delays could not be fetched. Everything else still works."
python3 -u scripts/drt-rt-filter.py >engine/drt-rt.log 2>&1 &
DRT_PID=$!

# 1) The app page (the pretty UI in web/), served at :8081 to this computer
#    only. The same server starts the "Reach map" engine (:8090, about
#    3.3 GB) the first time you tap with Reach on, and stops it after 15
#    quiet minutes; see scripts/web-server.py. It prints a line here when
#    it does either.
python3 -u scripts/web-server.py &
WEB_PID=$!

# 2) The routing engine at :8080 (the app talks to it behind the scenes;
#    you never need to visit :8080 yourself - that's the engine's own
#    built-in debug page, not our app. Like the page server, both engines
#    answer this computer only; OTP's default is every network interface.)
java -Xmx6G -jar engine/otp.jar --load engine --bindAddress 127.0.0.1 &
OTP_PID=$!

# Ctrl+C (or the engine dying, or bash stop.sh) stops the engine, the page
# server (which takes the Reach engine with it) and the two feed filters.
# Ctrl+C and stop.sh exit straight away, so a stop during loading doesn't
# say "Engine failed to start".
cleanup(){ kill $WEB_PID $OTP_PID $ALERTS_PID $DRT_PID 2>/dev/null; rm -f run.pid; }
trap cleanup EXIT
trap 'exit 130' INT TERM
# stop.sh reads this to find this script from any Terminal window
echo $$ > run.pid

# 3) Wait until the engine answers, then open the app in the browser
echo ""
echo "Loading the transit network (takes ~30-60 seconds)..."
until curl -s -m 2 -o /dev/null http://localhost:8080/otp/routers/default; do
  sleep 2
  # bail out if the engine crashed instead of waiting forever
  kill -0 $OTP_PID 2>/dev/null || { echo "Engine failed to start - see errors above."; exit 1; }
done
echo ""
echo "READY - opening http://localhost:8081 (bookmark it!)"
open "http://localhost:8081"

wait $OTP_PID
