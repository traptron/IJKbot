#!/usr/bin/env bash
# ==============================================================================
# teleop.sh — Ручное телеуправление мобильной платформой IJKbot с клавиатуры.
#
# Публикует команды в топик /cmd_vel_sm (приоритет 50 в twist_mux),
# что позволяет перехватывать управление у автономной навигации Nav2 (приоритет 10),
# но уступает экстренной остановке /cmd_vel_emergency (приоритет 100).
#
# ВНИМАНИЕ: Перед стартом на полигоне проверьте знаки вращения моторов
# на вывешенных колесах: левый — ID 1, правый — ID 2.
# Регламентная максимальная скорость движения: V_max <= 0.25 м/с.
# ==============================================================================
set -euo pipefail

# Цвета для вывода в терминал
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-42}"
export RMW_IMPLEMENTATION="${RMW_IMPLEMENTATION:-rmw_cyclonedds_cpp}"

PIXI_MANIFEST="${PIXI_PROJECT_MANIFEST:-/home/lev/ros2_jazzy/pixi.toml}"

# Дефолтные безопасные скорости (линейная 0.2 м/с <= 0.25 м/с по регламенту, угловая 0.5 рад/с)
DEFAULT_SPEED="0.2"
DEFAULT_TURN="0.5"

print_help() {
    echo -e "${BOLD}Использование:${NC} $0 [ПАРАМЕТРЫ]"
    echo ""
    echo "Параметры:"
    echo "  --speed <VAL>       Линейная скорость в м/с (по умолчанию: 0.2, макс: 0.25)"
    echo "  --turn <VAL>        Угловая скорость в рад/с (по умолчанию: 0.5)"
    echo "  --topic <TOPIC>     Топик для отправки Twist (по умолчанию: /cmd_vel_sm)"
    echo "  -h, --help          Показать эту справку"
    echo ""
    echo "Переменные окружения:"
    echo "  ROS_DOMAIN_ID       ID ROS-домена (по умолчанию: 42)"
}

TARGET_TOPIC="/cmd_vel_sm"
SPEED="${DEFAULT_SPEED}"
TURN="${DEFAULT_TURN}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --speed)
            SPEED="$2"
            shift 2
            ;;
        --turn)
            TURN="$2"
            shift 2
            ;;
        --topic)
            TARGET_TOPIC="$2"
            shift 2
            ;;
        -h|--help)
            print_help
            exit 0
            ;;
        *)
            echo -e "${RED}[ERROR] Неизвестный аргумент: $1${NC}" >&2
            print_help
            exit 1
            ;;
    esac
done

echo -e "${CYAN}${BOLD}================================================================${NC}"
echo -e "${CYAN}${BOLD}         IJKbot — Ручное телеуправление с клавиатуры             ${NC}"
echo -e "${CYAN}${BOLD}================================================================${NC}"
# Проверка лимита скорости по регламенту (V_max <= 0.25 м/с)
if awk "BEGIN {exit !(${SPEED} > 0.25)}"; then
    echo -e "${YELLOW}[WARN] Заданная скорость ${SPEED} м/с превышает регламентный лимит соревнований (V_max <= 0.25 м/с)!${NC}"
    echo -e "${YELLOW}[WARN] Скорость автоматически снижена до безопасного максимума: 0.25 м/с.${NC}"
    SPEED="0.25"
fi

echo -e "${BLUE}ROS_DOMAIN_ID:${NC}     ${BOLD}${ROS_DOMAIN_ID}${NC}"
echo -e "${BLUE}Целевой топик:${NC}     ${BOLD}${TARGET_TOPIC}${NC} (twist_mux приоритет: 50)"
echo -e "${BLUE}Линейная скорость:${NC} ${SPEED} м/с (лимит регламента: 0.25 м/с)"
echo -e "${BLUE}Угловая скорость:${NC}  ${TURN} рад/с"
echo -e "${CYAN}----------------------------------------------------------------${NC}"
echo -e "${BOLD}Управление клавишами:${NC}"
echo -e "   ${GREEN}u${NC}    ${GREEN}i${NC}    ${GREEN}o${NC}     — Вперед-влево / Вперед / Вперед-вправо"
echo -e "   ${GREEN}j${NC}    ${YELLOW}k${NC}    ${GREEN}l${NC}     — Разворот влево / СТОП / Разворот вправо"
echo -e "   ${GREEN}m${NC}    ${GREEN},${NC}    ${GREEN}.${NC}     — Назад-влево / Назад / Назад-вправо"
echo -e "   ${CYAN}пробел${NC}            — Экстренная остановка (СТОП)"
echo -e "   ${CYAN}q/z${NC}               — Увеличить / уменьшить макс. скорости на 10%"
echo -e "   ${CYAN}w/x${NC}               — Увеличить / уменьшить только линейную скорость на 10%"
echo -e "   ${CYAN}e/c${NC}               — Увеличить / уменьшить только угловую скорость на 10%"
echo -e "   ${RED}Ctrl+C${NC}            — Выход и автоматическая остановка моторов"
echo -e "${CYAN}================================================================${NC}"

# Функция остановки моторов при выходе
STOP_CALLED=false
stop_on_exit() {
    if [[ "${STOP_CALLED}" == "true" ]]; then
        return
    fi
    STOP_CALLED=true
    trap - EXIT INT TERM
    echo -e "\n${YELLOW}[INFO] Завершение телеуправления. Отправка нулевой скорости в ${TARGET_TOPIC}...${NC}"
    PIXI_PROJECT_MANIFEST="${PIXI_MANIFEST}" pixi run ros2 topic pub --once -w 0 "${TARGET_TOPIC}" geometry_msgs/msg/Twist \
        "{linear: {x: 0.0, y: 0.0, z: 0.0}, angular: {x: 0.0, y: 0.0, z: 0.0}}" >/dev/null 2>&1 || true
    echo -e "${GREEN}[OK] Телеуправление завершено.${NC}"
}
trap stop_on_exit EXIT INT TERM

export PIXI_PROJECT_MANIFEST="${PIXI_MANIFEST}"
# Запуск без exec, чтобы при выходе или сигнале bash гарантированно выполнил trap stop_on_exit
if pixi run ros2 run teleop_twist_keyboard teleop_twist_keyboard \
    --ros-args \
    -r /cmd_vel:="${TARGET_TOPIC}" \
    -p speed:="${SPEED}" \
    -p turn:="${TURN}"; then
    TELEOP_EXIT=0
else
    TELEOP_EXIT=$?
fi

stop_on_exit
exit "${TELEOP_EXIT}"

