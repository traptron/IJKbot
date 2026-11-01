"""Process orchestration for IJKbot: remote tmux sessions and local subprocesses."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Union
import os
import base64
import re
import signal
import subprocess
import sys
import time

from tools.ijk.config import IjkConfig
from tools.ijk.env import build_base_environment, build_shell_command, get_source_ip_for_target

TMUX_SESSION = "ijk"
REPO_DIR = Path(__file__).resolve().parents[2]


@dataclass
class ProcessHandle:
    name: str
    popen: Optional[subprocess.Popen] = None
    is_remote: bool = False


class Runner:
    def __init__(self, config: IjkConfig, robot_ip: Optional[str] = None, mock: bool = False, local: bool = False):
        self.config = config
        self.robot_ip = robot_ip
        self.mock = mock
        self.local = local or mock  # Mock implies local execution
        self.user = config.network.default_user
        self.domain_id = config.network.domain_id
        self.rmw = config.network.rmw
        self.remote_ws = config.network.remote_ws
        self.local_procs: List[subprocess.Popen] = []
        self._stopped = False

    def run_remote_ssh(self, command: str, timeout: int = 5) -> subprocess.CompletedProcess:
        if not self.robot_ip:
            raise RuntimeError("Robot IP is not configured")
        cmd = [
            "ssh",
            "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=no",
            "-o", f"ConnectTimeout={min(timeout, 3)}",
            f"{self.user}@{self.robot_ip}",
            command,
        ]
        try:
            return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)
        except (subprocess.TimeoutExpired, OSError) as e:
            return subprocess.CompletedProcess(cmd, 255, stdout="", stderr=str(e))

    def is_remote_tmux_running(self) -> bool:
        if not self.robot_ip or self.local:
            return False
        res = self.run_remote_ssh(f"tmux has-session -t {TMUX_SESSION} 2>/dev/null", timeout=4)
        return res.returncode == 0

    def kill_remote_tmux(self) -> None:
        if not self.robot_ip or self.local:
            return
        self.run_remote_ssh(f"tmux kill-session -t {TMUX_SESSION} 2>/dev/null || true", timeout=5)

    def attach_remote(self) -> None:
        """Attach interactively to the Pi's tmux session."""
        if not self.robot_ip or self.local:
            print("[attach] Робот не подключен по сети (локальный или mock режим).")
            return
        cmd = ["ssh", "-t", f"{self.user}@{self.robot_ip}", f"tmux attach -t {TMUX_SESSION}"]
        subprocess.run(cmd)

    def logs_remote(self, lines: int = 50) -> None:
        """Print recent log output from the remote tmux session."""
        if not self.robot_ip or self.local:
            print("[logs] Логи Pi недоступны в локальном/mock режиме.")
            return
        cmd = f"tmux capture-pane -pt {TMUX_SESSION}:0.0 -S -{lines} 2>/dev/null || echo 'Сессия {TMUX_SESSION} не найдена на Pi.'"
        res = self.run_remote_ssh(cmd, timeout=5)
        print(res.stdout)

    def start_remote_launch(self, launch_cmd: str) -> None:
        """Start a ROS 2 launch inside a remote tmux session on the Raspberry Pi."""
        if not self.robot_ip:
            raise RuntimeError("Cannot start remote process without robot IP")

        dds_export = ""
        if self.rmw == "rmw_cyclonedds_cpp":
            local_ip = get_source_ip_for_target(self.robot_ip)
            if not local_ip:
                raise RuntimeError("Cannot determine local IP toward robot for CycloneDDS")
            route = self.run_remote_ssh(f"ip -4 route get {local_ip}", timeout=5)
            match = re.search(r"\bsrc (\d+\.\d+\.\d+\.\d+)", route.stdout)
            if route.returncode != 0 or not match:
                raise RuntimeError("Cannot determine robot IP toward laptop for CycloneDDS")
            robot_source_ip = match.group(1)
            xml = (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<CycloneDDS xmlns="https://cdds.io/config"><Domain id="any">'
                f'<General><Interfaces><NetworkInterface address="{robot_source_ip}"/>'
                '</Interfaces><AllowMulticast>true</AllowMulticast></General>'
                f'<Discovery><Peers><Peer address="{local_ip}"/></Peers></Discovery>'
                '</Domain></CycloneDDS>'
            )
            encoded = base64.b64encode(xml.encode()).decode()
            remote_file = "/tmp/cyclonedds_ijkbot_remote.xml"
            setup = self.run_remote_ssh(f"printf %s {encoded} | base64 -d > {remote_file}", timeout=5)
            if setup.returncode != 0:
                raise RuntimeError(f"Cannot configure robot CycloneDDS: {setup.stderr}")
            dds_export = f"export CYCLONEDDS_URI=file://{remote_file}; "

        # Kill any dangling ijk session first
        self.kill_remote_tmux()

        # Wrap in environment setup
        full_sh = (
            f"export ROS_DOMAIN_ID={self.domain_id}; "
            f"export RMW_IMPLEMENTATION={self.rmw}; "
            f"{dds_export}"
            f"source /opt/ros/jazzy/setup.bash 2>/dev/null || true; "
            f"source {self.remote_ws}/install/setup.bash 2>/dev/null || true; "
            f"{launch_cmd}"
        )
        escaped_cmd = full_sh.replace("'", "'\\''")
        start_cmd = f"tmux new-session -d -s {TMUX_SESSION} bash -c '{escaped_cmd}; read'"
        res = self.run_remote_ssh(start_cmd, timeout=10)
        if res.returncode != 0:
            raise RuntimeError(f"Failed to start tmux on Pi: {res.stderr}")

    def run_local_process(
        self,
        cmd: Union[List[str], str],
        interactive: bool = False,
        env_extra: Optional[Dict[str, str]] = None,
    ) -> subprocess.Popen:
        """Run a local ROS 2 command inside Pixi / sourced workspace."""
        wrapped_argv, _ = build_shell_command(cmd, repo_dir=REPO_DIR)
        env = build_base_environment(self.domain_id, self.rmw, self.robot_ip)
        if env_extra:
            env.update(env_extra)

        if interactive:
            p = subprocess.Popen(wrapped_argv, env=env, stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr)
        else:
            p = subprocess.Popen(wrapped_argv, env=env)
        self.local_procs.append(p)
        return p

    def start_bag_recording(self, bag_name: Optional[str] = None, topics: Optional[List[str]] = None) -> Optional[subprocess.Popen]:
        """Record a rosbag for experiments if requested."""
        if not topics:
            topics = [
                "/scan", "/scan_raw", "/odom", "/tf", "/tf_static",
                "/cmd_vel", "/cmd_vel_emergency", "/cmd_vel_sm", "/cmd_vel_joy", "/cmd_vel_nav",
                "/victim_status",
            ]
        bags_dir = REPO_DIR / "bags"
        bags_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        target_bag = bags_dir / (bag_name or f"ijk_{ts}")
        print(f"[record] Запись rosbag в: {target_bag}")
        cmd = ["ros2", "bag", "record", "-o", str(target_bag)] + topics
        return self.run_local_process(cmd)

    def emergency_stop(self) -> None:
        """Send zero velocity to /cmd_vel_emergency and /cmd_vel and kill all stacks."""
        if self._stopped:
            return
        self._stopped = True

        print("[stop] Отправка экстренной нулевой скорости...")
        stop_cmd = [
            "ros2", "topic", "pub", "--once", "-w", "0",
            "/cmd_vel_emergency", "geometry_msgs/msg/Twist",
            "{linear: {x: 0.0, y: 0.0, z: 0.0}, angular: {x: 0.0, y: 0.0, z: 0.0}}",
        ]
        wrapped_stop, _ = build_shell_command(stop_cmd, repo_dir=REPO_DIR)
        env = build_base_environment(self.domain_id, self.rmw, self.robot_ip)
        try:
            subprocess.run(wrapped_stop, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2.0)
        except Exception:
            pass

        # Stop local processes
        for p in self.local_procs:
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    p.kill()
        self.local_procs.clear()

        # Kill remote tmux on Pi
        if self.robot_ip and not self.local:
            print("[stop] Завершение удалённых процессов на Raspberry Pi...")
            self.kill_remote_tmux()
            self.run_remote_ssh("pkill -9 -f diff_drive_node || true; pkill -9 -f ros2 || true", timeout=4)
        print("[stop] Все системы остановлены.")

    def wait_with_ctrl_c(self) -> None:
        """Wait for local processes and handle graceful shutdown on Ctrl+C."""
        def sig_handler(sig, frame):
            print("\n[runner] Получен сигнал остановки (Ctrl+C). Остановка...")
            self.emergency_stop()
            sys.exit(0)

        prev_int = signal.signal(signal.SIGINT, sig_handler)
        prev_term = signal.signal(signal.SIGTERM, sig_handler)

        try:
            while True:
                time.sleep(0.5)
                # If all local processes exited, we are done
                if self.local_procs and all(p.poll() is not None for p in self.local_procs):
                    break
        except KeyboardInterrupt:
            sig_handler(signal.SIGINT, None)
        finally:
            self.emergency_stop()
            signal.signal(signal.SIGINT, prev_int)
            signal.signal(signal.SIGTERM, prev_term)
