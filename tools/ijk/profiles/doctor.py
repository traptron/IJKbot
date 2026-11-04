"""System diagnostics and health check (without moving motors)."""

from typing import Optional
import os
import subprocess

from tools.ijk.config import IjkConfig
from tools.ijk.discovery import is_port_open, is_ssh_responsive
from tools.ijk.env import find_pixi, get_pixi_manifest, get_source_ip_for_target
from tools.ijk.role import is_ollama_available


def check_local_environment(config: IjkConfig, robot_ip: Optional[str]) -> None:
    print("--- 1. Локальное окружение (Ноутбук) ---")
    pixi = find_pixi()
    manifest = get_pixi_manifest()
    print(f"  Pixi binary:    {'[OK] ' + pixi if pixi else '[WARN] не найден в стандартных путях'}")
    print(f"  Pixi manifest:  {'[OK] ' + manifest if manifest else '[WARN] не найден'}")
    print(f"  ROS_DOMAIN_ID:  {config.network.domain_id}")
    print(f"  RMW:            {config.network.rmw}")

    ollama_ok = is_ollama_available()
    print(f"  Ollama LLM:     {'[OK] Сервер активен (localhost:11434)' if ollama_ok else '[INFO] Не запущен локально (нормально для роли operator)'}")

    if robot_ip:
        src_ip = get_source_ip_for_target(robot_ip)
        print(f"  Маршрут к Pi:   {src_ip or 'не определен'} -> {robot_ip}")


def check_remote_robot(robot_ip: Optional[str], config: IjkConfig) -> None:
    print("\n--- 2. Бортовой компьютер (Raspberry Pi) ---")
    if not robot_ip:
        print("  [FAIL] Робот не найден в сети.")
        print("  Рекомендации:")
        print("    1. Проверьте питание робота и подключение к Wi-Fi.")
        print("    2. Запустите './ijk discover' или укажите вручную: './ijk --host <IP> doctor'")
        return

    user = config.network.default_user
    print(f"  Целевой IP:     {robot_ip}")

    port_22 = is_port_open(robot_ip, 22, timeout=0.8)
    print(f"  Порт 22 (SSH):  {'[OK] Открыт' if port_22 else '[FAIL] Закрыт или таймаут'}")
    if not port_22:
        return

    ssh_ok = is_ssh_responsive(robot_ip, user, timeout=2)
    print(f"  SSH авторизация:{'[OK] Успешно (' + user + '@' + robot_ip + ')' if ssh_ok else '[FAIL] Ошибка ключа/пароля'}")
    if not ssh_ok:
        return

    def ssh_exec(cmd: str) -> str:
        try:
            res = subprocess.run(
                ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no", f"{user}@{robot_ip}", cmd],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=3.0,
            )
            return res.stdout.strip()
        except Exception:
            return ""

    # Hardware devices
    usb_devices = ssh_exec("ls -1 /dev/ttyUSB* /dev/ttySTS* 2>/dev/null || true")
    has_devices = bool(usb_devices)
    dev_str = ", ".join(usb_devices.splitlines()) if usb_devices else "нет устройств"
    print(f"  UART приводов:  {'[OK] ' + dev_str if has_devices else '[WARN] /dev/ttySTS не найден'}")

    # Chrony status
    chrony_sources = ssh_exec("chronyc sources 2>/dev/null | tail -n +3 | head -2 || true")
    if chrony_sources:
        print(f"  Chrony NTP:\n    {chrony_sources}")
    else:
        print("  Chrony NTP:     [WARN] chronyc не вернул источников")

    # Throttling / Undervoltage check
    throttled = ssh_exec("vcgencmd get_throttled 2>/dev/null || true")
    if throttled:
        print(f"  Питание Pi:     {throttled}")


def run_doctor(robot_ip: Optional[str], config: IjkConfig) -> None:
    print("==================================================================")
    print("                IJKbot — Системная диагностика                   ")
    print("==================================================================")
    check_local_environment(config, robot_ip)
    check_remote_robot(robot_ip, config)
    print("==================================================================")
