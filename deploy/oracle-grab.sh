#!/bin/bash
# Keeps asking Oracle for the free computer until it gets one, then tells
# you its address. Oracle's free tier in Toronto is often "Out of capacity";
# this retries every few minutes so you don't have to click Apply by hand.
#
# Also sets up everything the web form kept tripping on: its own network
# with ports 22/80/443 open, a public address, and an SSH key that lives at
# ~/.ssh/oracle-gta (so there's no guessing which key file is the right one).
#
# Needs: brew install oci-cli, and ~/.oci/config (an API key from the console).
# Run it with your Mac kept awake:   caffeinate -i bash deploy/oracle-grab.sh
# Stop it any time with Ctrl+C. Running it again is safe.
set -uo pipefail
export PYTHONWARNINGS=ignore   # oci-cli on Python 3.14 prints a harmless SyntaxWarning on every call
cd "$(dirname "$0")/.."

WAIT=${WAIT:-180}   # seconds between rounds
NAME=gta-router
KEY=~/.ssh/oracle-gta

say_it(){ echo "[$(date +%H:%M)] $*"; }
fail(){ say_it "STOPPED: $*"; exit 1; }
id_or_empty(){ [ "$1" = "null" ] && echo "" || echo "$1"; }

T=$(awk -F= '/^tenancy/{gsub(/ /,"",$2); print $2; exit}' ~/.oci/config 2>/dev/null)
[ -n "$T" ] || fail "no ~/.oci/config yet (make the API key in the Oracle console first)"
oci iam availability-domain list >/dev/null 2>&1 || fail "Oracle didn't accept the API key. Check ~/.oci/config."
AD=$(oci iam availability-domain list --query 'data[0].name' --raw-output)

# --- SSH key -------------------------------------------------------------
[ -f $KEY ] || ssh-keygen -t ed25519 -N "" -C gta-router -f $KEY >/dev/null
chmod 600 $KEY

# --- Network (created once, found by name after that) --------------------
VCN=$(id_or_empty "$(oci network vcn list -c "$T" --display-name gta-vcn --query 'data[0].id' --raw-output)")
if [ -z "$VCN" ]; then
  say_it "Creating the network..."
  VCN=$(oci network vcn create -c "$T" --display-name gta-vcn --dns-label gtavcn \
    --cidr-blocks '["10.0.0.0/16"]' --wait-for-state AVAILABLE --query data.id --raw-output) || fail "couldn't create network"
fi
SUB=$(id_or_empty "$(oci network subnet list -c "$T" --vcn-id "$VCN" --display-name gta-subnet --query 'data[0].id' --raw-output)")
if [ -z "$SUB" ]; then
  IGW=$(oci network internet-gateway create -c "$T" --vcn-id "$VCN" --display-name gta-igw --is-enabled true \
    --wait-for-state AVAILABLE --query data.id --raw-output) || fail "couldn't create internet gateway"
  RT=$(oci network route-table create -c "$T" --vcn-id "$VCN" --display-name gta-rt \
    --route-rules "[{\"destination\":\"0.0.0.0/0\",\"destinationType\":\"CIDR_BLOCK\",\"networkEntityId\":\"$IGW\"}]" \
    --wait-for-state AVAILABLE --query data.id --raw-output) || fail "couldn't create route table"
  port(){ echo "{\"source\":\"0.0.0.0/0\",\"protocol\":\"6\",\"isStateless\":false,\"tcpOptions\":{\"destinationPortRange\":{\"min\":$1,\"max\":$1}}}"; }
  SL=$(oci network security-list create -c "$T" --vcn-id "$VCN" --display-name gta-sl \
    --egress-security-rules '[{"destination":"0.0.0.0/0","protocol":"all","isStateless":false}]' \
    --ingress-security-rules "[$(port 22),$(port 80),$(port 443)]" \
    --wait-for-state AVAILABLE --query data.id --raw-output) || fail "couldn't create security list"
  SUB=$(oci network subnet create -c "$T" --vcn-id "$VCN" --display-name gta-subnet --dns-label gtasub \
    --cidr-block 10.0.0.0/24 --route-table-id "$RT" --security-list-ids "[\"$SL\"]" \
    --wait-for-state AVAILABLE --query data.id --raw-output) || fail "couldn't create subnet"
fi

# --- Image: newest Ubuntu 26.04 for Ampere, not the Minimal one ----------
IMG=$(id_or_empty "$(oci compute image list -c "$T" --operating-system "Canonical Ubuntu" --operating-system-version "26.04" \
  --shape VM.Standard.A1.Flex --sort-by TIMECREATED --sort-order DESC \
  --query "data[?!contains(\"display-name\", 'Minimal')] | [0].id" --raw-output)")
[ -n "$IMG" ] || fail "couldn't find the Ubuntu 26.04 image"

# --- Keep asking ----------------------------------------------------------
say_it "Network and image ready. Asking Oracle every $((WAIT/60)) minutes. Ctrl+C to stop."
round=0
while true; do
  round=$((round+1))
  EXISTING=$(id_or_empty "$(oci compute instance list -c "$T" --display-name $NAME \
    --query "data[?\"lifecycle-state\"=='RUNNING' || \"lifecycle-state\"=='PROVISIONING'] | [0].id" --raw-output)")
  if [ -n "$EXISTING" ] && [[ "$EXISTING" == ocid1.instance* ]]; then ID=$EXISTING; break; fi

  for size in "4 24" "2 12"; do
    set -- $size
    OUT=$(oci compute instance launch -c "$T" --availability-domain "$AD" --display-name $NAME \
      --shape VM.Standard.A1.Flex --shape-config "{\"ocpus\":$1,\"memoryInGBs\":$2}" \
      --image-id "$IMG" --subnet-id "$SUB" --assign-public-ip true \
      --ssh-authorized-keys-file $KEY.pub \
      --wait-for-state RUNNING --max-wait-seconds 900 --query data.id --raw-output 2>&1)
    if [ $? -eq 0 ]; then ID=$(echo "$OUT" | tail -1); say_it "GOT ONE: $1 OCPU / $2 GB"; break 2; fi
    if echo "$OUT" | grep -qi "capacity"; then
      say_it "Round $round: no room for $1 OCPU / $2 GB"
    elif echo "$OUT" | grep -qiE "timed out|timeout|connection|resolve|name or service|network is unreachable|RequestException|ServiceUnavailable"; then
      say_it "Round $round: no internet right now (Mac asleep?), trying again later"; break
    elif echo "$OUT" | grep -qi "TooManyRequests"; then
      say_it "Round $round: Oracle says slow down, waiting longer"; sleep $WAIT; break
    else
      echo "$OUT"; fail "Oracle gave an error that isn't 'out of capacity' (above)"
    fi
  done
  sleep $WAIT
done

IP=$(oci compute instance list-vnics --instance-id "$ID" --query 'data[0]."public-ip"' --raw-output)
echo "$IP" > deploy/oracle-ip.txt
say_it "READY. Public IP: $IP   SSH key: $KEY"
osascript -e "display notification \"Public IP $IP\" with title \"Oracle computer is ready\"" 2>/dev/null
say "Your Oracle computer is ready" 2>/dev/null
