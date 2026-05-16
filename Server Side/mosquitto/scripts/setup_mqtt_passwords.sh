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

# The broker reads its password file from the `mosquitto_secret` named volume
# (provisioned by the `mosquitto-init` compose service). All writes therefore
# happen *inside* a container that mounts that volume rw — never on a host file.
PASSWD_FILE="/secret/passwd"
ACL_FILE="./mosquitto/config/acl.conf"

# Run mosquitto_passwd against the secret volume via the init service.
passwd_in_volume() {
    docker compose run --rm --no-deps --entrypoint mosquitto_passwd mosquitto-init "$@"
}

# Load MQTT credentials from .env
if [ -f ".env" ]; then
    export $(grep -E "^MQTT_(USERNAME|PASSWORD)" .env | xargs)
fi

BACKEND_USER="${MQTT_USERNAME:-wattwise_backend}"
BACKEND_PASS="${MQTT_PASSWORD:-WattWise_MQTT_Backend_2026!}"
ADMIN_PASS="${MQTT_ADMIN_PASS:-WattWise_MQTT_Admin_2026!}"

case "${1:-init}" in
  init)
    echo "🔑 Creating MQTT password file in mosquitto_secret volume..."
    # -c (re)creates the file with the backend user, then add admin monitor.
    passwd_in_volume -b -c "$PASSWD_FILE" "$BACKEND_USER" "$BACKEND_PASS"
    passwd_in_volume -b "$PASSWD_FILE" "wattwise_admin" "$ADMIN_PASS"
    echo "✅ MQTT authentication configured"
    echo "   Backend user: $BACKEND_USER"
    echo "   Admin user:   wattwise_admin"
    echo ""
    echo "ℹ️  Now run: docker compose restart mosquitto"
    ;;

  add-home)
    HOME_ID="${2:-}"
    if [ -z "$HOME_ID" ]; then
      echo "❌ Usage: $0 add-home <home_id>  (e.g. home_016)"
      exit 1
    fi

    # Username matches acl.conf format: home_NNN (not rpi_home_NNN)
    HOME_USER="${HOME_ID}"
    HOME_PASS=$(openssl rand -base64 24)

    echo "🏠 Adding MQTT user for home: $HOME_ID"
    passwd_in_volume -b "$PASSWD_FILE" "$HOME_USER" "$HOME_PASS"

    # Append ACL entry only if not already present
    if ! grep -q "user ${HOME_USER}" "$ACL_FILE"; then
      cat >> "$ACL_FILE" << EOF

# ── ${HOME_ID} ───────────────────────────────────────────
user ${HOME_USER}
topic write wattwise/homes/${HOME_USER}/#
topic read  wattwise/homes/${HOME_USER}/commands/#
EOF
      echo "✅ ACL entry added for $HOME_USER"
    else
      echo "ℹ️  ACL entry already exists for $HOME_USER — skipped"
    fi

    echo "✅ Home $HOME_ID MQTT user created"
    echo "   Username: $HOME_USER"
    echo "   Password: $HOME_PASS"
    echo ""
    echo "👀 Save these credentials — they are shown only once!"
    echo "ℹ️  Add MQTT_${HOME_ID^^}_PASS='$HOME_PASS' to Server Side/.env"
    echo "ℹ️  Run: docker compose restart mosquitto  (to apply ACL changes)"
    ;;

  list)
    echo "📋 MQTT password file contents (usernames):"
    docker compose run --rm --no-deps --entrypoint sh mosquitto-init \
      -c "cut -d: -f1 $PASSWD_FILE 2>/dev/null" || echo "(empty or not found)"
    ;;

  *)
    echo "Usage: $0 {init|add-home <home_id>|list}"
    exit 1
    ;;
esac
