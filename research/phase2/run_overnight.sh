#!/bin/bash
# Run the full Phase 2 job, version 2 (weekday morning), while keeping the Mac awake.
# About 13,500 starting points and 382,000 requests: about 8.5 hours with 8 workers
# after a restart with nothing else heavy open (swapping makes it far slower). See the plan first with:
#   research/.venv/bin/python research/phase2/run_reach.py --dry-run
# Safe to run again after a stop: finished files are skipped.
# Output goes to research/phase2/run_v2.log. Watch it with:
#   tail -f research/phase2/run_v2.log
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
PY="$HERE/../.venv/bin/python"

if ! curl -s -m 10 -o /dev/null http://localhost:8091/otp; then
  echo "The research buffer engine on port 8091 is not answering yet."
  echo "Stop run.sh first (the Mac cannot run both), then start the engine from the gta-router folder:"
  echo "  java -Xmx6G -jar engine/otp25.jar --load engine/research-buffer --port 8091"
  echo "The job will wait for it."
fi

echo "Starting. Log: $HERE/run_v2.log  (stop with Ctrl+C, run this again to carry on)"
# caffeinate -i: no idle sleep while the job runs. Closing the laptop lid
# can still sleep the Mac, so leave it open and plugged in.
caffeinate -i "$PY" -u "$HERE/run_reach.py" "$@" 2>&1 | tee -a "$HERE/run_v2.log"
