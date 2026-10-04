# GTA Router - the environment the engine's config needs.
#
# Sourced by run.sh, setup.sh and refresh.sh. engine/router-config.json names
# ${METROLINX_KEY} and ${GTA_ROUTER_DIR}, and OpenTripPlanner reads that file
# even when it is only BUILDING a graph: with either variable unset it
# refuses to start at all. run.sh used to be the only script that set them,
# so every graph build in setup.sh and refresh.sh failed on the spot.

GTA_ROUTER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export GTA_ROUTER_DIR

# The GO real-time feeds need a free Metrolinx key. It lives in
# metrolinx.env, which is never uploaded to GitHub.
if [ ! -f "$GTA_ROUTER_DIR/metrolinx.env" ]; then
  echo "Missing metrolinx.env. Copy metrolinx.env.example to metrolinx.env"
  echo "and put your Metrolinx Open Data key in it."
  return 1 2>/dev/null || exit 1
fi
set -a; . "$GTA_ROUTER_DIR/metrolinx.env"; set +a
