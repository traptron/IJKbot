"""Environment and ROS 2 execution helpers for IJKbot.

Handles Pixi environment detection, CycloneDDS unicast XML generation,
and sourcing of workspace install/setup.bash.
"""

from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union
import os
import shutil
import subprocess
import tempfile

REPO_DIR = Path(__file__).resolve().parents[2]
DEFAULT_PIXI_MANIFEST = Path("/home/lev/ros2_jazzy/pixi.toml")


def find_pixi() -> Optional[str]:
    """Find pixi binary in PATH or common user directories."""
    which_pixi = shutil.which("pixi")
    if which_pixi:
        return which_pixi
    candidates = [
        Path.home() / ".pixi" / "bin" / "pixi",
        Path("/home/lev/.pixi/bin/pixi"),
        Path("/usr/local/bin/pixi"),
    ]
    for c in candidates:
        if c.is_file() and os.access(c, os.X_OK):
            return str(c)
    return None


def get_pixi_manifest() -> Optional[str]:
    """Locate pixi.toml with ROS 2 Jazzy environment."""
    env_manifest = os.environ.get("PIXI_PROJECT_MANIFEST")
    if env_manifest and Path(env_manifest).is_file():
        return env_manifest
    if DEFAULT_PIXI_MANIFEST.is_file():
        return str(DEFAULT_PIXI_MANIFEST)
    return None


def get_source_ip_for_target(target_ip: str) -> Optional[str]:
    """Determine local network interface IP that routes to target_ip."""
    try:
        proc = subprocess.run(
            ["ip", "route", "get", target_ip],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=1.0,
        )
        if proc.returncode == 0:
            parts = proc.stdout.split()
            for i, part in enumerate(parts):
                if part == "src" and i + 1 < len(parts):
                    return parts[i + 1]
    except Exception:
        pass
    return None


def configure_cyclonedds(robot_ip: Optional[str]) -> Optional[str]:
    """Generate CycloneDDS XML configuration with local interface and robot unicast peer."""
    if not robot_ip:
        return None
    src_ip = get_source_ip_for_target(robot_ip)
    if not src_ip:
        return None
    xml_path = str(Path(tempfile.gettempdir()) / f"cyclonedds_ijkbot_{os.getuid()}_{robot_ip.replace('.', '_')}.xml")
    src_element = f'<Interfaces><NetworkInterface address="{src_ip}"/></Interfaces>'
    xml_content = f"""<?xml version="1.0" encoding="UTF-8" ?>
<CycloneDDS xmlns="https://cdds.io/config">
    <Domain id="any">
        <General>
            {src_element}
            <AllowMulticast>true</AllowMulticast>
        </General>
        <Discovery>
            <Peers>
                <Peer address="{robot_ip}"/>
            </Peers>
        </Discovery>
    </Domain>
</CycloneDDS>
"""
    try:
        Path(xml_path).write_text(xml_content, encoding="utf-8")
        return f"file://{xml_path}"
    except OSError:
        return None


def build_base_environment(domain_id: int = 42, rmw: str = "rmw_cyclonedds_cpp", robot_ip: Optional[str] = None) -> Dict[str, str]:
    """Prepare environment variables for ROS 2 commands on laptop."""
    env = os.environ.copy()
    env["ROS_DOMAIN_ID"] = str(domain_id)
    env["RMW_IMPLEMENTATION"] = rmw
    env["RCUTILS_LOGGING_BUFFERED_STREAM"] = "1"

    # CycloneDDS unicast peering
    dds_uri = configure_cyclonedds(robot_ip)
    if dds_uri:
        env["CYCLONEDDS_URI"] = dds_uri

    # Clean snap / incompatible GUI variables that can break RViz2 / Qt plugins
    for var in [
        "GTK_PATH",
        "GIO_MODULE_DIR",
        "GTK_EXE_PREFIX",
        "GTK_DATA_PREFIX",
        "QT_PLUGIN_PATH",
        "QT_QPA_PLATFORM_PLUGIN_PATH",
    ]:
        env.pop(var, None)

    pixi_bin = find_pixi()
    if pixi_bin:
        pixi_dir = str(Path(pixi_bin).parent)
        if pixi_dir not in env.get("PATH", ""):
            env["PATH"] = f"{pixi_dir}:{env.get('PATH', '')}"

    manifest = get_pixi_manifest()
    if manifest:
        env["PIXI_PROJECT_MANIFEST"] = manifest

    return env


def build_shell_command(cmd: Union[List[str], str], repo_dir: Path = REPO_DIR) -> Tuple[List[str], bool]:
    """
    Wrap command to execute inside Pixi (or native ROS 2) with workspace sourced.
    Returns: (argv_list, uses_pixi_run)
    """
    if isinstance(cmd, list):
        cmd_str = " ".join(f"'{arg}'" if (" " in arg or ";" in arg or ":=" in arg or "{" in arg) else arg for arg in cmd)
    else:
        cmd_str = cmd

    setup_bash = repo_dir / "install" / "setup.bash"
    source_workspace = f"set +u && [ -f '{setup_bash}' ] && source '{setup_bash}'; set -u;"

    pixi_bin = find_pixi()
    manifest = get_pixi_manifest()

    if pixi_bin and manifest:
        full_sh = f"{source_workspace} {cmd_str}"
        return [pixi_bin, "run", "-m", manifest, "bash", "-c", full_sh], True
    elif Path("/opt/ros/jazzy/setup.bash").exists():
        full_sh = f"set +u && source /opt/ros/jazzy/setup.bash && {source_workspace} set -u; {cmd_str}"
        return ["bash", "-c", full_sh], False
    else:
        full_sh = f"{source_workspace} {cmd_str}"
        return ["bash", "-c", full_sh], False

