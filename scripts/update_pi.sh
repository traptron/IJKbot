#!/usr/bin/env bash
# ==============================================================================
# update_pi.sh — Обновление репозитория IJKbot и сборка пакетов colcon.
#
# Функционал:
# 1. git fetch & git pull актуальной ветки (по умолчанию dev).
# 2. Безопасное сохранение локальных изменений (автоматический git stash push/pop).
# 3. Автоматическая сборка измененных ROS 2 пакетов (colcon build --symlink-install).
# 4. Поддержка двух режимов:
#    - Локально на Raspberry Pi (или на ноутбуке с флагом --local)
#    - Удаленно с Ноутбука 2 на Raspberry Pi по SSH с трансляцией логов.
# ==============================================================================
set -uo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-42}"
export RMW_IMPLEMENTATION="${RMW_IMPLEMENTATION:-rmw_cyclonedds_cpp}"

PI_HOST="${PI_HOST:-${ROBOT_IP:-192.168.1.10}}"
PI_USER="${PI_USER:-${ROBOT_USER:-otmorozki}}"
BRANCH="dev"
REMOTE_WS="/home/${PI_USER}/IJKbot"
LOCAL_WS="${REPO_DIR}"
CUSTOM_WS=""
CLEAN_BUILD="false"
NO_BUILD="false"
PACKAGES=""
ALLOW_DIRTY="false"
RUN_LOCAL="false"
FORCE_START="false"
PIXI_MANIFEST="${PIXI_PROJECT_MANIFEST:-/home/lev/ros2_jazzy/pixi.toml}"

print_help() {
    echo -e "${BOLD}Использование:${NC} $0 [ПАРАМЕТРЫ]"
    echo ""
    echo "Скрипт обновления репозитория IJKbot и сборки пакетов colcon."
    echo "Работает как удалённо с ноутбука по SSH, так и напрямую на Raspberry Pi."
    echo ""
    echo "Параметры:"
    echo "  --host <IP>          IP-адрес Raspberry Pi (по умолчанию: ${PI_HOST})"
    echo "  --user <USER>        SSH-пользователь на роботе (по умолчанию: ${PI_USER})"
    echo "  --branch <BRANCH>    Ветка Git для обновления (по умолчанию: ${BRANCH})"
    echo "  --ws <DIR>           Путь к директории репозитория (по умолчанию: ${REMOTE_WS})"
    echo "  --clean              Полная очистка (rm -rf build/ install/ log/) перед сборкой"
    echo "  --no-build           Только git fetch & pull без вызова colcon build"
    echo "  --packages <PKGS>    Собрать только указанные пакеты (--packages-up-to)"
    echo "  --no-stash           Не выполнять автоматический git stash при наличии изменений"
    echo "  --local              Принудительно выполнить обновление локально на этой машине"
    echo "  --force              Игнорировать ошибки проверки связи (ping/SSH) и продолжать"
    echo "  -h, --help           Показать эту справку"
    echo ""
    echo "Переменные окружения:"
    echo "  PI_HOST / ROBOT_IP   IP-адрес Raspberry Pi (дефолт: 192.168.1.10)"
    echo "  PI_USER / ROBOT_USER SSH-пользователь (дефолт: otmorozki)"
    echo "  ROS_DOMAIN_ID        ID ROS-домена (дефолт: 42)"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --host)
            if [[ $# -lt 2 ]]; then
                echo -e "${RED}[ERROR] Опция $1 требует IP-адреса${NC}" >&2
                print_help
                exit 1
            fi
            PI_HOST="$2"
            shift 2
            ;;
        --user)
            if [[ $# -lt 2 ]]; then
                echo -e "${RED}[ERROR] Опция $1 требует имени пользователя${NC}" >&2
                print_help
                exit 1
            fi
            PI_USER="$2"
            shift 2
            ;;
        --branch)
            if [[ $# -lt 2 ]]; then
                echo -e "${RED}[ERROR] Опция $1 требует имени ветки${NC}" >&2
                print_help
                exit 1
            fi
            BRANCH="$2"
            shift 2
            ;;
        --ws|--dir)
            if [[ $# -lt 2 ]]; then
                echo -e "${RED}[ERROR] Опция $1 требует пути к рабочей директории${NC}" >&2
                print_help
                exit 1
            fi
            CUSTOM_WS="$2"
            shift 2
            ;;
        --clean)
            CLEAN_BUILD="true"
            shift
            ;;
        --no-build)
            NO_BUILD="true"
            shift
            ;;
        --packages|--packages-select|--packages-up-to)
            if [[ $# -lt 2 ]]; then
                echo -e "${RED}[ERROR] Опция $1 требует списка пакетов${NC}" >&2
                print_help
                exit 1
            fi
            PACKAGES="$2"
            shift 2
            ;;
        --no-stash)
            ALLOW_DIRTY="true"
            shift
            ;;
        --local)
            RUN_LOCAL="true"
            shift
            ;;
        --force)
            FORCE_START="true"
            shift
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

if [[ -n "${CUSTOM_WS}" ]]; then
    REMOTE_WS="${CUSTOM_WS}"
    LOCAL_WS="${CUSTOM_WS}"
fi

# Основная функция обновления (выполняется либо локально, либо удаленно через SSH)
do_update() {
    set -uo pipefail

    local RED='\033[0;31m'
    local GREEN='\033[0;32m'
    local YELLOW='\033[1;33m'
    local BLUE='\033[0;34m'
    local CYAN='\033[0;36m'
    local BOLD='\033[1m'
    local NC='\033[0m'

    local ws="${1}"
    local branch="${2:-dev}"
    local no_build="${3:-false}"
    local clean="${4:-false}"
    local pkgs="${5:-}"
    local allow_dirty="${6:-false}"
    local pixi_manifest="${7:-/home/lev/ros2_jazzy/pixi.toml}"

    echo -e "${BLUE}=== [1/3] Проверка и подготовка рабочей директории ===${NC}"
    if [[ ! -d "${ws}" ]]; then
        echo -e "${RED}[ERROR] Директория воркспейса '${ws}' не существует!${NC}" >&2
        return 1
    fi

    cd "${ws}" || {
        echo -e "${RED}[ERROR] Не удалось перейти в директорию '${ws}'!${NC}" >&2
        return 1
    }

    if ! git rev-parse --is-inside-work-tree &>/dev/null; then
        echo -e "${RED}[ERROR] Директория '${ws}' не является Git-репозиторием!${NC}" >&2
        return 1
    fi

    local current_branch
    current_branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "UNKNOWN")
    echo -e "${BLUE}Путь к воркспейсу:${NC} ${ws}"
    echo -e "${BLUE}Текущая ветка:${NC}     ${current_branch}"
    echo -e "${BLUE}Целевая ветка:${NC}     ${branch}"

    # Обработка незакоммиченных изменений
    local had_stash=false
    local dirty_status
    dirty_status=$(git status --porcelain 2>/dev/null || true)

    if [[ -n "${dirty_status}" ]]; then
        if [[ "${allow_dirty}" == "true" ]]; then
            echo -e "${YELLOW}[WARN] Обнаружены локальные изменения (авто-stash отключен флагом --no-stash):${NC}"
            git --no-pager status --short
        else
            echo -e "${YELLOW}[WARN] Обнаружены незакоммиченные локальные изменения в рабочей директории:${NC}"
            git --no-pager status --short
            echo -e "${YELLOW}[INFO] Безопасное сохранение во временный stash...${NC}"
            local stash_tag="ijkbot_update_stash_$(date +%Y%m%d_%H%M%S)"
            if git stash push -u -m "${stash_tag}"; then
                had_stash=true
                echo -e "${GREEN}[OK] Изменения сохранены в stash: ${stash_tag}${NC}"
            else
                echo -e "${RED}[ERROR] Не удалось сохранить изменения в git stash!${NC}" >&2
                return 1
            fi
        fi
    fi

    echo -e "${BLUE}=== [2/3] Обновление Git (fetch & pull) ===${NC}"
    local old_commit
    old_commit=$(git rev-parse HEAD 2>/dev/null || echo "")

    if ! git remote get-url origin &>/dev/null; then
        echo -e "${YELLOW}[WARN] Удаленный репозиторий 'origin' не настроен для '${ws}'. Пропуск git fetch & pull.${NC}"
    else
        # Переключение ветки при необходимости
        if [[ "${current_branch}" != "${branch}" ]]; then
            echo -e "${BLUE}[GIT] Переключение на ветку '${branch}'...${NC}"
            if ! git checkout "${branch}" 2>/dev/null; then
                if git checkout -b "${branch}" "origin/${branch}" 2>/dev/null; then
                    echo -e "${GREEN}[OK] Создана и активирована локальная ветка '${branch}' из origin/${branch}.${NC}"
                else
                    echo -e "${RED}[ERROR] Не удалось переключиться на ветку '${branch}'!${NC}" >&2
                    if [[ "${had_stash}" == "true" ]]; then
                        echo -e "${YELLOW}[INFO] Восстанавливаем сохраненный stash...${NC}"
                        git stash pop || true
                    fi
                    return 1
                fi
            fi
        fi

        # Получение изменений
        echo -e "${BLUE}[GIT] Выполнение 'git fetch origin ${branch}'...${NC}"
        if ! git fetch origin "${branch}"; then
            echo -e "${RED}[ERROR] Ошибка выполнения git fetch origin ${branch}! Проверьте соединение с интернетом/GitHub.${NC}" >&2
            if [[ "${had_stash}" == "true" ]]; then
                echo -e "${YELLOW}[INFO] Восстанавливаем сохраненный stash...${NC}"
                git stash pop || true
            fi
            return 1
        fi

        echo -e "${BLUE}[GIT] Выполнение 'git pull origin ${branch}'...${NC}"
        if ! git pull origin "${branch}"; then
            echo -e "${RED}[ERROR] Ошибка выполнения git pull origin ${branch}! Возможен конфликт слияния.${NC}" >&2
            if [[ "${had_stash}" == "true" ]]; then
                echo -e "${YELLOW}[INFO] Восстанавливаем сохраненный stash...${NC}"
                git stash pop || true
            fi
            return 1
        fi
    fi

    local new_commit
    new_commit=$(git rev-parse HEAD 2>/dev/null || echo "")

    # Восстановление stash
    if [[ "${had_stash}" == "true" ]]; then
        echo -e "${BLUE}[GIT] Восстановление локальных изменений (git stash pop)...${NC}"
        if git stash pop; then
            echo -e "${GREEN}[OK] Локальные изменения успешно применены поверх обновлений.${NC}"
        else
            echo -e "${RED}[WARN] Конфликт при восстановлении изменений из stash!${NC}" >&2
            echo -e "${YELLOW}Пожалуйста, проверьте состояние файлов ('git status') и разрешите конфликты вручную.${NC}" >&2
        fi
    fi

    if [[ -n "${old_commit}" && "${old_commit}" == "${new_commit}" ]]; then
        echo -e "${GREEN}[OK] Репозиторий уже содержит самые свежие изменения (${new_commit:0:8}).${NC}"
    elif [[ -n "${new_commit}" ]]; then
        echo -e "${GREEN}[OK] Репозиторий успешно обновлен: ${old_commit:0:8} -> ${new_commit:0:8}${NC}"
        echo -e "${CYAN}Последний коммит:${NC}"
        git --no-pager log -1 --stat
    fi

    # Сборка пакетов
    echo -e "${BLUE}=== [3/3] Сборка пакетов (colcon build) ===${NC}"
    if [[ "${clean}" == "true" ]]; then
        echo -e "${YELLOW}[INFO] Выполняется полная очистка директорий сборки (--clean)...${NC}"
        rm -rf "${ws}/build" "${ws}/install" "${ws}/log"
        echo -e "${GREEN}[OK] Директории build/, install/, log/ очищены.${NC}"
    fi

    if [[ "${no_build}" == "true" ]]; then
        echo -e "${YELLOW}[INFO] Сборка пакетов пропущена по флагу --no-build.${NC}"
        return 0
    fi

    # Sourcing ROS 2
    local ros_sourced=false
    if [[ -f "/opt/ros/jazzy/setup.bash" ]]; then
        # Нативный ROS 2 Jazzy (Raspberry Pi Ubuntu 24.04)
        source /opt/ros/jazzy/setup.bash
        ros_sourced=true
    elif [[ -n "${ROS_DISTRO:-}" && -f "/opt/ros/${ROS_DISTRO}/setup.bash" ]]; then
        source "/opt/ros/${ROS_DISTRO}/setup.bash"
        ros_sourced=true
    fi

    local colcon_cmd="colcon"
    if [[ "${ros_sourced}" != "true" ]]; then
        if command -v pixi &>/dev/null && [[ -f "${pixi_manifest}" ]]; then
            colcon_cmd="pixi run --manifest-path ${pixi_manifest} colcon"
            ros_sourced=true
        fi
    fi

    if ! command -v colcon &>/dev/null && [[ "${colcon_cmd}" == "colcon" ]]; then
        echo -e "${RED}[ERROR] Команда colcon не найдена! Убедитесь, что ROS 2 Jazzy установлен.${NC}" >&2
        return 1
    fi

    # Определение аргументов сборки
    local build_args=("--symlink-install")

    if [[ -n "${pkgs}" ]]; then
        echo -e "${BLUE}[BUILD] Сборка указанных пакетов: ${BOLD}${pkgs}${NC}"
        build_args+=("--packages-up-to" ${pkgs})
    elif [[ "${clean}" != "true" && -n "${old_commit}" && -n "${new_commit}" && "${old_commit}" != "${new_commit}" ]]; then
        local changed_dirs
        changed_dirs=$(git diff --name-only "${old_commit}" "${new_commit}" 2>/dev/null | awk -F/ '{print $1}' | sort -u || true)
        local detected_pkgs=()
        for d in ${changed_dirs}; do
            if [[ -f "${ws}/${d}/package.xml" ]]; then
                detected_pkgs+=("${d}")
            fi
        done
        if [[ ${#detected_pkgs[@]} -gt 0 ]]; then
            echo -e "${BLUE}[BUILD] Обнаружены изменения в пакетах: ${BOLD}${detected_pkgs[*]}${NC}"
            build_args+=("--packages-up-to" "${detected_pkgs[@]}")
        else
            echo -e "${BLUE}[BUILD] Изменения в ROS-пакетах не обнаружены, проверка сборки воркспейса...${NC}"
        fi
    else
        echo -e "${BLUE}[BUILD] Сборка всех пакетов воркспейса...${NC}"
    fi

    echo -e "${CYAN}----------------------------------------------------------------${NC}"
    echo -e "${BLUE}[BUILD] Запуск: ${BOLD}${colcon_cmd} build ${build_args[*]}${NC}"
    echo -e "${CYAN}----------------------------------------------------------------${NC}"

    local start_time
    start_time=$(date +%s)

    if ${colcon_cmd} build "${build_args[@]}"; then
        local end_time
        end_time=$(date +%s)
        local duration=$((end_time - start_time))
        echo -e "${CYAN}----------------------------------------------------------------${NC}"
        echo -e "${GREEN}${BOLD}[OK] Сборка пакетов успешно завершена за ${duration} с.${NC}"
        return 0
    else
        local status=$?
        echo -e "${CYAN}----------------------------------------------------------------${NC}"
        echo -e "${RED}${BOLD}[ERROR] Сборка colcon завершилась с ошибкой (код: ${status})!${NC}" >&2
        return ${status}
    fi
}

# Определение режима: локальный или удаленный (SSH)
IS_ON_PI=false
if [[ -f /proc/device-tree/model ]] && grep -qi "Raspberry Pi" /proc/device-tree/model; then
    IS_ON_PI=true
fi

IS_LOCAL_HOST=false
if [[ "${PI_HOST}" == "localhost" || "${PI_HOST}" == "127.0.0.1" || "${PI_HOST}" == "::1" ]]; then
    IS_LOCAL_HOST=true
elif command -v hostname >/dev/null && hostname -I 2>/dev/null | grep -qw "${PI_HOST}"; then
    IS_LOCAL_HOST=true
fi

if [[ "${RUN_LOCAL}" == "true" ]] || [[ "${IS_ON_PI}" == "true" ]] || [[ "${IS_LOCAL_HOST}" == "true" ]]; then
    ACTIVE_MODE="local"
else
    ACTIVE_MODE="remote"
fi

echo -e "${CYAN}${BOLD}================================================================${NC}"
echo -e "${CYAN}${BOLD}    IJKbot — Обновление репозитория ($([[ "${ACTIVE_MODE}" == "local" ]] && echo "Локально" || echo "На Raspberry Pi по SSH"))   ${NC}"
echo -e "${CYAN}${BOLD}================================================================${NC}"
echo -e "${BLUE}Режим работы:${NC}      ${BOLD}$([[ "${ACTIVE_MODE}" == "local" ]] && echo "ЛОКАЛЬНЫЙ (на текущей машине)" || echo "УДАЛЕННЫЙ (${PI_USER}@${PI_HOST}) via SSH")${NC}"
echo -e "${BLUE}Целевая ветка:${NC}     ${BOLD}${BRANCH}${NC}"
echo -e "${BLUE}Директория:${NC}        ${BOLD}$([[ "${ACTIVE_MODE}" == "local" ]] && echo "${LOCAL_WS}" || echo "${REMOTE_WS}")${NC}"
echo -e "${BLUE}Сборка colcon:${NC}     ${BOLD}$([[ "${NO_BUILD}" == "true" ]] && echo "ОТКЛЮЧЕНА (--no-build)" || echo "ВКЛЮЧЕНА ($([[ "${CLEAN_BUILD}" == "true" ]] && echo "clean" || echo "incremental"))")${NC}"
echo -e "${BLUE}ROS_DOMAIN_ID:${NC}     ${BOLD}${ROS_DOMAIN_ID}${NC}"
echo -e "${CYAN}----------------------------------------------------------------${NC}"

if [[ "${ACTIVE_MODE}" == "local" ]]; then
    echo -e "${GREEN}${BOLD}Запуск обновления локально в ${LOCAL_WS}...${NC}"
    echo -e "${CYAN}----------------------------------------------------------------${NC}"

    do_update "${LOCAL_WS}" "${BRANCH}" "${NO_BUILD}" "${CLEAN_BUILD}" "${PACKAGES}" "${ALLOW_DIRTY}" "${PIXI_MANIFEST}"
    LOCAL_EXIT=$?

    if [[ ${LOCAL_EXIT} -ne 0 ]]; then
        echo -e "${RED}[ERROR] Локальное обновление завершилось с ошибкой (код: ${LOCAL_EXIT}).${NC}" >&2
        exit ${LOCAL_EXIT}
    fi

    echo -e "${CYAN}================================================================${NC}"
    echo -e "${GREEN}${BOLD}[OK] Обновление робота завершено успешно!${NC}"
    echo -e "${CYAN}================================================================${NC}"
    exit 0
fi

# Удаленный режим через SSH
echo -ne "${BLUE}[1/2] Проверка связи с Raspberry Pi (${PI_HOST})... ${NC}"
SSH_PROBE_OUT=$(ssh -o BatchMode=yes -o ConnectTimeout=2 -o StrictHostKeyChecking=no "${PI_USER}@${PI_HOST}" "true" 2>&1 || true)
HOST_UNREACHABLE=false

if echo "${SSH_PROBE_OUT}" | grep -qE "timed out|No route to host|Connection refused|Connection timed out during banner exchange"; then
    HOST_UNREACHABLE=true
elif ! ping -c 1 -W 1 "${PI_HOST}" &>/dev/null && [[ -n "${SSH_PROBE_OUT}" ]] && ! echo "${SSH_PROBE_OUT}" | grep -qE "Permission denied"; then
    HOST_UNREACHABLE=true
fi

if [[ "${HOST_UNREACHABLE}" == "true" ]]; then
    echo -e "${RED}[FAIL] Робот ${PI_HOST} не отвечает по сети (SSH/Ping недоступен)!${NC}" >&2
    if [[ "${FORCE_START}" != "true" ]]; then
        echo -e "${YELLOW}Подсказка:${NC}" >&2
        echo -e "  - Проверьте подключение к Wi-Fi роутеру соревнований (5 ГГц)." >&2
        echo -e "  - Проверьте IP: возможно робот на мобильной точке (172.22.35.154)?" >&2
        echo -e "  - Для запуска с альтернативным IP используйте: $0 --host 172.22.35.154" >&2
        echo -e "  - Для локального прогона без робота используйте: $0 --local" >&2
        echo -e "  - Для принудительного продолжения используйте флаг --force" >&2
        exit 1
    else
        echo -e "${YELLOW}[WARN] Флаг --force активен: продолжаем попытку SSH подключения...${NC}"
    fi
else
    echo -e "${GREEN}[OK] Связь с ${PI_HOST} установлена.${NC}"
fi

echo -e "${GREEN}${BOLD}[2/2] Подключение по SSH и обновление репозитория...${NC}"
echo -e "${CYAN}----------------------------------------------------------------${NC}"

SSH_PID=""
cleanup_remote() {
    echo -e "\n${YELLOW}[INFO] Получен сигнал прерывания (Ctrl+C). Остановка удаленной команды...${NC}"
    if [[ -n "${SSH_PID}" ]] && kill -0 "${SSH_PID}" 2>/dev/null; then
        kill -INT "${SSH_PID}" 2>/dev/null || true
    fi
    exit 130
}
trap cleanup_remote SIGINT SIGTERM

SSH_TTY_OPT=""
if [[ -t 1 ]]; then
    SSH_TTY_OPT="-tt"
fi

REMOTE_PAYLOAD="$(typeset -f do_update); do_update \"${REMOTE_WS}\" \"${BRANCH}\" \"${NO_BUILD}\" \"${CLEAN_BUILD}\" \"${PACKAGES}\" \"${ALLOW_DIRTY}\""
B64_PAYLOAD=$(echo "${REMOTE_PAYLOAD}" | base64 -w 0)

ssh ${SSH_TTY_OPT} -o ConnectTimeout=10 -o StrictHostKeyChecking=no "${PI_USER}@${PI_HOST}" \
    "bash -c \"\$(echo '${B64_PAYLOAD}' | base64 -d)\"" &
SSH_PID=$!

wait "${SSH_PID}"
SSH_EXIT=$?
SSH_PID=""

if [[ ${SSH_EXIT} -ne 0 ]]; then
    echo -e "${RED}[ERROR] Ошибка при удаленном обновлении на ${PI_HOST} (код: ${SSH_EXIT}).${NC}" >&2
    exit ${SSH_EXIT}
fi

echo -e "${CYAN}================================================================${NC}"
echo -e "${GREEN}${BOLD}[OK] Удаленное обновление репозитория на ${PI_HOST} успешно завершено!${NC}"
echo -e "${CYAN}================================================================${NC}"
exit 0
