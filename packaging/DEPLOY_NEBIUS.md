# Deploying MatchdayDB on Nebius AI Cloud

This is the public demo URL for the [Nebius x NVIDIA Global AI
Hackathon](https://nebiusglobalaihackathon.devpost.com/) submission. It runs
the real FastAPI app (not the desktop build) on a small Nebius AI Cloud
virtual machine, behind a reverse proxy that gives it HTTPS.

MatchdayDB was originally built as a single-user local app, not a public
website -- see the "Supported deployment" note in the main README. Two of
its existing security checks (a hostname allowlist and an origin check on
POST requests) are written around that assumption, and both need to see the
request's *real* public hostname and scheme to keep working once the app is
reverse-proxied. The steps below exist specifically to satisfy that, not to
loosen it: every request still has to present a host this deployment
explicitly allowed, and every POST still has to come from that same origin.

## 1. Create the VM

1. Sign in to the [Nebius AI Cloud console](https://console.nebius.com) and
   create (or select) a project.
2. **Compute -> Virtual machines -> Create resource -> Virtual machine.**
3. **Compute step:** choose the **Without GPUs** / **Non-GPU** platform
   (AMD Epyc Genoa, or Intel Ice Lake in `eu-north1`) -- MatchdayDB's
   embedding model runs on CPU, so a GPU platform would just cost more for
   nothing. A small preset (2 vCPU / 4 GiB RAM) is enough; see [Nebius's
   published compute pricing](https://docs.nebius.com/compute/resources/pricing)
   to estimate the hourly cost for whatever size you pick.
4. **Storage step:** a plain Ubuntu 24.04 image, 20-30 GiB disk is plenty
   (the embedding model is ~90MB; SQLite data stays small).
5. **Network step:** select **Auto (dynamic)** under **Public IP address**
   so you can reach it over SSH and HTTP(S).
6. **Configuration step:** add an **Access** credential -- a username (not
   `root`/`admin`) plus your SSH public key.
7. Review and create. Copy the VM's public IP once it's running.

## 2. Point a hostname at it (recommended)

Caddy (step 4) can get you a real HTTPS certificate automatically, but only
for an actual DNS name -- not a bare IP. Add an A record for a subdomain
(e.g. `matchdaydb.yourdomain.com`) pointing at the VM's public IP. If you'd
rather skip this, you can run Caddy without a domain and reach the app over
plain HTTP on the IP instead; the Devpost demo-URL requirement doesn't
require HTTPS specifically, but it's one extra step for very little effort.

## 3. Install MatchdayDB on the VM

```bash
ssh <username>@<public_IP_address>
sudo apt update && sudo apt install -y python3.12 python3.12-venv git
git clone https://github.com/AagamS06/MatchdayDB.git
cd MatchdayDB
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Set the environment this instance runs with. The simplest option is a
`.env` file next to the code (same mechanism the desktop build uses, see
`config.py`'s `load_env_file`) -- or export them directly for a systemd
service (step 5):

```bash
cat > .env <<'EOF'
FOOTBALL_API_KEY=your-football-data-org-key
MATCHDAY_SOURCE=api
NEBIUS_API_KEY=your-nebius-token-factory-key
NEBIUS_MODEL=nvidia/nemotron-3-super-120b-a12b
MATCHDAY_ALLOWED_HOSTS=matchdaydb.yourdomain.com,localhost,127.0.0.1
EOF
```

(No football-data.org key yet, or don't want to use one for the public
demo? Leave `FOOTBALL_API_KEY` unset / `MATCHDAY_SOURCE=demo` -- the app
falls back to its 60-player synthetic demo automatically, and AI Scout
works identically against it.)

Pre-download the embedding model once, so the first real visitor isn't the
one waiting on it:

```bash
python app.py --prepare-model
```

## 4. Put Caddy in front of it

Caddy gets you automatic HTTPS (via Let's Encrypt) with a two-line config,
and it forwards the headers uvicorn needs (`X-Forwarded-Proto` in
particular) without any extra flags on Caddy's side:

```bash
sudo apt install --yes debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo chmod o+r /usr/share/keyrings/caddy-stable-archive-keyring.gpg
sudo chmod o+r /etc/apt/sources.list.d/caddy-stable.list
sudo apt update
sudo apt install caddy
```

`/etc/caddy/Caddyfile`:

```
matchdaydb.yourdomain.com {
    reverse_proxy 127.0.0.1:8000
}
```

(No domain? Use `:80` instead of the domain line, and Caddy serves plain
HTTP on the VM's public IP.)

```bash
sudo systemctl reload caddy
```

## 5. Run MatchdayDB as a service

`/etc/systemd/system/matchdaydb.service` (adjust `User`/paths to match the
VM):

```ini
[Unit]
Description=MatchdayDB
After=network.target

[Service]
Type=simple
User=<username>
WorkingDirectory=/home/<username>/MatchdayDB
EnvironmentFile=/home/<username>/MatchdayDB/.env
ExecStart=/home/<username>/MatchdayDB/.venv/bin/uvicorn app:create_app --factory --host 127.0.0.1 --port 8000 --proxy-headers --forwarded-allow-ips=127.0.0.1
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

This runs uvicorn directly (bypassing `app.py`'s own CLI, whose `--host`
flag is deliberately limited to loopback for the desktop/local use case --
see `main()` in `app.py`). `--proxy-headers --forwarded-allow-ips=127.0.0.1`
is what makes uvicorn trust Caddy's `X-Forwarded-Proto: https`, so the app
sees the request as `https://matchdaydb.yourdomain.com` and not
`http://127.0.0.1:8000` -- without that, the origin check on `/sync` and
`/data/connect` (both POST) would reject every request from the real site,
even though plain `GET`s (including `/ai/ask`) would work fine. This is
exactly the gap closed by making `MATCHDAY_ALLOWED_HOSTS` configurable
(`config.py`, `app.py`) instead of working around it with a header rewrite
at the proxy.

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now matchdaydb
```

## 6. Verify

```bash
curl https://matchdaydb.yourdomain.com/health
```

Then open it in a browser, and specifically exercise a POST path (**Data &
connection -> Connect & sync**, or **AI Scout**'s question form) to confirm
the origin/host checks above are actually passing end to end, not just the
GETs.

## Updating

```bash
cd ~/MatchdayDB && git pull && sudo systemctl restart matchdaydb
```
