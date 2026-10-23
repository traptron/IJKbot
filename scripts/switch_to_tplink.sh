#!/bin/bash
set -u

LOG="/var/log/wifi_switch.log"
RES_FILE="/home/otmorozki/wifi_switch_result.txt"

exec > >(tee -a "$LOG") 2>&1

echo "=========================================="
echo "Starting Wi-Fi switch at $(date)"
echo "Target SSID: TP-Link_C1C8"
echo "=========================================="

# 1. Backup existing netplan config
if [ -f /etc/netplan/50-cloud-init.yaml ]; then
    cp -v /etc/netplan/50-cloud-init.yaml /etc/netplan/50-cloud-init.yaml.bak_pixel
fi

# 2. Write new netplan config
cat << 'YAML_EOF' > /etc/netplan/50-cloud-init.yaml
network:
  version: 2
  ethernets:
    eth0:
      optional: true
      dhcp4: true
      dhcp6: true
  wifis:
    wlan0:
      optional: true
      dhcp4: true
      dhcp-identifier: mac
      addresses:
        - 192.168.1.10/24
      regulatory-domain: "RU"
      access-points:
        "TP-Link_C1C8":
          auth:
            key-management: "psk"
            password: "65751329"
        "TP-Link_C1C8_5G":
          auth:
            key-management: "psk"
            password: "65751329"
        "Pixel_1765":
          auth:
            key-management: "psk"
            password: "blebusavtobus"
YAML_EOF

chmod 600 /etc/netplan/50-cloud-init.yaml

# 3. Validate syntax
echo "Validating netplan configuration..."
if ! netplan generate; then
    echo "ERROR: netplan generate failed! Restoring backup..."
    cp -v /etc/netplan/50-cloud-init.yaml.bak_pixel /etc/netplan/50-cloud-init.yaml
    exit 1
fi

echo "Applying netplan configuration..."
netplan apply

# 4. Give wpa_supplicant a moment to reconfigure, then find network ID for TP-Link_C1C8
sleep 2
TPLINK_NET_ID=$(wpa_cli -i wlan0 list_networks 2>/dev/null | grep -E "TP-Link_C1C8\b" | head -n1 | awk '{print $1}')
if [ -z "$TPLINK_NET_ID" ]; then
    TPLINK_NET_ID=$(wpa_cli -i wlan0 list_networks 2>/dev/null | grep "TP-Link_C1C8_5G" | head -n1 | awk '{print $1}')
fi

if [ -n "$TPLINK_NET_ID" ]; then
    echo "Found TP-Link network ID: $TPLINK_NET_ID. Selecting it..."
    wpa_cli -i wlan0 select_network "$TPLINK_NET_ID"
else
    echo "Warning: TP-Link network not found in wpa_cli list_networks, forcing reassociate..."
    wpa_cli -i wlan0 reassociate
fi

# 5. Monitor association for up to 30 seconds
CONNECTED=0
for i in $(seq 1 30); do
    sleep 1
    STATUS=$(wpa_cli -i wlan0 status 2>/dev/null || true)
    CUR_SSID=$(echo "$STATUS" | grep "^ssid=" | cut -d'=' -f2)
    CUR_STATE=$(echo "$STATUS" | grep "^wpa_state=" | cut -d'=' -f2)
    BSSID=$(echo "$STATUS" | grep "^bssid=" | cut -d'=' -f2)
    
    echo "[$i/30] state=$CUR_STATE ssid=$CUR_SSID bssid=$BSSID"
    
    if [[ "$CUR_STATE" == "COMPLETED" ]] && [[ "$CUR_SSID" == TP-Link_C1C8* ]]; then
        CONNECTED=1
        echo "Successfully associated and authenticated with $CUR_SSID ($BSSID)!"
        break
    fi
done

if [ "$CONNECTED" -eq 1 ]; then
    echo "Re-enabling all networks so Pixel_1765 remains an automatic fallback..."
    wpa_cli -i wlan0 enable_network all
    
    echo "Requesting DHCP lease..."
    networkctl renew wlan0 || true
    sleep 3
    
    echo "Network state after switch:"
    ip -br a show dev wlan0
    ip route show
    
    cat << RES_EOF > "$RES_FILE"
STATUS=SUCCESS
SSID=$CUR_SSID
BSSID=$BSSID
IP_INFO=$(ip -br a show dev wlan0 | tr '\n' ' ')
ROUTES=$(ip route show | tr '\n' '; ')
DATE=$(date)
RES_EOF
    chown otmorozki:otmorozki "$RES_FILE"
    echo "SUCCESS: Wi-Fi switched to $CUR_SSID successfully!"
else
    echo "ERROR: Failed to connect to TP-Link within 30 seconds!"
    echo "Last status:"
    wpa_cli -i wlan0 status || true
    
    echo "Initiating ROLLBACK to Pixel_1765..."
    cp -v /etc/netplan/50-cloud-init.yaml.bak_pixel /etc/netplan/50-cloud-init.yaml
    netplan apply
    sleep 2
    PIXEL_NET_ID=$(wpa_cli -i wlan0 list_networks 2>/dev/null | grep "Pixel_1765" | head -n1 | awk '{print $1}')
    if [ -n "$PIXEL_NET_ID" ]; then
        wpa_cli -i wlan0 select_network "$PIXEL_NET_ID"
        wpa_cli -i wlan0 enable_network all
    fi
    networkctl renew wlan0 || true
    
    cat << RES_EOF > "$RES_FILE"
STATUS=FAILED
ERROR="Could not associate/authenticate with TP-Link within 30 seconds"
DATE=$(date)
RES_EOF
    chown otmorozki:otmorozki "$RES_FILE"
    echo "Rollback to Pixel_1765 completed."
fi
