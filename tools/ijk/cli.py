#!/usr/bin/env python3
"""Unified CLI dispatcher for IJKbot.

Supported profiles & tools:
  competition  — Соревновательный заезд (LLM + Nav2 + QR + Dashboard)
  showcase     — Презентация на ДОД (сенсоры, видео, экран)
  teleop       — Ручное управление (клавиатура / геймпад DS4)
  mapping      — Картографирование помещения (SLAM Toolbox + RViz)
  navigate     — Автономная навигация Nav2 по сохраненной карте
  bench        — Стендовые тесты (motors на вывешенных колесах, lidar, camera, qr, driver)
  doctor       — Системная диагностика (сеть, порты, сенсоры, Chrony, Ollama)
  stop         — Экстренная остановка всех систем (/cmd_vel_emergency)
  attach       — Подключение к сессии tmux на Raspberry Pi
  logs         — Просмотр логов сессии на Raspberry Pi
  ops          — Обслуживание (update, chrony, save-map)
  discover     — Поиск робота в локальной сети
"""

from pathlib import Path
from typing import List, Optional
import argparse
import os
import sys

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.ijk.config import load_config
from tools.ijk.discovery import discover_robot
from tools.ijk.role import resolve_role
from tools.ijk.runner import Runner
from tools.ijk.profiles.competition import run_competition
from tools.ijk.profiles.showcase import run_showcase
from tools.ijk.profiles.teleop import run_teleop
from tools.ijk.profiles.mapping import run_mapping
from tools.ijk.profiles.navigate import run_navigate
from tools.ijk.profiles.bench import run_bench_motors, run_isolated_subsystem
from tools.ijk.profiles.odom_calib import run_odom_calibration
from tools.ijk.profiles.doctor import run_doctor
from tools.ijk.profiles.ops import (
    run_ops_update,
    run_ops_chrony,
    run_ops_save_map,
    run_ops_timesync,
    run_ops_wifi,
    run_ops_bag_export,
)


def show_interactive_menu() -> str:
    print("\n=======================================================")
    print("           IJKbot — Единый командный центр             ")
    print("=======================================================")
    print("  1) competition  — Соревновательный заезд (LLM + Nav2 + QR)")
    print("  2) showcase     — Презентация на ДОД (сенсоры, видео, экран)")
    print("  3) teleop       — Ручное управление (клавиатура / геймпад)")
    print("  4) mapping      — Картографирование помещения (SLAM Toolbox)")
    print("  5) navigate     — Автономная навигация Nav2 по карте")
    print("  6) bench motors — Тест моторов на вывешенных колесах")
    print("  7) odom-calib   — Мастер калибровки одометрии (D колес, L колеи)")
    print("  8) timesync     — Принудительное выравнивание времени (ноутбук -> Pi)")
    print("  9) wifi         — Управление Wi-Fi сетями на роботе")
    print("  10) doctor      — Системная диагностика")
    print("  11) ops update  — Обновление и сборка (локально + Pi)")
    print("  12) stop        — Экстренная остановка всех систем")
    print("  0) Выход")
    print("=======================================================")
    choice = input("Выберите действие [0-13]: ").strip()
    mapping = {
        "1": "competition",
        "2": "showcase",
        "3": "teleop",
        "4": "mapping",
        "5": "navigate",
        "6": "bench-motors",
        "7": "bench-odom-calib",
        "8": "ops-timesync",
        "9": "ops-wifi",
        "10": "doctor",
        "11": "ops-update",
        "12": "stop",
    }
    return mapping.get(choice, "")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ijk",
        description="IJKbot Unified CLI: соревнования, ДОД, телеоп, навигация, SLAM, стендовые тесты",
    )
    parser.add_argument("--host", type=str, help="IP адрес Raspberry Pi (переопределяет автопоиск)")
    parser.add_argument("--mock", action="store_true", help="Режим симуляции моторов без реального железа")
    parser.add_argument("--local", action="store_true", help="Запуск всего стека локально на ноутбуке")
    parser.add_argument("--role", choices=["auto", "all", "ai", "operator"], default="auto", help="Роль машины (ноутбук 1 / 2)")
    parser.add_argument("--record", action="store_true", help="Записывать rosbag ключевых топиков")
    parser.add_argument("--bag-name", type=str, help="Имя директории для сохраняемого rosbag")
    parser.add_argument("--no-discovery", action="store_true", help="Не выполнять автопоиск робота")

    subparsers = parser.add_subparsers(dest="command", help="Команда или профиль")

    # competition
    subparsers.add_parser("competition", help="Соревновательный заезд (LLM + Nav2 + QR)")

    # showcase
    p_showcase = subparsers.add_parser("showcase", help="Презентация на ДОД (сенсоры + экран)")
    p_showcase.add_argument("--gamepad", dest="use_gamepad", action="store_true", default=True, help="Использовать геймпад DS4 (по умолчанию)")
    p_showcase.add_argument("--keyboard", dest="use_gamepad", action="store_false", help="Использовать клавиатуру вместо геймпада")

    # teleop
    p_teleop = subparsers.add_parser("teleop", help="Ручное управление")
    p_teleop.add_argument("--gamepad", action="store_true", help="Использовать геймпад DS4 вместо клавиатуры")
    p_teleop.add_argument("--web", action="store_true", help="Управление через веб-джойстик без DS4 и клавиатуры")
    p_teleop.add_argument("--speed", type=float, help="Потолок линейной скорости (м/с, до 0.40)")

    # mapping
    p_mapping = subparsers.add_parser("mapping", help="Построение карты (SLAM Toolbox + RViz)")
    p_mapping.add_argument("--teleop", action="store_true", help="Открыть клавиатурный телеоп в фокусе")
    p_mapping.add_argument("--save-map", type=str, help="Имя для сохранения карты при выходе")

    # navigate
    p_nav = subparsers.add_parser("navigate", help="Автономная навигация Nav2 по сохраненной карте")
    p_nav.add_argument("--map", type=str, help="Имя или путь к карте .yaml")
    p_nav.add_argument("--use-amcl", action="store_true", help="Использовать AMCL вместо чистой одометрии")

    # bench
    p_bench = subparsers.add_parser("bench", help="Стендовые тесты железа")
    p_bench.add_argument("target", choices=["motors", "odom-calib", "lidar", "camera", "driver", "qr"], help="Цель теста")

    # doctor
    subparsers.add_parser("doctor", help="Диагностика системы")

    # stop
    subparsers.add_parser("stop", help="Экстренная остановка")

    # attach & logs
    subparsers.add_parser("attach", help="Подключиться к сессии tmux на Raspberry Pi")
    p_logs = subparsers.add_parser("logs", help="Показать логи сессии на Raspberry Pi")
    p_logs.add_argument("-n", "--lines", type=int, default=50, help="Количество строк")

    # ops
    p_ops = subparsers.add_parser("ops", help="Обслуживание")
    p_ops.add_argument("action", choices=["update", "chrony", "timesync", "wifi", "bag-export", "save-map"], help="Действие обслуживания")
    p_ops.add_argument("--name", type=str, default="polygon_real", help="Имя карты для действия save-map")
    p_ops.add_argument("--profile", type=str, help="Профиль Wi-Fi (tplink, dev, scan, list)")
    p_ops.add_argument("--force", action="store_true", help="Принудительное выравнивание времени (timesync)")
    p_ops.add_argument("--bag", type=str, help="Путь к rosbag директории (bag-export)")

    for profile_parser in (subparsers.choices['competition'], p_showcase, p_mapping, p_nav):
        profile_parser.add_argument("--no-rviz", action="store_true", help="Не запускать RViz")

    # discover
    subparsers.add_parser("discover", help="Найти робота в сети и сохранить кэш")

    args = parser.parse_args(argv)

    command = args.command
    if not command:
        command = show_interactive_menu()
        if not command:
            print("Выход.")
            return 0

    config = load_config()

    from tools.ijk.discovery import is_ssh_responsive

    # Determine robot IP
    robot_ip = None
    if args.host:
        if is_ssh_responsive(args.host, config.network.default_user, timeout=4):
            robot_ip = args.host
        else:
            print(f"\n[ERROR] Указанный хост {args.host} не отвечает по SSH ({config.network.default_user}@{args.host})!")
            print("  Проверьте IP адрес робота или запустите с флагом '--mock' для симуляции без робота.")
            return 1
    elif not args.mock and not args.local and not args.no_discovery:
        # Fast discover robot if needed
        robot_ip = discover_robot(config, verbose=(command == "discover"))

    # Validate robot reachability for profiles that require it
    requires_robot = command in ("competition", "showcase", "teleop", "mapping", "navigate", "bench")
    if requires_robot and not args.mock and not args.local and not robot_ip:
        print("\n[ERROR] Робот не обнаружен в локальной сети!")
        print("  Решения:")
        print("    1. Проверьте питание робота и Wi-Fi сеть.")
        print("    2. Укажите IP вручную через '--host <IP>'.")
        print("    3. Для тестирования на ноутбуке без робота запустите с флагом '--mock'.")
        return 1

    runner = Runner(config, robot_ip=robot_ip, mock=args.mock, local=args.local)
    role = resolve_role(args.role, mock=args.mock, is_local=args.local)

    if command == "competition":
        run_competition(runner, config, role=role, mock=args.mock, record=args.record, bag_name=args.bag_name, rviz=not getattr(args, "no_rviz", False))
    elif command == "showcase":
        run_showcase(runner, config, mock=args.mock, gamepad=getattr(args, "use_gamepad", True), record=args.record, bag_name=args.bag_name, rviz=not getattr(args, "no_rviz", False))
    elif command == "teleop":
        run_teleop(runner, config, use_gamepad=getattr(args, "gamepad", False), web_mode=getattr(args, "web", False), speed=getattr(args, "speed", None), mock=args.mock, record=args.record, bag_name=args.bag_name)
    elif command == "mapping":
        run_mapping(runner, config, teleop=getattr(args, "teleop", False), save_name=getattr(args, "save_map", None), mock=args.mock, record=args.record, bag_name=args.bag_name, rviz=not getattr(args, "no_rviz", False))
    elif command == "navigate":
        run_navigate(runner, config, map_name=getattr(args, "map", None), use_amcl=getattr(args, "use_amcl", False), mock=args.mock, record=args.record, bag_name=args.bag_name, rviz=not getattr(args, "no_rviz", False))
    elif command in ("bench", "bench-motors", "bench-odom-calib"):
        target = getattr(args, "target", "motors") if command == "bench" else ("odom-calib" if command == "bench-odom-calib" else "motors")
        if target == "motors":
            run_bench_motors(runner, config, mock=args.mock)
        elif target == "odom-calib":
            run_odom_calibration(runner, config, mock=args.mock)
        else:
            run_isolated_subsystem(runner, target, mock=args.mock)
    elif command == "doctor":
        run_doctor(robot_ip, config)
    elif command == "stop":
        runner.emergency_stop()
    elif command == "attach":
        runner.attach_remote()
    elif command == "logs":
        runner.logs_remote(lines=getattr(args, "lines", 50))
    elif command in ("ops", "ops-update", "ops-timesync", "ops-wifi"):
        if command == "ops-timesync":
            action = "timesync"
        elif command == "ops-wifi":
            action = "wifi"
        elif command == "ops-update":
            action = "update"
        else:
            action = getattr(args, "action", "update")

        if action == "update":
            run_ops_update(runner, config)
        elif action == "chrony":
            run_ops_chrony(runner, config)
        elif action == "timesync":
            run_ops_timesync(runner, config, force=getattr(args, "force", False))
        elif action == "wifi":
            run_ops_wifi(runner, config, profile=getattr(args, "profile", None))
        elif action == "bag-export":
            run_ops_bag_export(runner, bag=getattr(args, "bag", None))
        elif action == "save-map":
            run_ops_save_map(runner, map_name=getattr(args, "name", "polygon_real"))
    elif command == "discover":
        if robot_ip:
            print(f"[discover] Робот доступен по адресу: {robot_ip}")
            return 0
        else:
            print("[discover] Робот не найден в сети.")
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
