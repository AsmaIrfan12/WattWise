# WattWise Participant Quick-Start Checklist

**Research Lead:** Mr. Suhas Devmane, Cardiff University | asmairfan12@gmail.com  
**Full setup guide:** see `PARTICIPANT_SETUP.md`

---

## RPi Setup

- [ ] Receive credentials slip (home ID, MQTT username, MQTT password, app login)
- [ ] SSH into Raspberry Pi: `ssh pi@homeassistant.local`
- [ ] Clone/pull repo: `cd ~ && git clone ... && cd "Sensing Layer"`
- [ ] Run installer: `bash install_publisher.sh`
- [ ] Edit config: `sudo nano /etc/wattwise/publisher.yaml`
  - [ ] Set `home.id` (e.g. `3`)
  - [ ] Set `mqtt.username` (e.g. `home_003`)
  - [ ] Set `mqtt.password` (from credentials slip)
  - [ ] Set `mqtt.host: www.talk2futurebuildings.systems`
  - [ ] Update device `entity_id` values from Home Assistant
- [ ] Start publisher: `sudo systemctl start wattwise-publisher`
- [ ] Verify running: `sudo journalctl -u wattwise-publisher -f` — should show `MQTT connected`

## Android App

- [ ] Enable "Install unknown apps" on Android device
- [ ] Install APK file provided by researcher
- [ ] Open WattWise → Settings → confirm server URL: `https://www.talk2futurebuildings.systems`
- [ ] Log in with your email/password from credentials slip
- [ ] Dashboard loads and shows energy charts

## Verification (do with participant present)

- [ ] Check admin panel shows this home's live data
- [ ] Send test notification → participant sees it in app tray within ~15 min
- [ ] Participant can view their usage in the Devices tab
- [ ] Participant can see community leaderboard in Rankings tab

## If Something Goes Wrong

| Problem | Action |
|---------|--------|
| Service not running | `sudo systemctl restart wattwise-publisher` |
| MQTT auth failed (rc=5) | Re-check username/password in `/etc/wattwise/publisher.yaml` |
| No data on dashboard | Wait 5 min for first reading cycle; check publisher logs |
| App blank screen | Tap refresh; check server URL in Settings |
| Contact researcher | asmairfan12@gmail.com |
