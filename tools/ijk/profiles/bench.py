"""Benchmarking and isolated hardware test profile."""

from typing import Optional
import sys
import time

from tools.ijk.config import IjkConfig
from tools.ijk.runner import Runner


def run_bench_motors(runner: Runner, config: IjkConfig, mock: bool = False) -> None:
    print("\n=======================================================")
    print("ВНИМАНИЕ: Тестирование моторов Feetech STS3215")
    print("Колеса робота ДОЛЖНЫ быть вывешены в воздухе!")
    print("=======================================================")

    if not mock:
        answer = input("Колеса робота находятся в воздухе и вращению ничего не мешает? [y/N]: ").strip().lower()
        if answer != "y":
            print("[bench] Тест отменен пользователем.")
            return

    print("\n[bench] Шаг 1/2: Запуск драйвера приводов STS3215...")
    if mock or runner.local:
        runner.run_local_process([
            "ros2", "launch", "driver", "driver.launch.py",
            "mock_hardware:=true",
        ])
    elif runner.robot_ip:
        runner.start_remote_launch(
            "ros2 launch bringup robot.launch.py enable_camera:=false enable_lidar:=false mock_hardware:=false max_linear_velocity:=0.10"
        )
    time.sleep(2.5)

    print("[bench] Шаг 2/2: Отправка скорости 0.10 м/с (вперед) в течение 2 секунд...")
    # Send continuous 10 Hz pulses for 2 seconds to satisfy 200ms watchdog
    pub_cmd = [
        "ros2", "topic", "pub", "-r", "10",
        "/cmd_vel", "geometry_msgs/msg/Twist",
        "{linear: {x: 0.1, y: 0.0, z: 0.0}, angular: {x: 0.0, y: 0.0, z: 0.0}}",
    ]
    p = runner.run_local_process(pub_cmd)
    time.sleep(2.0)
    p.terminate()

    print("[bench] Остановка моторов...")
    runner.emergency_stop()
    print("[bench] Тест моторов завершен. Проверьте правильность вращения обоих колес.")


def run_isolated_subsystem(runner: Runner, subsystem: str, mock: bool = False) -> None:
    print(f"\n=== Запуск изолированного теста подсистемы: [{subsystem}] ===")
    if subsystem == "lidar":
        launch_cmd = "ros2 launch bringup robot.launch.py enable_motors:=false enable_camera:=false enable_lidar:=true"
    elif subsystem == "camera":
        launch_cmd = "ros2 launch bringup robot.launch.py enable_motors:=false enable_camera:=true enable_lidar:=false"
    elif subsystem == "driver":
        launch_cmd = f"ros2 launch driver driver.launch.py mock_hardware:={'true' if mock else 'false'}"
    elif subsystem == "qr":
        launch_cmd = "ros2 launch vision qr_reader.launch.py"
    else:
        print(f"[bench] Неизвестная подсистема: {subsystem}. Доступны: lidar, camera, driver, qr")
        return

    if mock or runner.local:
        print(f"[bench] Запуск локально (mock={mock})...")
        runner.run_local_process(launch_cmd.split())
        runner.wait_with_ctrl_c()
    elif runner.robot_ip:
        print(f"[bench] Запуск на Raspberry Pi ({runner.robot_ip})...")
        runner.start_remote_launch(launch_cmd)
        print(f"[bench] Подсистема {subsystem} запущена на Pi. Для выхода нажмите Ctrl+C.")
        runner.wait_with_ctrl_c()
