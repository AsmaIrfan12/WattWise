# How to Deploy WattWise — Cloud (Docker + Cloudflare Tunnel) + Home Assistant RPi Publisher

**Runbook** — Part B is the exact, proven procedure used to get Asma Irfan's RPi (`home_001`)
publishing live data to the WattWise cloud; follow it to onboard any new participant's
Raspberry Pi. It works on **Home Assistant OS** (no host `systemctl`; the publisher runs as a
Supervisor add-on). Part A brings up the cloud it publishes to.

> 🔒 Real passwords are **not** in this file. Fill each `<placeholder>` from the sources in
> §"Per-home values". Asma's actual values live in the gitignored `asma-home.secrets.local`.

> 🌐 `wattwise.example.com` is a **placeholder** for your real domain, everywhere in this
> repo. Replace it once you own the domain (A0 below).

This document has two parts — do them in order on a brand-new setup:

- **Part A — Cloud:** run the whole WattWise stack with Docker on a laptop (or any machine)
  and publish it on your domain through a Cloudflare Tunnel.
- **Part B — RPi:** point a participant's Home Assistant Pi at that cloud.

---

# Part A — Run the WattWise cloud on a laptop behind a Cloudflare Tunnel

**How it works:** every service runs in Docker on the laptop. A small `cloudflared`
container opens an *outbound* connection to Cloudflare; Cloudflare serves
`https://wattwise.example.com` to the world and forwards requests down that connection to
nginx. Nothing listens on the internet, so **no router port-forwarding, no static/public IP,
no firewall holes and no TLS certificates** are needed — the laptop just needs internet.

Hardware: any laptop with **8 GB RAM** or more (Docker gets ≥ 4 GB) and ~10 GB free disk.
Works on Windows, macOS and Linux.

> The data lives in Docker volumes on this laptop (`mysql_data`, `influxdb_data`). Nightly
> MySQL dumps land in the `backups_data` volume; copy them off the laptop now and then.

## A0. Domain → Cloudflare (once)
1. Buy the domain at any registrar.
2. Create a free account at <https://dash.cloudflare.com>, **Add a domain**, pick the Free
   plan, and change the domain's **nameservers** at the registrar to the two Cloudflare gives
   you. Wait until Cloudflare shows the domain as **Active** (minutes to a few hours).
3. Put the real name into the repo on the laptop (one command, run in the repo root):
   ```bash
   git grep -l wattwise.example.com | xargs sed -i 's/wattwise.example.com/YOUR.DOMAIN/g'
   ```
   (PowerShell: `git grep -l wattwise.example.com | % { (Get-Content $_) -replace 'wattwise.example.com','YOUR.DOMAIN' | Set-Content $_ }`)
   Commit and push so every machine, RPi and the Android build see the same name.

## A1. Create the tunnel (Cloudflare dashboard, once)
1. <https://one.dash.cloudflare.com> → **Networks → Tunnels → Create a tunnel → Cloudflared**.
   Name it `wattwise`, click Save.
2. On the *Install connector* page, **copy the token** (the long string after
   `--token` in the shown command). Ignore the install instructions — the compose stack runs
   the connector for you.
3. **Public hostnames** tab → add these two routes (the service names resolve inside the
   compose network):

   | Subdomain | Domain | Type | URL |
   |---|---|---|---|
   | *(empty)* or `www` | `wattwise.example.com` | HTTP | `wattwise-nginx-proxy:80` |
   | `admin` | `wattwise.example.com` | HTTP | `wattwise-admin-frontend:3000` |

   The first route carries the user dashboard, `/api/*`, `/ws/*` and the RPi MQTT WebSocket
   `/mqtt`. WebSockets are on by default on Cloudflare; nothing else to enable.

## A2. Laptop — install Docker and get the code
- **Windows / macOS:** install **Docker Desktop**, then in its Settings: *General → Start
  Docker Desktop when you sign in* ✅, *Resources → Memory ≥ 4 GB*.
- **Linux:** `curl -fsSL https://get.docker.com | sh` and `sudo usermod -aG docker $USER`.

```bash
git clone https://github.com/AsmaIrfan12/WattWise.git wattwise
cd wattwise
```

## A3. Laptop — the two secret files
Both are gitignored; `git clone` never brings them. Either copy them from a machine that
already has them, or create them from the templates and fill every `CHANGE_ME` / `REPLACE_`
value:
```bash
cp .env.example .env
cp "Server Side/.env.production.template" "Server Side/.env"
```
In the root **`.env`** make sure these are set:
```ini
COMPOSE_PROFILES=tunnel
CLOUDFLARE_TUNNEL_TOKEN=<token from A1>
ALLOWED_ORIGINS=https://wattwise.example.com,https://admin.wattwise.example.com,http://localhost:3000,http://localhost:3001
```
and in **`Server Side/.env`**: the same `ALLOWED_ORIGINS` plus
`RESET_BASE_URL=https://wattwise.example.com`.
The MySQL / InfluxDB / MQTT passwords must be identical in both files.

## A4. Laptop — start the stack
```bash
docker compose up -d --build      # first boot ~2-3 min (image build + schema + seed + bootstrap)
docker compose ps                 # long-running services Up / healthy
curl -s http://localhost/health   # {"status":"healthy"}
docker compose logs cloudflared   # "Registered tunnel connection" x4 = tunnel is live
```
`mosquitto-init`, `db-seed` and `bootstrap-aggregator` are one-shot jobs — **Exited (0)** is
correct. Everything else restarts automatically whenever Docker starts.

## A5. Check it from outside (phone on mobile data is a good test)
| What | Address |
|---|---|
| User dashboard / API | `https://wattwise.example.com` |
| Health | `https://wattwise.example.com/health` → `{"status":"healthy"}` |
| Admin portal | `https://admin.wattwise.example.com` (login: `ADMIN_EMAIL` / `ADMIN_PASSWORD` in `Server Side/.env`) |
| MQTT for RPis | `wattwise.example.com` · port `443` · transport `websockets` · path `/mqtt` · tls `true` |

Expect a warm-up: energy totals stay `0 kWh` for ~30–60 min until the hourly aggregation
runs; rankings fill the next day; personas need ~2 days of data.

## A6. Keep the laptop serving
- **Windows:** Settings → System → Power → *Screen & sleep*: **Never** sleep when plugged
  in; *Lid close action* (Control Panel → Power Options) → **Do nothing**. Or from an
  admin PowerShell: `powercfg /change standby-timeout-ac 0` and
  `powercfg /change hibernate-timeout-ac 0`.
- **macOS:** System Settings → Battery/Energy → *Prevent automatic sleeping when the display
  is off* ✅, or run `caffeinate -s` in a terminal.
- **Linux:** `sudo systemctl mask sleep.target suspend.target hibernate.target`.
- Keep it on mains power and wired/stable Wi-Fi. After a reboot, Docker Desktop starts at
  login and brings every container back; the tunnel reconnects by itself.
- Home IP changes, VPNs and router NAT don't matter — the tunnel is outbound only.

## A7. Day-to-day commands (run in the repo root)
```bash
docker compose logs -f backend                   # tail one service
docker compose logs -f                           # tail everything
docker compose restart backend                   # restart one service
git pull && docker compose up -d --build         # update to the latest main
docker compose run --rm bootstrap-aggregator     # rebuild summaries + rankings + personas
docker compose down                              # stop (data volumes are kept)
```

## A8. After the cloud is up
- **RPis:** every Pi publishes to `wattwise.example.com:443` over WebSocket — new Pi →
  Part B; existing Pi → set the `mqtt:` block of `/config/wattwise_publisher.yaml` as in §5
  and restart the add-on.
- **Android app:** the default server URL is compiled in (`util/Constants.kt`,
  `res/xml/network_security_config.xml`). After A0, rebuild and reinstall the APK
  (`./gradlew assembleDebug` in `User Apps/Android/WattWiseUserApp`), or change the server
  address in the app's Settings on existing installs.

## A9. Cloud troubleshooting
| Symptom | Fix |
|---|---|
| `docker compose up` fails with `env file ... not found` | the `.env` files are missing — redo A3 |
| `cloudflared` restarting, log says token invalid / `Unauthorized` | wrong `CLOUDFLARE_TUNNEL_TOKEN` in `.env` — copy it again from A1 |
| `localhost/health` OK but the domain gives Cloudflare error 1033 / 502 | tunnel not connected or public-hostname URL wrong — `docker compose logs cloudflared`, re-check A1 step 3 (`wattwise-nginx-proxy:80`) |
| Domain gives `DNS_PROBE_FINISHED_NXDOMAIN` | nameservers not switched / domain not Active yet (A0) |
| backend stuck `unhealthy` / restarting | `docker compose logs backend`; usually MySQL still initialising on first boot — wait 2 min |
| Containers killed, "Service temporarily unavailable" | Docker has too little memory — Docker Desktop → Resources → Memory ≥ 4 GB |
| RPi: `WebSocket handshake error / 502` on `/mqtt` | the `/mqtt` route must reach nginx (`wattwise-nginx-proxy:80`), not the admin frontend |
| Everything stops when the lid closes | A6 |

---

# Part B — Deploy the publisher to a Home Assistant RPi

## Prerequisites
- SSH / terminal access to the HA OS Pi.
- The four fixed values for that participant (see §"Per-home values"):
  `home_id`, MQTT `host/port/user/pass`, InfluxDB `host/db/user/pass`, and the device
  `entity_id` ↔ `power_entity_id` mappings.
- The WattWise cloud reachable at **`https://wattwise.example.com`** (Cloudflare Tunnel) —
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
  host: "wattwise.example.com"          # the real domain (Part A)
  port: 443
  transport: "websockets"
  ws_path: "/mqtt"
  username: "<mqtt_username>"           # = home_id, e.g. home_001
  password: "<mqtt_password>"           # from Server Side/.env: MQTT_HOME_0NN_PASS
  tls: true
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
✅ MQTT connected to wattwise.example.com:443
InfluxDB ping: ✅ OK
🔄 Loop #1: 4 published, 0 errors
```

## 8. Cloud-side confirmation
Open `https://admin.wattwise.example.com`, log in with the **admin portal** credentials (separate from
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

Keep `appliance_key` values as the standard set; `mqtt.host` (`wattwise.example.com`, port 443, websockets, `/mqtt`, tls) and the
`influxdb` host/db/username (`localhost` / `homeassistant` / `homeassistant`) are the same for
every home. A ready-to-edit template with Asma's device mappings is in this folder's
`rpi_publisher_config.yaml` and the add-on's `publisher.default.yaml`.

## Troubleshooting
| Log line | Fix |
|---|---|
| Add-on not in the Store after copy | Run `ha addons reload` in the terminal (§3); the UI Reload alone isn't enough |
| `MQTT connect failed (rc=5)` | Wrong MQTT user/pass, or `home.id` ≠ MQTT username |
| `MQTT connection ... failed` / timeout | Cloud unreachable — check the Pi's internet, that the laptop stack + tunnel are up (Part A, A9), and that `mqtt` is `wattwise.example.com:443` websockets `/mqtt` tls |
| `InfluxDB ping: ❌ FAIL` | InfluxDB add-on stopped, or wrong `influxdb.password` |
| `Loop: 0 published` | a `power_entity_id` doesn't match the InfluxDB tag — redo §6 |

## Notes
- **TLS:** MQTT runs over WebSocket on port 443; Cloudflare terminates TLS, so credentials and
  readings are encrypted between the Pi and Cloudflare. A plain-TCP broker (`port 1883, transport
  tcp, tls false`) is only for a Pi on the same LAN as the laptop.
- **Updates:** to update the add-on later, re-run §2 (`git pull` + `cp`), then `ha addons reload`,
  then Rebuild/Update the add-on in the UI. The config in `/config/wattwise_publisher.yaml` is
  preserved across rebuilds.
