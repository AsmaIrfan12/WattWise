# WattWise RPi Publisher — Deploy Guide

This folder is a **working, proven** deployment for one Raspberry Pi running Home
Assistant. It reads live appliance wattage from HA's local InfluxDB and publishes it
to the WattWise cloud over MQTT every 30 s.

- **`asma-irfan/` is a real, filled example** (home `home_001`). Copy it to make a new RPi.
- Secrets (MQTT + InfluxDB passwords) are **placeholders here** — you fill them on the
  device. Never commit real passwords.

---

## What you need before starting

| Item | Where it comes from |
|---|---|
| HA + InfluxDB add-on already storing Tapo data | the RPi |
| The home registered in the WattWise cloud (gives device `entity_id`s) | admin portal / researcher |
| `home.id` + MQTT username + MQTT password | researcher (must match the broker ACL) |
| InfluxDB username + password | the RPi's HA config (see step 3) |

---

## Deploy on a Home Assistant OS RPi (the proven path)

### 1. Get a terminal
Install the **Advanced SSH & Web Terminal** add-on (Settings → Add-ons) and open it.

### 2. Clone the repo
```bash
cd ~
git clone https://github.com/AsmaIrfan12/WattWise.git wattwise || (cd ~/wattwise && git pull)
cd ~/wattwise/"Sensing Layer/deployments/asma-irfan"
pip3 install paho-mqtt influxdb pyyaml      # usually already present
```

### 3. Find this RPi's InfluxDB credentials
The HA InfluxDB add-on has **auth enabled**, so the publisher needs a username/password.
They're the same ones HA uses to write:
```bash
grep -iA15 'influxdb:' /config/configuration.yaml 2>/dev/null || grep -iA15 'influxdb:' /homeassistant/configuration.yaml
grep -i influxdb_password /config/secrets.yaml 2>/dev/null || grep -i influxdb_password /homeassistant/secrets.yaml
```
Note the `username` (usually `homeassistant`) and the `influxdb_password` value.

Confirm they work (replace `PASS`):
```bash
curl -s -G 'http://localhost:8086/query?db=homeassistant' -u 'homeassistant:PASS' \
  --data-urlencode "q=SELECT \"value\" FROM \"W\" WHERE entity_id='microwave_current_consumption' ORDER BY time DESC LIMIT 1"; echo
```
A `"values":[[ ...,<wattage> ]]` response = good. (If you get an SSL error, the add-on
is HTTPS-only → use `https://` + `-k` here and set `ssl: true` in the config below.)

### 4. Fill in the config
```bash
nano rpi_publisher_config.yaml
```
Set the four placeholders:
```yaml
influxdb:
  username: "homeassistant"
  password: "<influxdb_password from step 3>"
mqtt:
  password: "<your MQTT password from the researcher>"
```
Also confirm, per device, that `power_entity_id` matches the InfluxDB tag
(`SHOW TAG VALUES FROM "W" WITH KEY = "entity_id"` in the InfluxDB add-on) and that
`entity_id` matches the cloud device (leave it unless the researcher says otherwise).

### 5. Test in the foreground
```bash
python3 rpi_mqtt_publisher.py --config rpi_publisher_config.yaml
```
Success looks like:
```
✅ MQTT connected to <host>:443
InfluxDB ping: ✅ OK
🔄 Loop #1: 4 published, 0 errors
```
`Ctrl+C` to stop once you're happy. The home shows **online** in the admin portal within
a minute. (A foreground run stops when you close the terminal — make it permanent next.)

### 6. Make it permanent (survives reboots)
HA OS has no `systemctl`, so run it as the **WattWise Publisher add-on**:
see [`../../hass-addon/wattwise-publisher/README.md`](../../hass-addon/wattwise-publisher/README.md).
Put the **same** filled values into `/config/wattwise_publisher.yaml` there.

---

## Deploy on a normal Raspberry Pi OS / Linux host (systemd)
If the Pi is *not* Home Assistant OS and you have a real shell with `systemctl`:
```bash
cd ~/wattwise/"Sensing Layer/deployments/asma-irfan"
nano rpi_publisher_config.yaml          # fill the placeholders (step 4 above)
bash install_publisher.sh               # installs deps + config + systemd service
sudo systemctl restart wattwise-publisher
sudo journalctl -u wattwise-publisher -f
```

---

## Make a new RPi from this one
```bash
cd "Sensing Layer"
cp -r deployments/asma-irfan deployments/<new-home>
# refresh the shared script/installer in case they changed:
cp rpi_mqtt_publisher.py install_publisher.sh wattwise-publisher.service deployments/<new-home>/
# then edit deployments/<new-home>/rpi_publisher_config.yaml:
#   home.id + mqtt.username + mqtt.password   (must match the broker ACL)
#   each device entity_id (cloud) + power_entity_id (HA InfluxDB tag)
#   influxdb.username + influxdb.password
```
Keep `appliance_key` values unchanged — they map to WattWise's known appliance set.

---

## Gotchas we hit (so you don't again)

| Symptom | Cause → fix |
|---|---|
| `WebSocket handshake error` / `502` on connect | The cloud `/mqtt` path isn't routed to nginx→mosquitto. Point the tunnel/proxy `/mqtt` at nginx:80 (Cloudflare: add a `/mqtt` path rule → `http://localhost:80`). |
| `Loop: 0 published` but `MQTT connected` + `ping OK` | InfluxDB **auth** — username/password missing or wrong. The `/ping` check passes without auth, but queries don't. Fill `influxdb.username/password` (step 3). |
| `0 published` and curl returns data fine | A `power_entity_id` doesn't match the InfluxDB tag — recheck `SHOW TAG VALUES`. |
| Home never goes online | "online" = a reading in the last 5 min. Confirm the loop says `N published, 0 errors`. |
| `MQTT connect failed (rc=5)` | Wrong MQTT username/password, or `home.id` ≠ MQTT username (ACL mismatch). |

## Moving the cloud to a DigitalOcean droplet
Only `mqtt.host` changes — set it to the droplet's domain/IP. Keep `port: 443` +
`tls: true` + `ws_path: /mqtt` if TLS is fronted by nginx/Caddy/Cloudflare; ensure that
front door routes `/mqtt` to mosquitto's WebSocket (9001). For a same-network/dev broker,
use `port: 1883`, `transport: "tcp"`, `tls: false` instead.
