"""Navigate profile: Autonomous Nav2 navigation on saved map without LLM."""

from pathlib import Path
from typing import Optional
import subprocess
import shlex
import tempfile
import yaml

from tools.ijk.config import IjkConfig
from tools.ijk.runner import Runner

REPO_DIR = Path(__file__).resolve().parents[3]
MAPS_DIR = REPO_DIR / "src" / "nav2" / "maps"


def sync_map_to_pi(runner: Runner, map_path: Path) -> None:
    """Copy the current YAML and its referenced image; abort on any sync error."""
    if not runner.robot_ip or runner.local:
        return
    data = yaml.safe_load(map_path.read_text(encoding='utf-8'))
    image = (map_path.parent / data['image']).resolve()
    if not image.is_file():
        raise ValueError(f'Изображение карты не найдено: {image}')
    remote_maps = f"{runner.remote_ws}/src/nav2/maps/"
    result = runner.run_remote_ssh(f'mkdir -p {shlex.quote(remote_maps)}')
    if result.returncode:
        raise RuntimeError(f'Не удалось подготовить каталог карт на Pi: {result.stderr}')
    # Normalizing the image reference makes absolute local paths portable to Pi.
    with tempfile.TemporaryDirectory(prefix='ijk-map-sync-') as directory:
        normalized = Path(directory) / map_path.name
        data['image'] = image.name
        normalized.write_text(yaml.safe_dump(data), encoding='utf-8')
        command = ["scp", "-o", "BatchMode=yes", "-o", "ConnectTimeout=4",
                   str(image), str(normalized), f"{runner.user}@{runner.robot_ip}:{shlex.quote(remote_maps)}"]
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise RuntimeError(f'Не удалось передать карту на Pi: {result.stderr}')


def run_navigate(
    runner: Runner,
    config: IjkConfig,
    map_name: Optional[str] = None,
    use_amcl: bool = False,
    mock: bool = False,
    record: bool = False,
    bag_name: Optional[str] = None,
    rviz: bool = True,
) -> None:
    prof = config.profiles.get("navigate")
    speed_limit = prof.max_linear_velocity if prof else 0.25

    # Resolve map file
    selected_map = map_name or (prof.map if prof else "polygon_empty_4x4.yaml")
    map_file = Path(selected_map)
    if not map_file.is_file():
        if (MAPS_DIR / selected_map).is_file():
            map_file = MAPS_DIR / selected_map
        elif (MAPS_DIR / f"{selected_map}.yaml").is_file():
            map_file = MAPS_DIR / f"{selected_map}.yaml"
        else:
            raise ValueError(f"Карта не найдена: {selected_map}")

    print(f"\n==================================================================")
    print(f"  IJKbot — Автономная навигация Nav2 [navigate]                    ")
    print(f"  Карта: {map_file.name}, Локализация: {'AMCL' if use_amcl else 'Чистая одометрия'}")
    print(f"  Макс. скорость: {speed_limit} м/с, ROS_DOMAIN_ID={runner.domain_id}")
    print(f"==================================================================")

    if record:
        runner.start_bag_recording(bag_name=bag_name)

    # Sync map to Pi
    sync_map_to_pi(runner, map_file)

    # 1. Onboard Nav2 and robot stack
    if mock or runner.local:
        print("[navigate] Локальный запуск стека робота и Nav2 (mock_hardware:=true)...")
        cmd = [
            "ros2", "launch", "bringup", "system.launch.py",
            "enable_robot:=true",
            "enable_nav:=true",
            "enable_lidar:=false",
            "enable_camera:=false",
            "enable_brain:=false",
            "enable_qr:=false",
            "mock_hardware:=true",
            f"use_amcl:={'true' if use_amcl else 'false'}",
            f"map:={map_file}",
            f"max_linear_velocity:={speed_limit}",
            f"wheel_diameter:={config.hardware.wheel_diameter}",
            f"wheel_separation:={config.hardware.wheel_separation}",
        ]
        runner.run_local_process(cmd)
    elif runner.robot_ip:
        print(f"[navigate] Запуск Nav2 на Raspberry Pi ({runner.robot_ip})...")
        remote_map_path = f"{runner.remote_ws}/src/nav2/maps/{map_file.name}"
        remote_launch = (
            f"ros2 launch bringup system.launch.py "
            f"enable_robot:=true enable_nav:=true enable_lidar:=true "
            f"enable_brain:=false enable_qr:=false "
            f"mock_hardware:=false "
            f"use_amcl:={'true' if use_amcl else 'false'} "
            f"map:='{remote_map_path}' "
            f"max_linear_velocity:={speed_limit} "
            f"wheel_diameter:={config.hardware.wheel_diameter} "
            f"wheel_separation:={config.hardware.wheel_separation}"
        )
        runner.start_remote_launch(remote_launch)

    # 2. RViz locally
    if rviz:
        print("[navigate] Запуск RViz2 (отправка целей через кнопку 'Nav2 Goal')...")
        rviz_cmd = [
            "ros2", "run", "rviz2", "rviz2",
            "-d", "src/nav2/rviz/nav2_default_view.rviz",
        ]
        runner.run_local_process(rviz_cmd)

    print("\n[navigate] Навигация активна. Для выхода нажмите Ctrl+C.")
    runner.wait_with_ctrl_c()

