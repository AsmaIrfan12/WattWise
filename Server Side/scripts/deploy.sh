#!/usr/bin/env bash
# =============================================================================
# WattWise — DigitalOcean Droplet Setup Script
# =============================================================================
# Run this ONCE on a fresh Ubuntu 22.04 droplet as root or sudo user.
# After this script completes:
#   1. Edit Server Side/.env with your actual credentials
#   2. Run:  cd "Server Side" && docker compose -f docker-compose.yml -f docker-compose.production.yml up -d --build
#
# Usage (from repo root on the droplet):
#   bash "Server Side/scripts/deploy.sh"
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVER_DIR="$(dirname "$SCRIPT_DIR")"

echo "===> WattWise DigitalOcean Setup"
echo "      Server directory: $SERVER_DIR"
echo ""

# ── 1. Install Docker ─────────────────────────────────────────────────────────
if ! command -v docker &>/dev/null; then
  echo "---> Installing Docker..."
  apt-get update -qq
  apt-get install -y ca-certificates curl gnupg lsb-release
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  chmod a+r /etc/apt/keyrings/docker.gpg
  echo \
    "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
    https://download.docker.com/linux/ubuntu \
    $(lsb_release -cs) stable" \
    | tee /etc/apt/sources.list.d/docker.list > /dev/null
  apt-get update -qq
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
  echo "    Docker installed: $(docker --version)"
else
  echo "---> Docker already installed: $(docker --version)"
fi

# ── 2. Install git (if missing) ───────────────────────────────────────────────
if ! command -v git &>/dev/null; then
  apt-get install -y git
fi

# ── 3. Set up .env from template ─────────────────────────────────────────────
ENV_FILE="$SERVER_DIR/.env"
TEMPLATE_FILE="$SERVER_DIR/.env.production.template"

if [ -f "$ENV_FILE" ]; then
  echo "---> .env already exists — skipping template copy. Review it before starting."
else
  if [ -f "$TEMPLATE_FILE" ]; then
    cp "$TEMPLATE_FILE" "$ENV_FILE"
    echo "---> Copied .env.production.template -> .env"
    echo "     !! IMPORTANT: Edit $ENV_FILE and replace all REPLACE_* values before starting !!"
  else
    echo "    WARNING: $TEMPLATE_FILE not found. Create $ENV_FILE manually."
  fi
fi

# ── 4. Generate a SECRET_KEY suggestion ───────────────────────────────────────
echo ""
echo "---> Suggested SECRET_KEY (copy into .env):"
python3 -c "import secrets; print('SECRET_KEY=' + secrets.token_urlsafe(64))"

# ── 5. Enable Docker service ──────────────────────────────────────────────────
systemctl enable docker
systemctl start docker
echo "---> Docker service enabled and started"

# ── 6. Summary ────────────────────────────────────────────────────────────────
echo ""
echo "============================================================"
echo " Setup complete. Next steps:"
echo ""
echo " 1. Edit Server Side/.env — replace ALL REPLACE_* values"
echo "    especially: SECRET_KEY, MYSQL_ROOT_PASSWORD,"
echo "                MYSQL_PASSWORD, INFLUX_PASS, ADMIN_PASSWORD"
echo "    and set:    ALLOWED_ORIGINS=http://129.212.138.248"
echo ""
echo " 2. Configure DigitalOcean Firewall (inbound rules):"
echo "    - TCP 22   (SSH)"
echo "    - TCP 80   (HTTP — nginx, API, /admin, MQTT WebSocket)"
echo "    - TCP 1883 (MQTT TCP direct from RPi)"
echo "    DO NOT open: 3307 (MySQL) or 8086 (InfluxDB)"
echo ""
echo " 3. Start the stack:"
echo "    cd \"Server Side\""
echo "    docker compose -f docker-compose.yml -f docker-compose.production.yml up -d --build"
echo ""
echo " 4. Verify:"
echo "    docker compose ps"
echo "    curl http://129.212.138.248/health"
echo "    curl http://129.212.138.248/admin/"
echo ""
echo " 5. Update RPi publisher config:"
echo "    Set mqtt.host = 129.212.138.248 in rpi_publisher_config.yaml"
echo "============================================================"
