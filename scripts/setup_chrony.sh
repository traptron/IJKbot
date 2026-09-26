#!/usr/bin/env bash
# ==============================================================================
# setup_chrony.sh — Настройка NTP-синхронизации Chrony (Ноутбук <-> Raspberry Pi)
# Хакатон «Эвакуация» (Кубок РТК Высшая Лига)
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVER_CONF="${SCRIPT_DIR}/chrony/chrony_server.conf"
CLIENT_CONF="${SCRIPT_DIR}/chrony/chrony_client.conf"

PI_HOST="${ROBOT_IP:-192.168.1.10}"
PI_USER="${ROBOT_USER:-otmorozki}"

print_usage() {
    echo "Использование: $0 [server | client | deploy-pi]"
    echo "  server     - Установить конфигурацию сервера Chrony на текущую машину (Ноутбук)"
    echo "  client     - Установить конфигурацию клиента Chrony на текущую машину (Pi)"
    echo "  deploy-pi  - Скопировать конфигурацию клиента на Raspberry Pi по SSH и перезапустить chrony"
}

if [[ $# -lt 1 ]]; then
    print_usage
    exit 1
fi

ACTION="$1"

case "${ACTION}" in
    server)
        echo "=== Установка конфигурации Chrony NTP Server (Ноутбук) ==="
        if ! command -v chronyd &>/dev/null; then
            echo "[ERROR] chrony не установлен. Установите: sudo apt-get install -y chrony"
            exit 1
        fi
        sudo mkdir -p /etc/chrony/conf.d
        sudo cp -v "${SERVER_CONF}" /etc/chrony/conf.d/ijkbot_server.conf
        sudo systemctl restart chrony
        echo "[OK] Chrony сервер успешно настроен и перезапущен."
        chronyc sources -v || true
        ;;

    client)
        echo "=== Установка конфигурации Chrony NTP Client (Raspberry Pi) ==="
        if ! command -v chronyd &>/dev/null; then
            echo "[ERROR] chrony не установлен. Установите: sudo apt-get install -y chrony"
            exit 1
        fi
        sudo mkdir -p /etc/chrony/conf.d
        sudo cp -v "${CLIENT_CONF}" /etc/chrony/conf.d/ijkbot_client.conf
        sudo systemctl restart chrony
        echo "[OK] Chrony клиент успешно настроен и перезапущен."
        chronyc sources -v || true
        ;;

    deploy-pi)
        TARGET_HOST="${2:-${PI_HOST}}"
        TARGET_USER="${3:-${PI_USER}}"
        echo "=== Деплой конфигурации Chrony на Raspberry Pi (${TARGET_USER}@${TARGET_HOST}) ==="
        scp -o BatchMode=yes -o StrictHostKeyChecking=no "${CLIENT_CONF}" "${TARGET_USER}@${TARGET_HOST}:/tmp/ijkbot_client.conf"
        ssh -o BatchMode=yes -o StrictHostKeyChecking=no "${TARGET_USER}@${TARGET_HOST}" "
            sudo mkdir -p /etc/chrony/conf.d && \
            sudo mv /tmp/ijkbot_client.conf /etc/chrony/conf.d/ijkbot_client.conf && \
            sudo systemctl restart chrony && \
            sleep 1 && \
            (chronyc sources || true)
        "
        echo "[OK] Конфигурация успешно развернута на Raspberry Pi."
        ;;

    *)
        print_usage
        exit 1
        ;;
esac
