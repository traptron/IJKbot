"""Odometry calibration interactive wizard."""

import math
from pathlib import Path
import subprocess
import sys
import time

from tools.ijk.config import IjkConfig, save_odom_calibration
from tools.ijk.runner import Runner

REPO_DIR = Path(__file__).resolve().parents[2]


def execute_calib_motion(runner: Runner, mode: str, target: float, speed: float) -> float:
    """Execute motion using odom_calib_worker inside Pixi environment and parse result."""
    worker_script = REPO_DIR / "tools" / "ijk" / "profiles" / "odom_calib_worker.py"
    cmd = [
        "python3", str(worker_script),
        "--mode", mode,
        "--target", str(target),
        "--speed", str(speed),
    ]

    p = runner.run_local_process(cmd)
    result_val = target

    # Monitor output
    try:
        p.wait()
    except KeyboardInterrupt:
        runner.emergency_stop()
        raise

    return result_val


def run_odom_calibration(runner: Runner, config: IjkConfig, mock: bool = False) -> None:
    current_d = config.hardware.wheel_diameter
    current_l = config.hardware.wheel_separation

    print("\n=======================================================")
    print("      IJKbot — Мастер калибровки одометрии             ")
    print("=======================================================")
    print(f"Текущие параметры шасси:")
    print(f"  • Диаметр ведущих колес (D): {current_d * 1000:.2f} мм ({current_d:.4f} м)")
    print(f"  • Колея ведущих колес   (L): {current_l * 1000:.2f} мм ({current_l:.4f} м)")
    print("-------------------------------------------------------")
    print("Выберите режим калибровки:")
    print("  1) Линейная калибровка (дистанция 1.0 м -> диаметр колес D)")
    print("  2) Угловая калибровка  (разворот 3 оборота -> колея L)")
    print("  3) Полная калибровка   (линейная + угловая)")
    print("  4) Сброс параметров к заводским (D=75 мм, L=225 мм)")
    print("  0) Выход")
    print("-------------------------------------------------------")

    choice = input("Ваш выбор [0-4]: ").strip()
    if choice == "0" or not choice:
        print("[калибровка] Выход без изменений.")
        return

    if choice == "4":
        saved_file = save_odom_calibration(0.075, 0.225)
        print(f"\n[OK] Параметры сброшены к заводским (D=0.075м, L=0.225м) в {saved_file}")
        return

    # Start low-level driver stack if not already running
    if mock or runner.local:
        print("\n[калибровка] Запуск драйвера робота локально (mock_hardware:=true)...")
        launch_cmd = [
            "ros2", "launch", "bringup", "robot.launch.py",
            "enable_camera:=false",
            "enable_lidar:=false",
            "mock_hardware:=true",
            f"wheel_diameter:={current_d}",
            f"wheel_separation:={current_l}",
            "max_linear_velocity:=0.20",
        ]
        runner.run_local_process(launch_cmd)
    elif runner.robot_ip:
        if not runner.is_remote_tmux_running():
            print(f"\n[калибровка] Запуск драйвера моторов на Raspberry Pi ({runner.robot_ip})...")
            remote_launch = (
                f"ros2 launch bringup robot.launch.py "
                f"enable_camera:=false enable_lidar:=false mock_hardware:=false "
                f"wheel_diameter:={current_d} wheel_separation:={current_l} "
                f"max_linear_velocity:=0.20"
            )
            runner.start_remote_launch(remote_launch)

    print("[калибровка] Ожидание инициализации топика /odom (2.5 сек)...")
    time.sleep(2.5)

    new_d = current_d
    new_l = current_l

    # 1. Linear Calibration
    if choice in ("1", "3"):
        print("\n-------------------------------------------------------")
        print("  ШАГ: ЛИНЕЙНАЯ КАЛИБРОВКА (ДИАМЕТР КОЛЕС)")
        print("-------------------------------------------------------")
        print("1. Поставьте робота передней осью на нулевую отметку рулетки.")
        print("2. Убедитесь, что перед роботом свободно не менее 1.5 метров.")
        input("Нажмите [Enter] для старта движения на 1.0 метр...")

        target_dist = 1.0  # 1 metre
        print(f"[калибровка] Робот едет вперёд ровно {target_dist:.2f} м по энкодерам...")
        try:
            execute_calib_motion(runner, mode="linear", target=target_dist, speed=0.12)
        except KeyboardInterrupt:
            print("\n[калибровка] Прервано оператором.")
            runner.emergency_stop()
            return

        print("\n[OK] Движение завершено. Робот проехал 1.000 м по одометрии.")
        while True:
            val_str = input("Введите фактическое расстояние по рулетке в метрах [Enter = 1.00]: ").strip()
            if not val_str:
                measured_dist = 1.0
                break
            try:
                measured_dist = float(val_str.replace(",", "."))
                if 0.5 <= measured_dist <= 1.5:
                    break
                print("Расстояние должно быть в пределах 0.5..1.5 м. Попробуйте снова.")
            except ValueError:
                print("Некорректное число.")

        k_dist = measured_dist / target_dist
        new_d = current_d * k_dist
        print(f"\nРезультат линейной калибровки:")
        print(f"  • Коэффициент коррекции: {k_dist:.5f}")
        print(f"  • Новый диаметр колес D: {new_d * 1000:.2f} мм (было: {current_d * 1000:.2f} мм)")

    # 2. Angular Calibration
    if choice in ("2", "3"):
        print("\n-------------------------------------------------------")
        print("  ШАГ: УГЛОВАЯ КАЛИБРОВКА (ШИРИНА КОЛЕИ)")
        print("-------------------------------------------------------")
        print("1. Отметьте стартовое направление робота (курс 0°).")
        print("2. Робот совершит ровно 3 полных разворота на месте (1080° по энкодерам).")
        input("Нажмите [Enter] для старта вращения...")

        num_turns = 3
        target_rad = num_turns * 2.0 * math.pi
        print(f"[калибровка] Вращение на месте ({num_turns} оборота = 1080°)...")
        try:
            execute_calib_motion(runner, mode="angular", target=target_rad, speed=0.45)
        except KeyboardInterrupt:
            print("\n[калибровка] Прервано оператором.")
            runner.emergency_stop()
            return

        print(f"\n[OK] Вращение завершено. Пройдено ровно {num_turns * 360}° по одометрии.")
        print("Оцените ориентацию робота относительно начальной отметки:")
        print("  • Смотрит точно в цель: введите 0")
        print("  • Недокрутил влево: введите со знаком минус (например, -12)")
        print("  • Перекрутил вправо: введите со знаком плюс  (например, +10)")

        while True:
            err_str = input("Угловая ошибка в градусах (-180..+180) [Enter = 0]: ").strip()
            if not err_str:
                err_deg = 0.0
                break
            try:
                err_deg = float(err_str.replace(",", "."))
                if -180.0 <= err_deg <= 180.0:
                    break
                print("Ошибка должна быть в диапазоне -180..+180 градусов.")
            except ValueError:
                print("Некорректное число.")

        total_actual_deg = (num_turns * 360.0) + err_deg
        k_turn = (num_turns * 360.0) / total_actual_deg
        new_l = current_l * k_turn
        print(f"\nРезультат угловой калибровки:")
        print(f"  • Фактический угол разворота: {total_actual_deg:.1f}°")
        print(f"  • Коэффициент коррекции:     {k_turn:.5f}")
        print(f"  • Новая эффективная колея L: {new_l * 1000:.2f} мм (было: {current_l * 1000:.2f} мм)")

    # Stop motor driver
    runner.emergency_stop()

    # Summary and Save
    print("\n=======================================================")
    print("              ИТОГИ КАЛИБРОВКИ ОДОМЕТРИИ               ")
    print("=======================================================")
    print(f"  Диаметр колес (D): {current_d * 1000:.2f} мм  -->  {new_d * 1000:.2f} мм ({new_d:.6f} м)")
    print(f"  Ширина колеи  (L): {current_l * 1000:.2f} мм  -->  {new_l * 1000:.2f} мм ({new_l:.6f} м)")
    print("=======================================================")

    save_choice = input("Сохранить параметры в config/ijk.local.yaml? [Y/n]: ").strip().lower()
    if save_choice in ("", "y", "yes", "д", "да"):
        saved_file = save_odom_calibration(new_d, new_l)
        print(f"\n[OK] Калибровка успешно сохранена в: {saved_file}")
        print("Новые параметры будут автоматически применяться во всех профилях запуска (competition, navigate, etc.)!")
    else:
        print("[калибровка] Изменения отменены пользователем.")

