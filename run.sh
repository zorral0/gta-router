#!/bin/bash
# GTA Router - start everything.
# Starts the routing engine AND the app page, then opens the app in your
# browser at http://localhost:8081. Stop it all with Ctrl+C.

cd "$(dirname "$0")"

# 0) The GO real-time feeds need a free Metrolinx key. It lives in
#    metrolinx.env, which is never uploaded to GitHub. router-config.json
#    reads it as ${METROLINX_KEY}; without it the engine won't start.
if [ ! -f metrolinx.env ]; then
  echo "Missing metrolinx.env. Copy metrolinx.env.example to metrolinx.env"
  echo "and put your Metrolinx Open Data key in it."
  exit 1
fi
set -a; . ./metrolinx.env; set +a

# 1) The app page (the pretty UI in web/), served at :8081
python3 -m http.server 8081 --directory web >/dev/null 2>&1 &
WEB_PID=$!

# 2) The routing engine at :8080 (the app talks to it behind the scenes;
#    you never need to visit :8080 yourself - that's the engine's own
#    built-in debug page, not our app)
java -Xmx6G -jar otp.jar --load . &
OTP_PID=$!

# 2b) The "Reach map" engine at :8090. This is the older engine (kept as a
#     backup) - it's the only one that can draw the travel-time colour
#     blooms. It's read-only and uses about 1.7 GB while running. If it
#     ever fails to start, the Reach button just says so and the rest of
#     the app works exactly as before. Its log goes to reach-engine/reach.log
java -Xmx3G -jar otp25.jar.bak --load reach-engine --port 8090 >reach-engine/reach.log 2>&1 &
REACH_PID=$!

# Ctrl+C (or the engine dying) stops all three
trap 'kill $WEB_PID $OTP_PID $REACH_PID 2>/dev/null' EXIT INT TERM

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
