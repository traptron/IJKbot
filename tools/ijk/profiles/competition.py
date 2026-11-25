"""Competition profile executor."""

import re
from typing import Optional
from tools.ijk.config import IjkConfig
from tools.ijk.runner import Runner


def run_competition(
    runner: Runner,
    config: IjkConfig,
    role: str = "all",
    mock: bool = False,
    record: bool = False,
    bag_name: Optional[str] = None,
    rviz: bool = True,
) -> None:
    prof = config.profiles.get("competition")
    speed_limit = prof.max_linear_velocity if prof else 0.25
    qr_backend = prof.qr_backend if prof else 'zxing'
    color_profile = prof.color_profile if prof else '1920x1080x15'
    if qr_backend not in ('zxing', 'opencv'):
        raise ValueError('competition.qr_backend must be zxing or opencv')
    if not re.fullmatch(r'[1-9]\d*x[1-9]\d*x[1-9]\d*', color_profile):
        raise ValueError('competition.color_profile must be WIDTHxHEIGHTxFPS')
    wheel_d = config.hardware.wheel_diameter
    wheel_sep = config.hardware.wheel_separation

    print(f"\n==================================================================")
    print(f"  IJKbot — Соревновательный заезд [competition] (Роль: {role})   ")
    print(f"  Регламент: V_max <= {speed_limit} м/с, ROS_DOMAIN_ID={runner.domain_id}")
    print(f"  Калибровка колес: D={wheel_d:.4f}м, L={wheel_sep:.4f}м")
    print(f"==================================================================")

    if record:
        runner.start_bag_recording(bag_name=bag_name)

    # 1. Onboard / robot stack
    if role in ("operator", "all"):
        if mock or runner.local:
            print("[competition] Локальный/Mock запуск базового стека и Nav2 (mock_hardware:=true)...")
            local_system_cmd = [
                "ros2", "launch", "bringup", "system.launch.py",
                "enable_robot:=true",
                "enable_nav:=true",
                "enable_lidar:=false",
                "enable_camera:=false",
                "enable_brain:=false",
                "enable_qr:=false",
                "mock_hardware:=true",
                f"max_linear_velocity:={speed_limit}",
                f"wheel_diameter:={wheel_d}",
                f"wheel_separation:={wheel_sep}",
            ]
            runner.run_local_process(local_system_cmd)
        elif runner.robot_ip:
            print(f"[competition] Бортовой запуск Nav2 и QR ({qr_backend}) на {runner.robot_ip}...")
            remote_launch = (
                f"ros2 launch bringup system.launch.py "
                f"enable_robot:=true enable_nav:=true enable_lidar:=true "
                f"enable_brain:=false enable_camera:=true enable_qr:=true "
                f"qr_backend:={qr_backend} color_profile:={color_profile} depth_profile:=640x480x15 "
                f"mock_hardware:=false max_linear_velocity:={speed_limit} "
                f"wheel_diameter:={wheel_d} wheel_separation:={wheel_sep}"
            )
            runner.start_remote_launch(remote_launch)

    # 2. AI / Dashboard stack
    if role in ("ai", "all"):
        print("[competition] Запуск судейского дашборда на ноутбуке (laptop.launch.py)...")
        laptop_cmd = [
            "ros2", "launch", "bringup", "laptop.launch.py",
            "enable_vision:=false",
            f"mock:={'true' if mock else 'false'}",
        ]
        runner.run_local_process(laptop_cmd)

    # 3. RViz for Operator
    if rviz and role in ("operator", "all"):
        print("[competition] Запуск RViz2...")
        rviz_cmd = [
            "ros2", "run", "rviz2", "rviz2",
            "-d", "src/nav2/rviz/nav2_default_view.rviz",
        ]
        runner.run_local_process(rviz_cmd)

    print("\n[competition] Все системы запущены. Для штатной остановки нажмите Ctrl+C.")
    runner.wait_with_ctrl_c()
