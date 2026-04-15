#!/bin/bash
# ============================================================
# WattWise MQTT Password Setup Script
# Author: Suhas Devmane, Cardiff University, UK
# ============================================================
# Run from: Server Side/
# Usage:
#   1) Initial setup:     ./mosquitto/scripts/setup_mqtt_passwords.sh init
#   2) Add a new home:    ./mosquitto/scripts/setup_mqtt_passwords.sh add-home <home_id>
#   3) List users:        ./mosquitto/scripts/setup_mqtt_passwords.sh list
# ============================================================

set -euo pipefail

PASSWD_FILE="./mosquitto/config/passwd"
ACL_FILE="./mosquitto/config/acl.conf"

# Load MQTT credentials from .env
if [ -f ".env" ]; then
    export $(grep -E "^MQTT_(USERNAME|PASSWORD)" .env | xargs)
fi

BACKEND_USER="${MQTT_USERNAME:-wattwise_backend}"
BACKEND_PASS="${MQTT_PASSWORD:-WattWise_MQTT_Backend_2026!}"
ADMIN_PASS="${MQTT_ADMIN_PASS:-WattWise_MQTT_Admin_2026!}"

case "${1:-init}" in
  init)
    echo "🔑 Creating MQTT password file..."
    # Create/reset passwd file
    touch "$PASSWD_FILE"
    # Add backend user
    docker compose run --rm mosquitto mosquitto_passwd -b "$PASSWD_FILE" "$BACKEND_USER" "$BACKEND_PASS"
    # Add admin monitor user
    docker compose run --rm mosquitto mosquitto_passwd -b "$PASSWD_FILE" "wattwise_admin" "$ADMIN_PASS"
    echo "✅ MQTT authentication configured"
    echo "   Backend user: $BACKEND_USER"
    echo "   Admin user:   wattwise_admin"
    echo ""
    echo "ℹ️  Now run: docker compose restart mosquitto"
    ;;

  add-home)
    HOME_ID="${2:-}"
    if [ -z "$HOME_ID" ]; then
      echo "❌ Usage: $0 add-home <home_id>"
      exit 1
    fi

    HOME_USER="rpi_home_${HOME_ID}"
    HOME_PASS=$(openssl rand -base64 24)

    echo "🏠 Adding MQTT user for home: $HOME_ID"
    docker compose run --rm mosquitto mosquitto_passwd -b "$PASSWD_FILE" "$HOME_USER" "$HOME_PASS"

    # Append ACL entry
    cat >> "$ACL_FILE" << EOF

# Home ${HOME_ID}
user ${HOME_USER}
topic write wattwise/homes/${HOME_ID}/#
topic read  wattwise/homes/${HOME_ID}/commands/#
EOF

    echo "✅ Home $HOME_ID MQTT user created"
    echo "   Username: $HOME_USER"
    echo "   Password: $HOME_PASS"
    echo ""
    echo "👀 Save these credentials — they are shown only once!"
    echo "ℹ️  Run: docker compose restart mosquitto  (to apply ACL changes)"
    ;;

  list)
    echo "📋 MQTT password file contents:"
    cat "$PASSWD_FILE" 2>/dev/null || echo "(empty or not found)"
    ;;

  *)
    echo "Usage: $0 {init|add-home <home_id>|list}"
    exit 1
    ;;
esac
