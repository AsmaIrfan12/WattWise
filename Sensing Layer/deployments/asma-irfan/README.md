# WattWise RPi Deployment Bundle — Asma Irfan

Self-contained, copy-ready bundle for one real Raspberry Pi running Home Assistant.
Copy this **entire folder** to the RPi and run the installer. Use it as the template
for every other real RPi (see [Cloning for another RPi](#cloning-for-another-rpi)).

| Item | Value |
|------|-------|
| Participant | Asma Irfan |
| Cloud platform | `https://www.talk2futurebuildings.systems` |
| MQTT topic | `wattwise/homes/{home_id}/devices/{device_id}/data` |
| Publish interval | 30 s |

## What's in this folder

| File | Purpose |
|------|---------|
| `rpi_mqtt_publisher.py` | The publisher (canonical copy — reads local InfluxDB → cloud MQTT) |
| `rpi_publisher_config.yaml` | Config **pre-filled for Asma** with `<PLACEHOLDER>`s to complete |
| `install_publisher.sh` | Installs deps, copies files to `/opt/wattwise` + `/etc/wattwise`, registers the service |
| `wattwise-publisher.service` | systemd unit (auto-start on boot, restart on failure) |

> The script and service file are **exact copies** of the canonical files in
> `Sensing Layer/`. If you update those, re-copy them into this folder before
> redeploying (see the clone command below).

## Deploy on Asma's RPi

```bash
# 1. On the RPi (HA terminal add-on or SSH), clone the repo:
cd ~
git clone https://github.com/AsmaIrfan12/WattWise.git wattwise || (cd ~/wattwise && git pull)
cd ~/wattwise/"Sensing Layer/deployments/asma-irfan"

# 2. Run the installer (copies script + config, installs deps, registers service):
bash install_publisher.sh
```

The installer stops before starting the service because the config still has
placeholders. Fill them in:

```bash
sudo nano /etc/wattwise/publisher.yaml
```

Set the three required values (get them from the admin portal / your credentials slip):

```yaml
home:
  id: "<ASMA_HOME_ID>"                 # numeric homes.id from the admin portal
mqtt:
  username: "<ASMA_MQTT_USERNAME>"      # e.g. home_003 — must match broker ACL
  password: "REPLACE_WITH_YOUR_MQTT_PASSWORD"
```

Then confirm each device `entity_id` matches Asma's Home Assistant entities
(Developer Tools → States, or the InfluxDB add-on Chronograf:
`SELECT * FROM "W" LIMIT 5`).

Start it:

```bash
sudo systemctl start wattwise-publisher
sudo systemctl status wattwise-publisher        # expect: active (running)
sudo journalctl -u wattwise-publisher -f        # live logs
```

Healthy output looks like:

```
✅ Config loaded from /etc/wattwise/publisher.yaml (home_id=3, mqtt_user=home_003)
📊 InfluxDB reader initialised: localhost:8086/homeassistant
✅ MQTT connected to www.talk2futurebuildings.systems:443
📤 Published kettle: {"power_watts": 2100.0, ...}
```

## Verify data is flowing

- **Logs**: `🔄 Loop #N: 6 published, 0 errors`
- **Cloud**: Asma's dashboard in the app, or admin portal, shows live wattage within ~5 min.
- **Local InfluxDB** (sanity check the source): open the `a0d7b954_influxdb` add-on UI
  and confirm the `W` / `kWh` measurements are receiving fresh Tapo readings.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `mqtt.password is blank or still contains the placeholder` | You skipped the config edit — set username/password |
| `MQTT connect failed (rc=5)` | Wrong MQTT username/password |
| `MQTT connect failed (rc=3)` | Broker unreachable — check RPi internet |
| `InfluxDB ping: ❌ FAIL` | InfluxDB add-on not running, or auth required — set `influxdb.username/password` |
| `No power data for <device>` | `entity_id` doesn't match HA — verify in Developer Tools → States |

## Cloning for another RPi

Each real RPi gets its own bundle so credentials and entity IDs never collide:

```bash
cd "Sensing Layer"

# 1. Copy this bundle under the new participant's name
cp -r deployments/asma-irfan deployments/<participant-name>

# 2. Refresh the script/service from canonical (in case they changed)
cp rpi_mqtt_publisher.py wattwise-publisher.service install_publisher.sh \
   deployments/<participant-name>/

# 3. Edit deployments/<participant-name>/rpi_publisher_config.yaml:
#    - home.id, home.name
#    - mqtt.username / mqtt.password
#    - device entity_id values for that home
```

Keep `appliance_key` values unchanged — they map to WattWise's known appliance set.
Never commit real MQTT passwords; leave the placeholder and fill it in on the device.
