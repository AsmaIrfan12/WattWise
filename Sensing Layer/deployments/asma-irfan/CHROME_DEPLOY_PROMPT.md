# Claude-in-Chrome Deployment Prompt — Asma Irfan's RPi

Paste the block below into Claude running in the Chrome extension, with Asma's
Home Assistant already open in the active tab
(`https://homeassistant.tail5340f7.ts.net/`).

> ⚠️ Contains a real MQTT password — only paste into your own Claude session.

---

You are deploying the **WattWise RPi MQTT publisher** onto this Raspberry Pi, which
is running Home Assistant. You are operating the browser tab that has this RPi's
Home Assistant open at `https://homeassistant.tail5340f7.ts.net/`. Work
methodically through the phases below. **Do not skip the discovery phase** — the
publisher will silently send zeros if the InfluxDB entity tags are wrong.

## Background

- This RPi belongs to participant **Asma Irfan**. It collects live energy data from
  Tapo smart plugs into Home Assistant's local **InfluxDB add-on** (slug
  `a0d7b954_influxdb`, database `homeassistant`).
- A small Python service (`rpi_mqtt_publisher.py`) must run on this RPi. Every 30s it
  reads the latest wattage per appliance from the local InfluxDB and publishes it over
  authenticated MQTT (WebSocket, TLS) to the WattWise cloud at
  `www.talk2futurebuildings.systems`, which stores it against Asma's account.
- The cloud backend matches each reading to a device **by the `entity_id` string in the
  payload**. Those strings are fixed (listed below) — they must not change.

## Fixed values (already confirmed from the WattWise admin/server side)

| Setting | Value |
|---|---|
| MQTT broker host | `www.talk2futurebuildings.systems` (port 443, websockets, path `/mqtt`, TLS on) |
| MQTT username | `home_001` |
| MQTT password | (the researcher gives you this — set it on the RPi only; never paste into a committed file) |
| Topic home id | `home_001` (required by broker ACL — NOT the numeric id) |
| InfluxDB | `localhost:8086`, database `homeassistant`, no auth (verify) |

Asma's 4 registered devices — the **`entity_id`** is the cloud-match string (keep exactly),
the **InfluxDB tag** is the real HA name (confirmed in Chronograf):

| Appliance | entity_id (cloud match — keep) | InfluxDB entity_id tag (power_entity_id) |
|---|---|---|
| Airfryer | `sensor.airfryer_04d1f4` | `airfryer_current_consumption` |
| Dishwasher | `sensor.dishwasher_aebe90` | `dishwasher_current_consumption` |
| Microwave | `sensor.microwave_821ec2` | `microwave_current_consumption` |
| Washing Machine | `sensor.washing_machine_b612c5` | `washing_machine_current_consumption` |

(HA InfluxDB also has `kettle_current_consumption` and `toaster_current_consumption`,
but Asma has no kettle/toaster registered in the cloud, so they are not published.)

## Phase 1 — Discover & verify the InfluxDB entity tags (browser)

1. In Home Assistant, open the **InfluxDB add-on** (Settings → Add-ons → InfluxDB →
   "Open Web UI", which opens Chronograf). If a different query UI is present, use
   whatever lets you run InfluxQL against the `homeassistant` database.
2. Run, against database `homeassistant`:
   ```
   SHOW MEASUREMENTS
   SHOW TAG VALUES FROM "W" WITH KEY = "entity_id"
   ```
   (`W` is the watts measurement. If there is no `W`, try `SHOW MEASUREMENTS` and look
   for the power unit measurement.)
3. Confirm the 4 tags match the table above (`airfryer_current_consumption`, etc.).
   These were already verified in Chronograf — this step is just a re-check that the
   names haven't changed and that data is flowing.
4. Sanity-check there is **recent** data, e.g.:
   ```
   SELECT "value" FROM "W" WHERE "entity_id" = 'airfryer_current_consumption' ORDER BY time DESC LIMIT 5
   ```
   You should see non-zero recent wattage when that appliance is on.
5. If any of the 4 tags is missing or renamed, note it and adjust `power_entity_id`
   accordingly in Phase 2. The committed config already has the confirmed names, so
   normally no change is needed.

> Cross-check (optional): Developer Tools → States, filter by the appliance name, and
> confirm the power sensor exists and updates.

## Phase 2 — Deploy the publisher (needs a shell on the RPi)

You need a terminal on the RPi. Use the **Advanced SSH & Web Terminal** add-on
(Settings → Add-ons) if it's installed — open its Web UI to get a shell. If no terminal
add-on is available, STOP and report that one must be installed (or SSH access provided);
do not attempt to deploy without a shell.

In the terminal:

```bash
# 1. Clone the WattWise repo (contains the publisher + Asma's pre-filled bundle)
cd ~
git clone https://github.com/AsmaIrfan12/WattWise.git wattwise 2>/dev/null || (cd ~/wattwise && git pull)
cd ~/wattwise/"Sensing Layer/deployments/asma-irfan"

# 2. Set the MQTT password (the committed config has a placeholder for safety).
#    Replace <MQTT_PASSWORD> with the value the researcher gave you:
sed -i 's|REPLACE_WITH_YOUR_MQTT_PASSWORD|<MQTT_PASSWORD>|' rpi_publisher_config.yaml

# 3. (Usually skip.) The committed config already uses the confirmed InfluxDB tags
#    (airfryer_current_consumption, etc.). Only edit if Phase 1 showed a renamed tag:
nano rpi_publisher_config.yaml   # optional review

# 4. Install: copies the script to /opt/wattwise, the config to /etc/wattwise,
#    installs python deps, and registers the systemd service.
bash install_publisher.sh

# 5. Start the service (the installer leaves it stopped until the password is set)
sudo systemctl restart wattwise-publisher
```

If `git clone` is blocked (private repo / no auth), generate a GitHub personal-access
token or ask the researcher; the publisher script and bundle live under
`Sensing Layer/deployments/asma-irfan/` in the repo.

## Phase 3 — Verify it works

```bash
sudo systemctl status wattwise-publisher          # expect: active (running)
sudo journalctl -u wattwise-publisher -n 50 -f    # live logs
```

A healthy run shows:
```
✅ Config loaded from /etc/wattwise/publisher.yaml (home_id=home_001, mqtt_user=home_001)
📊 InfluxDB reader initialised: localhost:8086/homeassistant
InfluxDB ping: ✅ OK
✅ MQTT connected to www.talk2futurebuildings.systems:443
🔄 Loop #1: 4 published, 0 errors
```

Then confirm in the browser that the cloud received it: open
`https://www.talk2futurebuildings.systems/` and check Asma's dashboard shows live
wattage updating within ~5 minutes (or log in to the WattWise app / admin portal).

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `MQTT connect failed (rc=5)` | Wrong username/password — username must be `home_001`; re-check the password from the researcher |
| `MQTT connect failed (rc=3)` | Broker unreachable — check RPi internet / Cloudflare |
| `InfluxDB ping: ❌ FAIL` | InfluxDB add-on stopped, or it requires auth → fill `influxdb.username/password` |
| `Loop: 0 published` or always 0 W | `power_entity_id` doesn't match the real InfluxDB tag — redo Phase 1 |
| Readings flow but don't show on Asma's dashboard | `entity_id` was changed — it MUST stay `sensor.<appliance>_<hex>` exactly |

## Report back

When done, report:
1. The exact InfluxDB `entity_id` tag you used for each of the 4 appliances.
2. Whether the InfluxDB add-on needed auth.
3. The final `systemctl status` and the last ~10 log lines.
4. Whether live data appeared on Asma's cloud dashboard.
