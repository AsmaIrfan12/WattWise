# WattWise Publisher — Home Assistant Add-on

Runs the WattWise RPi publisher as a proper Home Assistant add-on. Use this on any
Pi running **Home Assistant OS / Supervised**, where there is no host `systemctl`
and the SSH terminal is an ephemeral container.

The add-on:
- starts on boot and restarts automatically (Supervisor-managed),
- uses host networking so it reaches the InfluxDB add-on on `localhost:8086`,
- reads its config from `/config/wattwise_publisher.yaml` (edit it in the File editor /
  Studio Code Server / Samba add-on — secrets stay on the device, never in git).

## Install (local add-on)

1. **Get a file path into Home Assistant.** Install one of: **Samba share**, **File
   editor**, or **Studio Code Server** add-on (Settings → Add-ons → Add-on Store).
2. **Copy this folder to the add-ons directory** so it lands at:
   ```
   /addons/wattwise-publisher/
   ```
   - Via Samba: the `addons` share → create `wattwise-publisher` → copy these files in.
   - Via SSH (if your SSH add-on maps `/addons`):
     ```bash
     cp -r ~/wattwise/"Sensing Layer/hass-addon/wattwise-publisher" /addons/
     ```
3. **Reload the store:** Settings → Add-ons → Add-on Store → ⋮ (top-right) → **Reload**.
   "WattWise Publisher" appears under **Local add-ons**.
4. **Open it → Install.** Supervisor builds the image (first build pulls base + pip deps,
   takes a few minutes).
5. **Start it once** so it writes the default config, then **Stop** it.
6. **Edit `/config/wattwise_publisher.yaml`** (File editor):
   - set `mqtt.password` to the value from the researcher,
   - confirm the device `entity_id` (cloud match) and `power_entity_id` (InfluxDB tag).
7. **Start** the add-on. Enable **Start on boot** and **Watchdog** in its toolbar.

## Verify

- Add-on **Log** tab shows:
  ```
  ✅ Config loaded ... (home_id=home_001, mqtt_user=home_001)
  📊 InfluxDB reader initialised: localhost:8086/homeassistant
  InfluxDB ping: ✅ OK
  ✅ MQTT connected to www.talk2futurebuildings.systems:443
  🔄 Loop #1: 4 published, 0 errors
  ```
- Cloud: the home's dashboard / admin portal shows live wattage within ~5 minutes.

## Troubleshooting

| Symptom in the add-on log | Fix |
|---|---|
| `mqtt.password ... placeholder` then exit | You haven't edited `/config/wattwise_publisher.yaml` yet (steps 5–6) |
| `InfluxDB ping: ❌ FAIL` | InfluxDB add-on stopped, or it needs auth → set `influxdb.username/password`. Confirm 8086 is reachable (host_network is on) |
| `Loop: ... 0 published` / always 0 W | `power_entity_id` doesn't match the InfluxDB tag — check the InfluxDB add-on (Chronograf): `SHOW TAG VALUES FROM "W" WITH KEY = "entity_id"` |
| `MQTT connect failed (rc=5)` | Wrong MQTT username/password |

## Deploying to other real RPis

Copy this same folder to each Pi's `/addons/`. The only per-home edits live in
`/config/wattwise_publisher.yaml`: `home.id` / `mqtt.username` / `mqtt.password` and the
device `entity_id` (cloud) ↔ `power_entity_id` (InfluxDB tag) mappings.
