"""Showcase profile for Open Doors Days (ДОД) and live sensor presentations."""

from typing import Optional
from tools.ijk.config import IjkConfig
from tools.ijk.runner import Runner


def run_showcase(
    runner: Runner,
    config: IjkConfig,
    mock: bool = False,
    gamepad: bool = True,
    record: bool = False,
    bag_name: Optional[str] = None,
    rviz: bool = True,
) -> None:
    prof = config.profiles.get("showcase")
    speed_limit = prof.max_linear_velocity if prof else 0.25

    print(f"\n==================================================================")
    print(f"  IJKbot — Презентация сенсоров на ДОД [showcase]                 ")
    print(f"  Режим: Большой экран + сенсоры + {'геймпад DS4' if gamepad else 'клавиатура'}")
    print(f"==================================================================")

    if record:
        runner.start_bag_recording(bag_name=bag_name)

    # 1. Onboard sensors and drivers
    if mock or runner.local:
        print("[showcase] Запуск базового стека робота локально (mock_hardware:=true)...")
        local_robot_cmd = [
            "ros2", "launch", "bringup", "robot.launch.py",
            "enable_lidar:=false",
            "enable_camera:=false",
            "mock_hardware:=true",
            f"max_linear_velocity:={speed_limit}",
            f"wheel_diameter:={config.hardware.wheel_diameter}",
            f"wheel_separation:={config.hardware.wheel_separation}",
        ]
        runner.run_local_process(local_robot_cmd)
    elif runner.robot_ip:
        print(f"[showcase] Запуск сенсоров на Raspberry Pi ({runner.robot_ip})...")
        gamepad_cmd = "ros2 run DS4_teleop teleop_node --ros-args -r /cmd_vel:=/cmd_vel_joy & " if gamepad else ""
        remote_launch = (
            f"{gamepad_cmd}"
            f"ros2 launch bringup robot.launch.py "
            f"enable_lidar:=true enable_camera:=false mock_hardware:=false "
            f"max_linear_velocity:={speed_limit} "
            f"wheel_diameter:={config.hardware.wheel_diameter} "
            f"wheel_separation:={config.hardware.wheel_separation}"
        )
        runner.start_remote_launch(remote_launch)

    # 2. Local visualization: RViz2 + Vision QR / camera preview
    if rviz:
        print("[showcase] Запуск RViz2 для показа лидара и состояния робота...")
        rviz_cmd = [
            "ros2", "run", "rviz2", "rviz2",
            "-d", "src/nav2/rviz/nav2_default_view.rviz",
        ]
        runner.run_local_process(rviz_cmd)

    print("[showcase] Запуск ноды детекции QR-кодов...")
    vision_cmd = ["ros2", "launch", "vision", "qr_reader.launch.py"]
    runner.run_local_process(vision_cmd)

    # If keyboard was chosen instead of gamepad, start keyboard teleop in interactive mode
    if not gamepad:
        print(f"[showcase] Запуск клавиатурного управления (топик /cmd_vel_sm)...")
        teleop_cmd = [
            "ros2", "run", "teleop_twist_keyboard", "teleop_twist_keyboard",
            "--ros-args",
            "-r", "/cmd_vel:=/cmd_vel_sm",
            "-p", f"speed:={speed_limit}",
            "-p", "turn:=0.8",
        ]
        runner.run_local_process(teleop_cmd, interactive=True)

    print("\n[showcase] Презентация активна. Для остановки нажмите Ctrl+C.")
    runner.wait_with_ctrl_c()
