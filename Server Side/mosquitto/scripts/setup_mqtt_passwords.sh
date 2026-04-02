#!/bin/bash
# ==============================================================
# WattWise MQTT Password Setup Script
# ==============================================================
# Run inside the Mosquitto container OR on the host after install.
# Creates the passwd file with all required user accounts.
#
# Usage (Docker):
#   docker compose exec wattwise-mqtt bash /mosquitto/scripts/setup_mqtt_passwords.sh
#
# Usage (host):
#   bash setup_mqtt_passwords.sh
# ==============================================================

PASSWD_FILE="/mosquitto/config/passwd"

echo "⚡ WattWise MQTT Password Setup"
echo "================================="

# --- Backend service account ---
echo "Creating backend service account..."
mosquitto_passwd -b "$PASSWD_FILE" wattwise_backend "${MQTT_BACKEND_PASSWORD:-$(openssl rand -hex 16)}"

# --- Admin account ---
echo "Creating admin account..."
mosquitto_passwd -b "$PASSWD_FILE" wattwise_admin "${MQTT_ADMIN_PASSWORD:-$(openssl rand -hex 16)}"

# --- Home accounts ---
# Each home gets a unique credential. Add new homes here as they join.
echo "Creating home accounts..."
mosquitto_passwd -b "$PASSWD_FILE" home_001 "${MQTT_HOME_001_PASSWORD:-$(openssl rand -hex 16)}"
mosquitto_passwd -b "$PASSWD_FILE" home_002 "${MQTT_HOME_002_PASSWORD:-$(openssl rand -hex 16)}"

echo ""
echo "✅ MQTT passwords created in $PASSWD_FILE"
echo ""
echo "⚠️  IMPORTANT: Save the generated passwords in a secure secrets manager."
echo "   Set these as environment variables in your .env file:"
echo "   MQTT_BACKEND_PASSWORD, MQTT_ADMIN_PASSWORD, MQTT_HOME_001_PASSWORD, etc."
echo ""
echo "   Then set the same MQTT_HOME_NNN_PASSWORD in /etc/wattwise/publisher.yaml on each RPi."
