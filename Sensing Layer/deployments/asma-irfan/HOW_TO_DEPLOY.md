# How to Deploy WattWise — Cloud (Docker droplet) + Home Assistant RPi Publisher

**Runbook** — Part B is the exact, proven procedure used to get Asma Irfan's RPi (`home_001`)
publishing live data to the WattWise cloud; follow it to onboard any new participant's
Raspberry Pi. It works on **Home Assistant OS** (no host `systemctl`; the publisher runs as a
Supervisor add-on). Part A brings up the cloud it publishes to.

> 🔒 Real passwords are **not** in this file. Fill each `<placeholder>` from the sources in
> §"Per-home values". Asma's actual values live in the gitignored `asma-home.secrets.local`.

This document has two parts — do them in order on a brand-new setup:

- **Part A — Cloud:** bring up the whole WattWise stack with Docker on a fresh droplet.
- **Part B — RPi:** point a participant's Home Assistant Pi at that cloud.

---

# Part A — Deploy the WattWise cloud on a fresh droplet (Docker)

Target: a fresh **Ubuntu 24.04 (LTS) x64** DigitalOcean droplet with the **Reserved IP
`67.207.68.22`** assigned to it (DigitalOcean panel → Networking → Reserved IPs). Use the
Reserved IP everywhere — it survives droplet rebuilds, the plain public IPv4 does not.
Size: **2 vCPU / 2 GB** ($18/mo) with the 4 GB swap from A1, or 2 vCPU / 4 GB. Do **not** use the 512 MB or 1 GB sizes — MySQL gets
OOM-killed during its first-time setup and leaves a half-initialised database (see A7).

> A new droplet starts empty. MySQL / InfluxDB data from a destroyed droplet is gone unless
> you restore a backup; the 50 synthetic participants and the admin account are re-seeded
> automatically on first boot.

## A1. On the droplet — install Docker and prepare the box
```bash
ssh root@67.207.68.22

# Docker Engine + Compose plugin
apt update && apt -y upgrade
curl -fsSL https://get.docker.com | sh
docker --version && docker compose version

# Swap (REQUIRED on a 2 GB droplet, harmless on 4 GB — stops MySQL/InfluxDB being OOM-killed)
fallocate -l 4G /swapfile && chmod 600 /swapfile && mkswap /swapfile \
  && swapon /swapfile && echo '/swapfile none swap sw 0 0' >> /etc/fstab

# Firewall: SSH, user dashboard/API (80), admin portal (3000), MQTT for RPis (1883)
ufw allow OpenSSH && ufw allow 80/tcp && ufw allow 3000/tcp \
  && ufw allow 1883/tcp && ufw --force enable

# Code
git clone https://github.com/AsmaIrfan12/WattWise.git /opt/wattwise
```
`/opt/wattwise` is the path the CI deploy job expects (see A6).

## A2. On your laptop — copy the two secret files
Both `.env` files are gitignored, so they never arrive with `git clone`. From the repo root
on the laptop (PowerShell):
```powershell
scp .env "root@67.207.68.22:/opt/wattwise/.env"
scp "Server Side/.env" "root@67.207.68.22:/opt/wattwise/Server Side/.env"
```
No laptop copy? Create them from `.env.example` and `Server Side/.env.production.template`.
The stack is IP-agnostic — nothing in either file needs the droplet's address.

## A3. On the droplet — start the stack
```bash
cd /opt/wattwise
docker compose up -d --build      # first boot ~2-3 min (schema + seed + bootstrap)
docker compose ps                 # long-running services Up / healthy
curl -s http://localhost/health   # {"status":"healthy"}
```
`mosquitto-init`, `db-seed` and `bootstrap-aggregator` are one-shot jobs — showing as
**Exited (0)** is correct. Everything else restarts automatically after a reboot.

## A4. Check it from outside
| What | Address |
|---|---|
| User dashboard / API | `http://67.207.68.22` |
| Admin portal | `http://67.207.68.22:3000` (login: `ADMIN_EMAIL` / `ADMIN_PASSWORD` in `Server Side/.env`) |
| MQTT for RPis | `67.207.68.22:1883` · transport tcp · tls false |

From any other machine: `nc -vz 67.207.68.22 1883` should connect.

Expect a warm-up: energy totals stay `0 kWh` for ~30–60 min until the hourly aggregation
runs; rankings fill the next day; personas need ~2 days of data.

## A5. Day-to-day commands (run in `/opt/wattwise`)
```bash
docker compose logs -f backend                   # tail one service
docker compose logs -f                           # tail everything
docker compose restart backend                   # restart one service
git pull && docker compose up -d --build         # update to the latest main
docker compose run --rm bootstrap-aggregator     # rebuild summaries + rankings + personas
docker compose down                              # stop (data volumes are kept)
```

## A6. After the cloud is up
- **RPis:** every Pi must publish to `67.207.68.22:1883` — new Pi → Part B; existing Pi →
  change `mqtt.host` in `/config/wattwise_publisher.yaml` and restart the add-on.
- **Android app:** the default server URL is compiled in (`util/Constants.kt`). Rebuild and
  reinstall the APK (`./gradlew assembleDebug` in `User Apps/Android/WattWiseUserApp`), or
  change the server address in the app's Settings on existing installs.
- **CI auto-deploy (optional):** for pushes to `main` to deploy here, set the GitHub secret
  `PROD_HOST` to `67.207.68.22` and add the `PROD_SSH_KEY` public key to the droplet's
  `~/.ssh/authorized_keys`.

## A7. Cloud troubleshooting
| Symptom | Fix |
|---|---|
| `docker compose up` fails with `env file ... not found` | the `.env` files weren't copied — redo A2 |
| backend stuck `unhealthy` / restarting | `docker compose logs backend`; usually MySQL still initialising on first boot — wait 2 min |
| "Service temporarily unavailable", containers killed | out of memory — confirm swap with `free -h` (A1) or resize the droplet |
| Dashboard unreachable from outside, `curl localhost/health` OK | firewall — `ufw status`, plus any DigitalOcean Cloud Firewall on the droplet |
| RPi can't connect on 1883 | port 1883 blocked (same firewall check), or the Reserved IP isn't assigned to this droplet |
| `wattwise-mysql` loops `Restarting (137)` / `dependency mysql failed to start` | MySQL is being OOM-killed: droplet too small or no swap — `sudo dmesg -T \| grep -i "out of memory"` confirms. Resize / add swap (A1), then do the next row |
| backend can't log in to MySQL (`Access denied`) after MySQL was killed on first boot | the data volume holds a half-finished init (no `wattwise_db`, no app user). Reset it — it contains no real data yet: `docker compose down && docker volume rm wattwise_mysql_data && docker compose up -d` |

---

# Part B — Deploy the publisher to a Home Assistant RPi

## Prerequisites
- SSH / terminal access to the HA OS Pi.
- The four fixed values for that participant (see §"Per-home values"):
  `home_id`, MQTT `host/port/user/pass`, InfluxDB `host/db/user/pass`, and the device
  `entity_id` ↔ `power_entity_id` mappings.
- The WattWise cloud reachable at **`67.207.68.22:1883`** (droplet, plain MQTT/TCP) —
  i.e. Part A is done.

---

## 1. Get a shell
Settings → Add-ons → search **"Terminal & SSH"** or **"Advanced SSH & Web Terminal"** →
Install (if not already) → Start → **Open Web UI**.

## 2. Fetch and stage the add-on code
```bash
cd ~
git clone https://github.com/AsmaIrfan12/WattWise.git 2>/dev/null || (cd WattWise && git pull)
cp -r ~/WattWise/"Sensing Layer/hass-addon/wattwise-publisher" ~/addons/
ls ~/addons/wattwise-publisher
```
Expected listing: `Dockerfile  README.md  build.yaml  config.yaml  publisher.default.yaml  run.sh  rpi_mqtt_publisher.py`

## 3. Make the Supervisor discover the add-on  ⚠️ key step
A UI **"Reload"** alone does **not** reliably pick up a freshly-copied local add-on.
Reload from the CLI instead:
```bash
ha addons reload      # (newer alias: `ha apps reload` — same effect; deprecation note is harmless)
```
Then: Settings → Add-ons → Add-on Store → it now appears under **Local add-ons** as
**"WattWise Publisher"**. If it still doesn't show, re-run the reload — the Supervisor must
re-scan `/addons`, and the Store's own "Check for updates" button doesn't always trigger that.

## 4. Install and prime the config
Open **WattWise Publisher** → **Install** (first build takes a couple of minutes — it builds
a Docker image on-device) → **Start** once → **Stop**. Starting once writes the default
`wattwise_publisher.yaml` template to `/config/`, which you overwrite next.

## 5. Write the real config
The config file is `/config/wattwise_publisher.yaml` = `~/homeassistant/wattwise_publisher.yaml`
in the terminal (also editable via the **File editor** add-on). Overwrite it:
```bash
cat > ~/homeassistant/wattwise_publisher.yaml <<'YAML'
home:
  id: "<home_id>"                       # e.g. home_001 (MUST match the MQTT username / broker ACL)
  name: "<Participant Name>'s Home"
  devices:
    - id: "<device_id>"                 # e.g. airfryer
      name: "<Device Name>"
      appliance_key: "<device_id>"
      entity_id: "sensor.<ha_entity_suffix>"     # cloud-match string — keep exactly as registered
      power_entity_id: "<influxdb_tag_name>"     # the entity_id TAG in HA InfluxDB (see §6)
    # ...repeat per device
influxdb:
  host: "localhost"
  port: 8086
  database: "homeassistant"
  username: "homeassistant"
  password: "<influxdb_password_from_secrets.yaml>"
  ssl: false
mqtt:
  host: "67.207.68.22"                # WattWise droplet
  port: 1883
  transport: "tcp"
  ws_path: ""
  username: "<mqtt_username>"           # = home_id, e.g. home_001
  password: "<mqtt_password>"           # from Server Side/.env: MQTT_HOME_0NN_PASS
  tls: false
publish_interval_seconds: 30
log_level: "INFO"
YAML
```
Verify it landed:
```bash
cat ~/homeassistant/wattwise_publisher.yaml
wc -l ~/homeassistant/wattwise_publisher.yaml
```

## 6. Confirm the InfluxDB tag names match  (do this BEFORE starting)
```bash
curl -s -G 'http://localhost:8086/query?db=homeassistant' \
  -u 'homeassistant:<influxdb_password>' \
  --data-urlencode 'q=SHOW TAG VALUES FROM "W" WITH KEY = "entity_id"'
```
Cross-check every `power_entity_id` against this list. **Mismatches here are the #1 cause of
`Loop: 0 published`.** Leave every `entity_id` unchanged (that's the cloud match).

## 7. Start and verify
In the UI: **Start**, then toggle on **Start on boot** and **Watchdog**. Open the **Log** tab
and confirm this sequence, repeating every 30 s with `0 errors`:
```
✅ Config loaded ... (home_id=..., mqtt_user=...)
📊 InfluxDB reader initialised: localhost:8086/homeassistant
✅ MQTT connected to 67.207.68.22:1883
InfluxDB ping: ✅ OK
🔄 Loop #1: 4 published, 0 errors
```

## 8. Cloud-side confirmation
Open `http://67.207.68.22:3000`, log in with the **admin portal** credentials (separate from
the MQTT/InfluxDB creds — see `Server Side/.env`: `ADMIN_EMAIL` / `ADMIN_PASSWORD`), and confirm
the home shows **online** with live wattage within ~2 minutes.

---

## Per-home values (what changes for each RPi)
| Field | Where to get it | Asma (`home_001`) example |
|---|---|---|
| `home.id` / `mqtt.username` | broker ACL — always `home_NNN` | `home_001` |
| `mqtt.password` | `Server Side/.env` → `MQTT_HOME_0NN_PASS` | *(in `asma-home.secrets.local`)* |
| `influxdb.password` | that Pi's HA `secrets.yaml` → `influxdb_password` | *(in `asma-home.secrets.local`)* |
| device `entity_id` (cloud) | admin DB / the participant's registered devices | `sensor.airfryer_04d1f4`, `sensor.dishwasher_aebe90`, `sensor.microwave_821ec2`, `sensor.washing_machine_b612c5` |
| device `power_entity_id` (InfluxDB tag) | §6 `SHOW TAG VALUES` on that Pi | `airfryer_current_consumption`, `dishwasher_current_consumption`, `microwave_current_consumption`, `washing_machine_current_consumption` |

Keep `appliance_key` values as the standard set; `mqtt.host` (`67.207.68.22`) and the
`influxdb` host/db/username (`localhost` / `homeassistant` / `homeassistant`) are the same for
every home. A ready-to-edit template with Asma's device mappings is in this folder's
`rpi_publisher_config.yaml` and the add-on's `publisher.default.yaml`.

## Troubleshooting
| Log line | Fix |
|---|---|
| Add-on not in the Store after copy | Run `ha addons reload` in the terminal (§3); the UI Reload alone isn't enough |
| `MQTT connect failed (rc=5)` | Wrong MQTT user/pass, or `home.id` ≠ MQTT username |
| `MQTT connection ... failed` / timeout | Droplet unreachable on 1883 — check the Pi's internet and the droplet firewall |
| `InfluxDB ping: ❌ FAIL` | InfluxDB add-on stopped, or wrong `influxdb.password` |
| `Loop: 0 published` | a `power_entity_id` doesn't match the InfluxDB tag — redo §6 |

## Notes
- **TLS:** the droplet uses plain MQTT over a bare IP, so the MQTT password crosses the
  internet unencrypted — acceptable for a research pilot. When a domain + TLS is added, switch
  `mqtt` back to `port 443, transport websockets, ws_path /mqtt, tls true`.
- **Updates:** to update the add-on later, re-run §2 (`git pull` + `cp`), then `ha addons reload`,
  then Rebuild/Update the add-on in the UI. The config in `/config/wattwise_publisher.yaml` is
  preserved across rebuilds.
