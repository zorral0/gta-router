# Deployment

The hosted version has two parts:

- **Web app** on Vercel, which also proxies routing requests to the engine.
- **Routing engines** (OpenTripPlanner 2.9, plus 2.5 for the Reach map) on an
  Ubuntu VM behind Caddy, which handles HTTPS. The scripts assume an Oracle
  Cloud Always Free Ampere instance (VM.Standard.A1.Flex, 4 OCPU, 24 GB).

Only the two planning endpoints are exposed publicly, not OpenTripPlanner's
debug UI.

## 1. Create the VM

- Image: Ubuntu 26.04 (the full image, not Minimal).
- Shape: VM.Standard.A1.Flex, 4 OCPU and 24 GB of memory. 2 OCPU and 12 GB
  works if you drop the Reach map.
- Give it a public IPv4 address and an SSH key.
- Add an ingress rule allowing TCP 80 and 443 from `0.0.0.0/0`.

Free Ampere capacity in a region is often exhausted. `deploy/oracle-grab.sh`
retries instance creation until one is available (requires `oci-cli` and an
API key in `~/.oci/config`).

## 2. Deploy the engine

Build the graphs locally first (`setup.sh`, which also builds the graph, or `refresh.sh`),
and make sure `metrolinx.env` exists. Then:

```bash
bash deploy/push-engine.sh <server-ip> <path-to-ssh-key>
```

This uploads the engines, graphs and configuration (about 1.2 GB the first
time, only changes after that), installs Java and Caddy, and starts both
engines as systemd services. The engine is served at
`https://<ip-with-dashes>.sslip.io`.

Two small services, `gta-go-alerts` and `gta-drt-rt`, keep rewriting cleaned
copies of the GO alerts and Durham delay feeds, and the engine reads those
files (via `GTA_ROUTER_DIR` in `gta-otp.service`). Without them, GO alerts
and Durham live delays do not load. Their logs: `journalctl -u gta-go-alerts`.

## 3. Deploy the web app

```bash
npx vercel login
bash deploy/deploy-web.sh <server-ip>
```

This publishes `web/` to Vercel with a rewrite that forwards routing requests
to the engine, and prints the URL.

## Updating

Nothing updates automatically.

- After refreshing schedules, run `push-engine.sh` again.
- After changing the web app, run `deploy-web.sh` again.

The Metrolinx key is copied to the VM only. It is never included in the web
app or the repository.
