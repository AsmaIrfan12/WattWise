#!/usr/bin/env bash
set -euo pipefail

BASE="${BASE:-http://129.212.138.248}"
NAME="${NAME:-Asma Irfan}"
EMAIL="${EMAIL:-IrfanA1@cardiff.ac.uk}"
PASSWORD="${PASSWORD:-WattWise2024!}"

HOME_NAME="${HOME_NAME:-Asma Irfan Home}"
ADDRESS="${ADDRESS:-14 Roath Park Road, Cardiff CF24 3AA}"
LOCATION_DESC="${LOCATION_DESC:-Roath, Cardiff}"
NUM_OCCUPANTS="${NUM_OCCUPANTS:-4}"
HOME_TYPE="${HOME_TYPE:-terraced}"

extract_json_string() {
  # Minimal extraction helper for simple JSON payloads.
  local key="$1"
  sed -n "s/.*\"${key}\":\"\([^\"]*\)\".*/\1/p"
}

extract_json_number() {
  local key="$1"
  sed -n "s/.*\"${key}\":\([0-9]*\).*/\1/p"
}

echo "== WattWise single user provisioning =="
echo "BASE=$BASE"
echo "EMAIL=$EMAIL"

# 1) Signup (fallback to login if already exists)
SIGNUP_RESP=$(curl -sS -X POST "$BASE/api/auth/signup" \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"$NAME\",\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}")

TOKEN=$(echo "$SIGNUP_RESP" | extract_json_string access_token)
USER_ID=$(echo "$SIGNUP_RESP" | extract_json_number user_id)

if [ -z "$TOKEN" ]; then
  echo "Signup did not return token. Trying login fallback..."
  LOGIN_RESP=$(curl -sS -X POST "$BASE/api/auth/login" \
    -H "Content-Type: application/json" \
    -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}")
  TOKEN=$(echo "$LOGIN_RESP" | extract_json_string access_token)
  USER_ID=$(echo "$LOGIN_RESP" | extract_json_number user_id)

  if [ -z "$TOKEN" ]; then
    echo "Auth failed. Signup response:"
    echo "$SIGNUP_RESP"
    echo "Login response:"
    echo "$LOGIN_RESP"
    exit 1
  fi
fi

echo "Authenticated: user_id=$USER_ID"

# 2) Create home
HOME_RESP=$(curl -sS -X POST "$BASE/api/homes" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"home_name\":\"$HOME_NAME\",\"address\":\"$ADDRESS\",\"location_desc\":\"$LOCATION_DESC\",\"num_occupants\":$NUM_OCCUPANTS,\"home_type\":\"$HOME_TYPE\"}")

HOME_ID=$(echo "$HOME_RESP" | extract_json_number id)

if [ -z "$HOME_ID" ]; then
  echo "Home creation failed. Response:"
  echo "$HOME_RESP"
  exit 1
fi

echo "Home created: home_id=$HOME_ID"

# 3) Add devices
add_device() {
  local body="$1"
  local label="$2"
  local resp
  resp=$(curl -sS -X POST "$BASE/api/homes/$HOME_ID/devices" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d "$body")

  local id
  id=$(echo "$resp" | extract_json_number id)
  if [ -n "$id" ]; then
    echo "  OK device: $label (id=$id)"
  else
    echo "  WARN device failed: $label"
    echo "       response: $resp"
  fi
}

add_device '{"name":"Air Fryer","appliance_key":"airfryer","entity_id":"airfryer_current_consumption","device_type":"appliance","rated_wattage":1500,"location":"Kitchen"}' "Air Fryer"
add_device '{"name":"Dishwasher","appliance_key":"dishwasher","entity_id":"dishwasher_current_consumption","device_type":"appliance","rated_wattage":1800,"location":"Kitchen"}' "Dishwasher"
add_device '{"name":"Kettle","appliance_key":"kettle","entity_id":"kettle_current_consumption","device_type":"appliance","rated_wattage":2200,"location":"Kitchen"}' "Kettle"
add_device '{"name":"Microwave","appliance_key":"microwave","entity_id":"microwave_current_consumption","device_type":"appliance","rated_wattage":900,"location":"Kitchen"}' "Microwave"
add_device '{"name":"Toaster","appliance_key":"toaster","entity_id":"toaster_current_consumption","device_type":"appliance","rated_wattage":800,"location":"Kitchen"}' "Toaster"
add_device '{"name":"Washing Machine","appliance_key":"washing_machine","entity_id":"washing_machine_current_consumption","device_type":"appliance","rated_wattage":2000,"location":"Kitchen"}' "Washing Machine"

echo "Done: user_id=$USER_ID, home_id=$HOME_ID"

## & "C:\Program Files\Git\bin\bash.exe" "./single user add.sh"