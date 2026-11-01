"""IJKbot unified configuration loader."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
import os
import yaml


REPO_DIR = Path(__file__).resolve().parents[2]
CONFIG_FILE = REPO_DIR / "config" / "ijk.yaml"
LOCAL_CONFIG_FILE = REPO_DIR / "config" / "ijk.local.yaml"
CACHE_DIR = Path.home() / ".cache" / "ijk"
LAST_IP_FILE = CACHE_DIR / "last_ip"


@dataclass
class NetworkConfig:
    default_user: str = "otmorozki"
    ssh_port: int = 22
    domain_id: int = 42
    rmw: str = "rmw_cyclonedds_cpp"
    known_hosts: List[str] = field(default_factory=lambda: ["192.168.0.191", "10.197.37.154", "192.168.1.10"])
    mdns_hostname: str = "ijkbot.local"
    subnet_scan_timeout_sec: float = 2.0
    remote_ws: str = "/home/otmorozki/IJKbot"


@dataclass
class HardwareConfig:
    lidar_port: str = "/dev/ttyUSB0"
    lidar_baudrate: int = 115200
    motors_port: str = "/dev/ttySTS"
    camera_type: str = "csi"
    wheel_diameter: float = 0.075
    wheel_separation: float = 0.225


@dataclass
class ProfileConfig:
    name: str
    description: str = ""
    max_linear_velocity: float = 0.25
    max_angular_velocity: float = 2.0
    enable_brain: bool = False
    enable_vision: bool = False
    enable_nav: bool = False
    enable_robot: bool = True
    enable_lidar: bool = True
    use_amcl: bool = False
    map: str = "polygon_empty_4x4.yaml"
    teleop_source: str = "keyboard"
    allow_speed_override: bool = False


@dataclass
class IjkConfig:
    network: NetworkConfig = field(default_factory=NetworkConfig)
    hardware: HardwareConfig = field(default_factory=HardwareConfig)
    profiles: Dict[str, ProfileConfig] = field(default_factory=dict)
    raw: Dict[str, Any] = field(default_factory=dict)


def deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def load_config() -> IjkConfig:
    data: Dict[str, Any] = {}
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

    if LOCAL_CONFIG_FILE.exists():
        with open(LOCAL_CONFIG_FILE, "r", encoding="utf-8") as f:
            local_data = yaml.safe_load(f) or {}
            data = deep_merge(data, local_data)

    net_data = data.get("network", {})
    network = NetworkConfig(
        default_user=os.environ.get("ROBOT_USER", net_data.get("default_user", "otmorozki")),
        ssh_port=int(net_data.get("ssh_port", 22)),
        domain_id=int(os.environ.get("ROS_DOMAIN_ID", net_data.get("domain_id", 42))),
        rmw=os.environ.get("RMW_IMPLEMENTATION", net_data.get("rmw", "rmw_cyclonedds_cpp")),
        known_hosts=list(net_data.get("known_hosts", ["192.168.0.191", "10.197.37.154", "192.168.1.10"])),
        mdns_hostname=str(net_data.get("mdns_hostname", "ijkbot.local")),
        subnet_scan_timeout_sec=float(net_data.get("subnet_scan_timeout_sec", 2.0)),
        remote_ws=str(net_data.get("remote_ws", "/home/otmorozki/IJKbot")),
    )

    hw_data = data.get("hardware", {})
    lidar_data = hw_data.get("lidar", {})
    motors_data = hw_data.get("motors", {})
    camera_data = hw_data.get("camera", {})
    hardware = HardwareConfig(
        lidar_port=str(lidar_data.get("port", "/dev/ttyUSB0")),
        lidar_baudrate=int(lidar_data.get("baudrate", 115200)),
        motors_port=str(motors_data.get("port", "/dev/ttySTS")),
        camera_type=str(camera_data.get("type", "csi")),
        wheel_diameter=float(motors_data.get("wheel_diameter", 0.075)),
        wheel_separation=float(motors_data.get("wheel_separation", 0.225)),
    )

    profiles: Dict[str, ProfileConfig] = {}
    prof_data = data.get("profiles", {})
    for name, p in prof_data.items():
        profiles[name] = ProfileConfig(
            name=name,
            description=str(p.get("description", "")),
            max_linear_velocity=float(p.get("max_linear_velocity", 0.25)),
            max_angular_velocity=float(p.get("max_angular_velocity", 2.0)),
            enable_brain=bool(p.get("enable_brain", False)),
            enable_vision=bool(p.get("enable_vision", False)),
            enable_nav=bool(p.get("enable_nav", False)),
            enable_robot=bool(p.get("enable_robot", True)),
            enable_lidar=bool(p.get("enable_lidar", True)),
            use_amcl=bool(p.get("use_amcl", False)),
            map=str(p.get("map", "polygon_empty_4x4.yaml")),
            teleop_source=str(p.get("teleop_source", "keyboard")),
            allow_speed_override=bool(p.get("allow_speed_override", False)),
        )

    return IjkConfig(network=network, hardware=hardware, profiles=profiles, raw=data)


def save_last_ip(ip: str) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        LAST_IP_FILE.write_text(ip.strip(), encoding="utf-8")
    except OSError:
        pass


def get_cached_ip() -> Optional[str]:
    if LAST_IP_FILE.exists():
        try:
            ip = LAST_IP_FILE.read_text(encoding="utf-8").strip()
            if ip:
                return ip
        except OSError:
            pass
    return None


def save_odom_calibration(wheel_diameter: float, wheel_separation: float) -> Path:
    """Save calibrated wheel parameters to config/ijk.local.yaml."""
    local_data: Dict[str, Any] = {}
    if LOCAL_CONFIG_FILE.exists():
        try:
            with open(LOCAL_CONFIG_FILE, "r", encoding="utf-8") as f:
                local_data = yaml.safe_load(f) or {}
        except Exception:
            local_data = {}

    if "hardware" not in local_data:
        local_data["hardware"] = {}
    if "motors" not in local_data["hardware"]:
        local_data["hardware"]["motors"] = {}

    local_data["hardware"]["motors"]["wheel_diameter"] = round(float(wheel_diameter), 6)
    local_data["hardware"]["motors"]["wheel_separation"] = round(float(wheel_separation), 6)

    LOCAL_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOCAL_CONFIG_FILE, "w", encoding="utf-8") as f:
        yaml.dump(local_data, f, default_flow_style=False, sort_keys=False)

    return LOCAL_CONFIG_FILE

