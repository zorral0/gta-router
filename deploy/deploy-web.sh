#!/bin/bash
# Runs on your Mac. Puts the app page (web/) on Vercel, pointed at the cloud
# engine. Vercel passes every /otp/... request on to that engine, so the
# page never needs to know the engine's address.
# Usage: bash deploy/deploy-web.sh <server-ip>
set -euo pipefail
cd "$(dirname "$0")/.."
HOST="${1//./-}.sslip.io"
OUT=deploy/build/gta-router   # kept between runs so Vercel reuses the same project and link

mkdir -p "$OUT"
rsync -a --delete --exclude .vercel web/ "$OUT/"
cat > "$OUT/vercel.json" <<JSON
{ "rewrites": [ { "source": "/otp/:path*", "destination": "https://$HOST/otp/:path*" } ] }
JSON
cd "$OUT" && npx --yes vercel@latest deploy --prod --yes
