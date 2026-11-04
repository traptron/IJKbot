"""Operations and maintenance: code updates, chrony sync, and map saving."""

from pathlib import Path
from typing import Optional
import subprocess

from tools.ijk.config import IjkConfig
from tools.ijk.env import build_base_environment, build_shell_command
from tools.ijk.profiles.mapping import save_current_map
from tools.ijk.profiles.netops import run_ops_timesync, run_ops_wifi, run_ops_bag_export
from tools.ijk.runner import Runner

REPO_DIR = Path(__file__).resolve().parents[2]


def run_ops_update(runner: Runner, config: IjkConfig) -> None:
    print("\n=== Обновление репозитория IJKbot (локально и на Pi) ===")

    # 1. Local build
    print("[update] 1/2: Сборка пакетов colcon на ноутбуке...")
    cmd, _ = build_shell_command("colcon build --symlink-install", repo_dir=REPO_DIR)
    env = build_base_environment(config.network.domain_id, config.network.rmw, runner.robot_ip)
    res = subprocess.run(cmd, env=env)
    if res.returncode == 0:
        print("[update] Локальная сборка успешно завершена.")
    else:
        print(f"[update] Ошибка сборки локально (код {res.returncode})!")

    # 2. Remote update & build on Pi
    if runner.robot_ip and not runner.local:
        user = config.network.default_user
        ws = config.network.remote_ws
        print(f"\n[update] 2/2: Сборка на Raspberry Pi ({user}@{runner.robot_ip})...")
        remote_cmd = (
            f"cd {ws} && git pull origin dev 2>/dev/null || true && "
            f"source /opt/ros/jazzy/setup.bash && colcon build --symlink-install"
        )
        ssh_cmd = ["ssh", f"{user}@{runner.robot_ip}", remote_cmd]
        subprocess.run(ssh_cmd)
        print("[update] Сборка на Raspberry Pi завершена.")


def run_ops_chrony(runner: Runner, config: IjkConfig) -> None:
    print("\n=== Проверка синхронизации времени Chrony ===")
    print("[chrony] Статус на Ноутбуке:")
    subprocess.run(["chronyc", "sources", "-v"], check=False)
    if runner.robot_ip and not runner.local:
        user = config.network.default_user
        print(f"\n[chrony] Статус на Raspberry Pi ({runner.robot_ip}):")
        subprocess.run(["ssh", f"{user}@{runner.robot_ip}", "chronyc sources -v"], check=False)


def run_ops_save_map(runner: Runner, map_name: str = "polygon_real") -> None:
    save_current_map(runner, map_name=map_name)
