# WattWise — Participant RPi Setup Guide

**Research Lead:** Mr. Suhas Devmane, Cardiff University  
**Contact:** asmairfan12@gmail.com  
**Platform:** https://www.talk2futurebuildings.systems

---

## What you will need

- Raspberry Pi running Home Assistant (already installed)
- Tapo smart plugs already paired to Home Assistant
- The **home ID**, **MQTT username**, and **MQTT password** provided by the researcher
- Internet access on the RPi

---

## Step 1 — Receive your credentials

The researcher will give you a slip with:

| Item | Example value |
|------|---------------|
| Home ID | `home_003` |
| MQTT username | `home_003` |
| MQTT password | `WW_Home003_RPi_2026!` |
| WattWise App username | your email address |
| WattWise App password | (set during account creation) |

Keep this slip safe — do not share it.

---

## Step 2 — Install the publisher on your RPi

Open a terminal on your Raspberry Pi (SSH in or use the keyboard/monitor):

```bash
# Download the publisher files
cd ~
git clone https://github.com/Suhass-Devmane/WattWise.git wattwise
# OR if already cloned:
cd wattwise && git pull

cd "Sensing Layer"
bash install_publisher.sh
```

The installer will:
- Install Python dependencies (`paho-mqtt`, `influxdb`, `pyyaml`)
- Copy the publisher script to `/opt/wattwise/`
- Create a config template at `/etc/wattwise/publisher.yaml`
- Register a systemd service (`wattwise-publisher`)

---

## Step 3 — Edit your config file

```bash
sudo nano /etc/wattwise/publisher.yaml
```

Find and update these sections:

### Home identity
```yaml
home:
  id: "3"            # ← your numeric home ID (e.g. 3 for home_003)
  name: "Home 3 - Cardiff"
```

### MQTT credentials
```yaml
mqtt:
  host: "www.talk2futurebuildings.systems"
  port: 443
  transport: "websockets"
  ws_path: "/mqtt"
  username: "home_003"                 # ← your MQTT username
  password: "WW_Home003_RPi_2026!"    # ← your MQTT password
  tls: true
```

### Device entity IDs

Each device needs the entity_id from Home Assistant.

**How to find your entity IDs:**
1. Open Home Assistant in a browser (`http://homeassistant.local:8123`)
2. Go to **Developer Tools** → **States**
3. Filter by your device name (e.g. "kettle")
4. Copy the entity_id (e.g. `sensor.tapo_kettle_current_consumption`)

Update each device block:
```yaml
    - id: "kettle"
      entity_id: "sensor.tapo_kettle_current_consumption"   # ← your entity_id
```

Save and exit: `Ctrl+O`, `Enter`, `Ctrl+X`

---

## Step 4 — Start the publisher

```bash
sudo systemctl start wattwise-publisher
sudo systemctl status wattwise-publisher
```

You should see `Active: active (running)`.

Check live logs:
```bash
sudo journalctl -u wattwise-publisher -f
```

A healthy publisher prints lines like:
```
✅ MQTT connected to www.talk2futurebuildings.systems:443
📊 InfluxDB reader initialised
📤 Published kettle: {"power_watts": 2100.0, ...}
```

---

## Step 5 — Install the WattWise app

1. Enable **Install unknown apps** on your Android device  
   (Settings → Apps → Special app access → Install unknown apps → enable for your browser or file manager)
2. Open the APK file the researcher sent you and install it
3. Open **WattWise** → tap **Settings** (gear icon)
4. Verify the Server URL is: `https://www.talk2futurebuildings.systems`
5. Tap **Log in** → enter your email and password

The dashboard should load and show your energy data within a few minutes.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `MQTT connect failed (rc=5)` | Wrong username or password — re-check Step 3 |
| `MQTT connect failed (rc=3)` | Broker unreachable — check RPi has internet access |
| `InfluxDB query error` | Home Assistant InfluxDB not running — check HA add-ons |
| App shows blank screen | Tap the refresh icon; check server URL in Settings |
| No data on dashboard | Wait 5 minutes for first readings; check publisher logs |
| `Config error: mqtt.password is blank` | You skipped Step 3 — fill in the password |

---

## Stopping / restarting the publisher

```bash
sudo systemctl stop wattwise-publisher    # stop
sudo systemctl restart wattwise-publisher # restart (after config changes)
sudo systemctl disable wattwise-publisher # prevent autostart on boot
```

---

## What data is collected?

The publisher sends **only** energy readings (Watts, Amps, kWh) from your smart plugs — no other data. Readings are labelled with your home ID, not your name. The research team at Cardiff University cannot identify you from the energy data alone.

For questions or technical problems, contact:  
**Mr. Suhas Devmane** — asmairfan12@gmail.com
