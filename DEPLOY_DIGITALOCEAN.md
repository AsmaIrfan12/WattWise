# Deploying WattWise to a DigitalOcean Droplet

The whole stack runs from the root `docker-compose.yml`: MySQL, InfluxDB, Mosquitto,
the FastAPI backend, the admin + user web dashboards, nginx, backups, and the dummy
data sender. One `docker compose up` brings it all online, exactly like on your laptop.

The only things that don't come from `git clone` are the **secrets** (`.env` files, gitignored)
and the **public address** (you'll use the droplet's IP instead of the Cloudflare domain).

---

## 1. Create the droplet
- Ubuntu 24.04 LTS, **≥ 2 vCPU / 4 GB RAM** (MySQL + InfluxDB + backend need headroom),
  ≥ 50 GB disk.
- Add your SSH key. Note the droplet's public IP (called `DROPLET_IP` below).

## 2. Install Docker + Compose (on the droplet)
```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER && newgrp docker
docker compose version    # confirm v2
```

## 3. Open the firewall
```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp        # nginx → user dashboard, /api, /mqtt
sudo ufw allow 3000/tcp      # admin portal (optionally restrict to your IP)
sudo ufw allow 1883/tcp      # MQTT TCP for RPi publishers (see §8)
# sudo ufw allow 443/tcp     # only if you add TLS (§9)
sudo ufw enable
```
MySQL (3307) and InfluxDB (8086) are bound to `127.0.0.1` in compose — not public. Good.

## 4. Clone the repo
```bash
cd ~ && git clone https://github.com/AsmaIrfan12/WattWise.git wattwise && cd wattwise
```

## 5. Provide the secrets (`.env` files)
The clone has **no** `.env` (they're gitignored). Two files are needed:
`./.env` (compose vars) and `./Server Side/.env` (backend).

**Easiest — copy your working files from the laptop** (run on the laptop):
```bash
scp .env "root@DROPLET_IP:~/wattwise/.env"
scp "Server Side/.env" "root@DROPLET_IP:~/wattwise/Server Side/.env"
```
This reuses the exact passwords that already work, so the broker/db/backend all match.

**Or fill the templates** (on the droplet):
```bash
cp .env.example .env                                   # then edit: fill CHANGE_ME values
cp "Server Side/.env.production.template" "Server Side/.env"   # then edit
```
If you fill templates, the passwords in `./.env` and `./Server Side/.env` **must match**,
and the `MQTT_HOME_0NN_PASS` values must match what each RPi uses.

Add the droplet to CORS in **both** env files:
```
ALLOWED_ORIGINS=...,http://DROPLET_IP,http://DROPLET_IP:3000
```

## 6. Launch
```bash
docker compose up -d --build
docker compose ps          # all services Up / healthy
docker compose logs -f backend
```
First boot creates the DB schema, seeds participants, and the dummy sender begins a
5-minute cycle. Give it ~2–3 minutes.

## 7. Verify
```bash
curl -s http://localhost/health                 # {"status":"healthy"} via nginx
curl -s http://localhost:8000/health             # backend direct
docker compose logs --tail=20 dummy-data-sender  # "Cycle N done — sent=..."
```
From your browser:
- **Admin portal:** `http://DROPLET_IP:3000`
- **User dashboard / API:** `http://DROPLET_IP` (served by nginx on :80)

## 8. Point the RPis and the app at the droplet
Over a **bare IP there is no TLS**, so use plain HTTP/MQTT:

**RPi publisher** — edit each `rpi_publisher_config.yaml` `mqtt:` block to direct TCP
(simplest without TLS; the WebSocket transport always forces TLS in the publisher, so
don't use `ws://` on port 80):
```yaml
mqtt:
  host: "DROPLET_IP"
  port: 1883
  transport: "tcp"
  ws_path: ""        # unused for tcp
  username: "home_001"
  password: "<the home_001 MQTT password — matches MQTT_HOME_001_PASS in .env>"
  tls: false
```

**Android app** — set the server URL to `http://DROPLET_IP`, and add the IP to cleartext
in `app/src/main/res/xml/network_security_config.xml`:
```xml
<domain includeSubdomains="true">DROPLET_IP</domain>
```
(Default base URL/port also live in `util/Constants.kt`.) Rebuild the APK.

## 9. (Optional, recommended) Add a domain + HTTPS later
Point a domain's A record at `DROPLET_IP`, then issue a Let's Encrypt cert (nginx already
has a `:443` block + `letsencrypt`/`certbot_webroot` volumes). With TLS in place you can
switch the RPis back to `wss` on 443 (`port 443, transport websockets, ws_path /mqtt,
tls true`) and the app to `https://your.domain` — matching today's Cloudflare setup.

## 10. Day-to-day ops
```bash
docker compose logs -f <service>           # tail a service
docker compose restart backend             # restart one service
docker compose pull && docker compose up -d --build   # update after a git pull
docker compose down                        # stop all (keeps volumes/data)
```
- **Auto-start on reboot:** every long-running service uses `restart: unless-stopped`,
  and Docker starts on boot — so the stack (including the dummy sender) comes back by itself.
- **Backups:** the `mysql-backup` service dumps MySQL daily to the `backups_data` volume
  (30-day retention). Create `/backups/.backup_disabled` inside it to pause.
- **Stop the dummy data** (once you only want real RPi homes):
  `docker compose stop dummy-data-sender` (and remove the service if permanent).
