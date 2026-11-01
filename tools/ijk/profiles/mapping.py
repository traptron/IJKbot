"""Mapping profile (SLAM with slam_toolbox and RViz)."""

from pathlib import Path
from typing import Optional
import time

from tools.ijk.config import IjkConfig
from tools.ijk.runner import Runner

REPO_DIR = Path(__file__).resolve().parents[3]


def save_current_map(runner: Runner, map_name: str = "polygon_real") -> bool:
    """Save map from /map topic using nav2 map_saver_cli and normalize image path to relative."""
    output_dir = REPO_DIR / "src" / "nav2" / "maps"
    output_dir.mkdir(parents=True, exist_ok=True)
    target_base = str(output_dir / map_name)

    print(f"\n[save_map] Сохранение карты полигона в: {target_base}...")
    cmd = [
        "ros2", "run", "nav2_map_server", "map_saver_cli",
        "-t", "/map",
        "-f", target_base,
        "--occ", "0.65",
        "--free", "0.15",
    ]
    p = runner.run_local_process(cmd)
    p.wait()

    yaml_file = output_dir / f"{map_name}.yaml"
    pgm_file = output_dir / f"{map_name}.pgm"

    if yaml_file.exists() and pgm_file.exists():
        # Normalize image: path to just filename for portability between Pi and Laptop
        content = yaml_file.read_text(encoding="utf-8")
        lines = []
        for line in content.splitlines():
            if line.startswith("image:"):
                lines.append(f"image: {pgm_file.name}")
            else:
                lines.append(line)
        yaml_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"[save_map] Карта успешно сохранена:\n  - YAML: {yaml_file}\n  - PGM:  {pgm_file}")
        return True
    else:
        print("[save_map] Ошибка: файлы карты не были созданы map_saver_cli.")
        return False


def run_mapping(
    runner: Runner,
    config: IjkConfig,
    teleop: bool = False,
    save_name: Optional[str] = None,
    mock: bool = False,
    record: bool = False,
    bag_name: Optional[str] = None,
    rviz: bool = True,
) -> None:
    prof = config.profiles.get("mapping")
    speed_limit = prof.max_linear_velocity if prof else 0.20

    print(f"\n==================================================================")
    print(f"  IJKbot — Картографирование помещения (SLAM) [mapping]            ")
    print(f"  Макс. скорость: {speed_limit} м/с, ROS_DOMAIN_ID={runner.domain_id}")
    print(f"==================================================================")

    if record:
        runner.start_bag_recording(bag_name=bag_name)

    # 1. Start SLAM stack
    if mock or runner.local:
        print("[mapping] Запуск SLAM Toolbox локально (mock_hardware:=true)...")
        cmd = [
            "ros2", "launch", "bringup", "mapping.launch.py",
            "mock_hardware:=true",
            f"max_linear_velocity:={speed_limit}",
        ]
        runner.run_local_process(cmd)
    elif runner.robot_ip:
        print(f"[mapping] Запуск SLAM Toolbox и лидара на Raspberry Pi ({runner.robot_ip})...")
        remote_launch = (
            f"ros2 launch bringup mapping.launch.py "
            f"mock_hardware:=false max_linear_velocity:={speed_limit}"
        )
        runner.start_remote_launch(remote_launch)

    # 2. RViz locally
    if rviz:
        print("[mapping] Запуск RViz2 (отображение сетки и строящейся карты /map)...")
        rviz_cmd = [
            "ros2", "run", "rviz2", "rviz2",
            "-d", "src/nav2/rviz/nav2_default_view.rviz",
        ]
        runner.run_local_process(rviz_cmd)

    # 3. Optional teleop
    if teleop:
        print("[mapping] Запуск клавиатурного телеуправления в фокусе...")
        teleop_cmd = [
            "ros2", "run", "teleop_twist_keyboard", "teleop_twist_keyboard",
            "--ros-args",
            "-r", "/cmd_vel:=/cmd_vel_sm",
            "-p", f"speed:={speed_limit}",
            "-p", "turn:=0.6",
        ]
        runner.run_local_process(teleop_cmd, interactive=True)

    print("\n[mapping] SLAM активен. По завершении нажмите Ctrl+C.")
    try:
        runner.wait_with_ctrl_c()
    finally:
        if save_name:
            save_current_map(runner, map_name=save_name)

