#!/bin/bash
# Runs on your Mac. Uploads the routing engine to the Oracle cloud computer
# (about 1.2 GB the first time, only changed files after that) and starts it.
# Run it again after refresh.sh builds new graphs.
# Usage: bash deploy/push-engine.sh <server-ip> <path-to-ssh-key>
set -euo pipefail
cd "$(dirname "$0")/.."
IP="$1"; KEY="$2"
HOST="${IP//./-}.sslip.io"
chmod 600 "$KEY"   # ssh refuses keys other people can read
SSH="ssh -i $KEY -o StrictHostKeyChecking=accept-new"
DEST="ubuntu@$IP"

$SSH "$DEST" "mkdir -p gta-router/reach-engine gta-router/deploy gta-router/scripts gta-router/engine"
rsync -aP -e "$SSH" engine/otp.jar engine/graph.obj engine/otp-config.json engine/router-config.json metrolinx.env "$DEST:gta-router/"
rsync -aP -e "$SSH" engine/otp25.jar "$DEST:gta-router/otp25.jar"
rsync -aP -e "$SSH" engine/graph.obj.otp25 "$DEST:gta-router/reach-engine/graph.obj"
rsync -aP -e "$SSH" engine/reach-engine/otp-config.json "$DEST:gta-router/reach-engine/"
# The two live-feed filters. They find everything from their own location
# (scripts/ next to pbwire.py, the Durham zip in engine/, output .pb files in
# the folder above scripts/), so keep this same layout on the server.
rsync -aP -e "$SSH" scripts/go-alerts-filter.py scripts/drt-rt-filter.py scripts/pbwire.py "$DEST:gta-router/scripts/"
rsync -aP -e "$SSH" engine/drt-gtfs.zip "$DEST:gta-router/engine/"
rsync -aP -e "$SSH" deploy/server-setup.sh deploy/Caddyfile deploy/gta-otp.service deploy/gta-reach.service deploy/gta-go-alerts.service deploy/gta-drt-rt.service "$DEST:gta-router/deploy/"
$SSH "$DEST" "bash gta-router/deploy/server-setup.sh $HOST"
