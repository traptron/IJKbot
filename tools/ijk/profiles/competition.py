"""Competition profile executor."""

import re
from typing import Optional
import json
import hashlib
import os
from pathlib import Path
import shlex
import subprocess
import yaml

from tools.ijk.profiles.navigate import sync_map_to_pi
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
    terrain_3d: bool = False,
    bridge_reference: Optional[str] = None,
    sensor_mounts_file: str = "",
) -> None:
    arena_file = os.environ.get('IJKBOT_ARENA_FILE')
    victim_model_path = os.environ.get('IJKBOT_VICTIM_MODEL_PATH', '').strip()
    victim_launch_args = [f'victim_model_path:={victim_model_path}'] if victim_model_path else []
    if terrain_3d and not arena_file:
        raise ValueError('Для --3d укажите IJKBOT_ARENA_FILE с утверждённой картой')
    map_file = None
    reference = None
    if arena_file:
        arena = json.loads(Path(arena_file).read_text())
        if arena.get('training_state') != 'MAP_READY' or not arena.get('version'):
            raise ValueError('Сначала сохраните проверенную семантическую карту')
        map_file = Path(arena['occupancy_map']).resolve()
        if not map_file.is_file():
            raise ValueError(f'Нет навигационной карты {map_file}')
        if terrain_3d:
            reference = Path(bridge_reference or Path(arena_file).with_name('bridge.json')).resolve(strict=True)
            bridge = json.loads(reference.read_text())
            if (bridge['arena_version'] != arena['version']
                    or bridge['occupancy_sha256'] != arena['occupancy_sha256']):
                raise ValueError('Эталон моста записан для другой версии карты')
            image = map_file.parent / yaml.safe_load(map_file.read_text())['image']
            if hashlib.sha256(map_file.read_bytes() + image.read_bytes()).hexdigest() != arena['occupancy_sha256']:
                raise ValueError('Файлы утверждённой карты изменились')
        if role in ('operator', 'all') and not mock:
            sync_map_to_pi(runner, map_file)
    prof = config.profiles.get("competition")
    speed_limit = prof.max_linear_velocity if prof else 0.25
    if terrain_3d:
        speed_limit = float(bridge['calibration']['max_speed_m_s'])
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
        if terrain_3d:
            command = ['ros2', 'launch', 'bringup', 'terrain_competition.launch.py',
                       f'wheel_diameter:={wheel_d}', f'wheel_separation:={wheel_sep}',
                       f'lidar_serial_port:={config.hardware.lidar_port}',
                       f'lidar_serial_baudrate:={config.hardware.lidar_baudrate}',
                       f'motors_serial_port:={config.hardware.motors_port}',
                       f'sensor_mounts_file:={sensor_mounts_file}', *victim_launch_args]
            if mock or runner.local:
                runner.run_local_process(command + [f'map:={map_file}', f'bridge_reference:={reference}',
                                                    'mock_hardware:=true', 'enable_lidar:=false', 'replay:=true'])
            elif runner.robot_ip:
                maps = f'{runner.remote_ws}/src/nav2/maps'
                remote_reference = f'{maps}/bridge-{arena["version"]}.json'
                subprocess.run(['scp', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=4', str(reference),
                                f'{runner.user}@{runner.robot_ip}:{shlex.quote(remote_reference)}'],
                               check=True, timeout=30)
                runner.start_remote_launch(shlex.join(command + [
                    f'map:={maps}/{map_file.name}', f'bridge_reference:={remote_reference}',
                    'mock_hardware:=false',
                ]))
        elif mock or runner.local:
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
            if map_file:
                local_system_cmd.append(f"map:={map_file}")
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
            if victim_launch_args:
                remote_launch += ' ' + shlex.join(victim_launch_args)
            if map_file:
                remote_map = f'{runner.remote_ws}/src/nav2/maps/{map_file.name}'
                remote_launch += ' map:=' + shlex.quote(remote_map)
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
