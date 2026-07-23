# How to Deploy the WattWise Publisher to a Home Assistant RPi

**Proven runbook** — this is the exact procedure used to get Asma Irfan's RPi (`home_001`)
publishing live data to the WattWise cloud. Follow it to onboard any new participant's
Raspberry Pi. Works on **Home Assistant OS** (no host `systemctl`; the publisher runs as a
Supervisor add-on).

> 🔒 Real passwords are **not** in this file. Fill each `<placeholder>` from the sources in
> §"Per-home values". Asma's actual values live in the gitignored `asma-home.secrets.local`.

---

## Prerequisites
- SSH / terminal access to the HA OS Pi.
- The four fixed values for that participant (see §"Per-home values"):
  `home_id`, MQTT `host/port/user/pass`, InfluxDB `host/db/user/pass`, and the device
  `entity_id` ↔ `power_entity_id` mappings.
- The WattWise cloud reachable at **`159.65.213.183:1883`** (droplet, plain MQTT/TCP).

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
  host: "159.65.213.183"                # WattWise droplet
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
✅ MQTT connected to 159.65.213.183:1883
InfluxDB ping: ✅ OK
🔄 Loop #1: 4 published, 0 errors
```

## 8. Cloud-side confirmation
Open `http://159.65.213.183:3000`, log in with the **admin portal** credentials (separate from
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

Keep `appliance_key` values as the standard set; `mqtt.host` (`159.65.213.183`) and the
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
