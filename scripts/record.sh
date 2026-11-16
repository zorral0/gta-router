#!/bin/bash
# GTA Router - run the live data recorder in the background.
# It is separate from run.sh and stop.sh, so it keeps recording while the app
# is stopped or rebuilding.
#
#   bash scripts/record.sh start
#   bash scripts/record.sh stop
#   bash scripts/record.sh status

cd "$(dirname "$0")/.."

case "$1" in
  start)
    if pgrep -f "scripts/record-feeds.py" >/dev/null; then
      echo "The recorder is already running."
      exit 0
    fi
    mkdir -p recordings
    # caffeinate keeps a Mac from idle-sleeping; a closed lid can still stop it
    keep_awake=""
    command -v caffeinate >/dev/null && keep_awake="caffeinate -i"
    nohup $keep_awake python3 -u scripts/record-feeds.py >>recordings/recorder.log 2>&1 &
    disown
    echo "The recorder started. Check on it with: bash scripts/record.sh status"
    ;;
  stop)
    pkill -f "scripts/record-feeds.py" && echo "The recorder stopped." \
      || echo "The recorder was not running."
    ;;
  status)
    python3 scripts/record-feeds.py --status
    ;;
  *)
    echo "Use: bash scripts/record.sh start, stop or status"
    exit 1
    ;;
esac
