#!/usr/bin/env sh
# WattWise Publisher — Home Assistant add-on entrypoint
set -e

CONFIG_FILE="/config/wattwise_publisher.yaml"

# On first run, drop the editable config into /config (visible in File editor / Samba).
if [ ! -f "${CONFIG_FILE}" ]; then
  echo "[wattwise] No ${CONFIG_FILE} yet — installing the default template."
  cp /app/publisher.default.yaml "${CONFIG_FILE}"
  echo "[wattwise] ----------------------------------------------------------------"
  echo "[wattwise] EDIT ${CONFIG_FILE}:"
  echo "[wattwise]   • set mqtt.password  (the value from the researcher)"
  echo "[wattwise]   • confirm the device entity_id / power_entity_id mappings"
  echo "[wattwise] Then restart this add-on."
  echo "[wattwise] ----------------------------------------------------------------"
fi

echo "[wattwise] Starting publisher with ${CONFIG_FILE}"
exec python3 /app/rpi_mqtt_publisher.py --config "${CONFIG_FILE}"
