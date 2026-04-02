#!/bin/bash
# ============================================================
# WattWise RPi Publisher — Installation Script
# ============================================================
# Run on each Raspberry Pi to install the MQTT publisher.
# Requires: Python 3.9+, pip3
#
# Usage: bash install_publisher.sh
# ============================================================

set -e

INSTALL_DIR="/opt/wattwise"
CONFIG_DIR="/etc/wattwise"
SERVICE_NAME="wattwise-publisher"
LOG_FILE="/var/log/wattwise-publisher.log"

echo "⚡ WattWise RPi Publisher Installer"
echo "====================================="

# ── Python dependencies ──
echo "📦 Installing Python dependencies..."
pip3 install --upgrade paho-mqtt influxdb pyyaml || {
    sudo pip3 install --upgrade paho-mqtt influxdb pyyaml
}

# ── Create directories ──
sudo mkdir -p "$INSTALL_DIR"
sudo mkdir -p "$CONFIG_DIR"

# ── Copy publisher script ──
echo "📋 Copying publisher script..."
sudo cp rpi_mqtt_publisher.py "$INSTALL_DIR/"
sudo chmod +x "$INSTALL_DIR/rpi_mqtt_publisher.py"

# ── Copy example config if not present ──
if [ ! -f "$CONFIG_DIR/publisher.yaml" ]; then
    echo "📋 Copying example config to $CONFIG_DIR/publisher.yaml"
    sudo cp rpi_publisher_config.yaml "$CONFIG_DIR/publisher.yaml"
    echo "⚠️  IMPORTANT: Edit $CONFIG_DIR/publisher.yaml with your home_id, device entity IDs, and MQTT credentials!"
else
    echo "ℹ️  Config already exists at $CONFIG_DIR/publisher.yaml — skipping copy"
fi

# ── Create log file ──
sudo touch "$LOG_FILE"
sudo chown pi:pi "$LOG_FILE" 2>/dev/null || true

# ── Install systemd service ──
echo "🔧 Installing systemd service..."
sudo cp wattwise-publisher.service "/etc/systemd/system/$SERVICE_NAME.service"
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"

echo ""
echo "✅ Installation complete!"
echo ""
echo "Next steps:"
echo "  1. Edit your config: sudo nano $CONFIG_DIR/publisher.yaml"
echo "  2. Start the service: sudo systemctl start $SERVICE_NAME"
echo "  3. Check status: sudo systemctl status $SERVICE_NAME"
echo "  4. View logs: sudo journalctl -u $SERVICE_NAME -f"
echo ""
echo "MQTT topic format: wattwise/homes/{home_id}/devices/{device_id}/data"
