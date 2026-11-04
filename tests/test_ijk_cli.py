"""Unit and integration tests for the unified ijk CLI and discovery."""

from pathlib import Path
import os
import subprocess
import sys
import pytest

REPO_DIR = Path(__file__).resolve().parents[1]
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

from tools.ijk.config import load_config
from tools.ijk.discovery import is_port_open, resolve_mdns
from tools.ijk.env import build_base_environment, build_shell_command, find_pixi, get_pixi_manifest
from tools.ijk.role import resolve_role
from tools.ijk.runner import Runner


def test_ijk_symlink_executable():
    ijk_bin = REPO_DIR / "ijk"
    assert ijk_bin.exists(), "ijk symlink does not exist"
    assert os.access(ijk_bin, os.X_OK), "ijk is not executable"


def test_ijk_help_command():
    proc = subprocess.run([str(REPO_DIR / "ijk"), "--help"], stdout=subprocess.PIPE, text=True, timeout=5)
    assert proc.returncode == 0
    assert "competition" in proc.stdout
    assert "showcase" in proc.stdout
    assert "teleop" in proc.stdout
    assert "mapping" in proc.stdout
    assert "navigate" in proc.stdout
    assert "bench" in proc.stdout
    assert "doctor" in proc.stdout
    assert "attach" in proc.stdout
    assert "logs" in proc.stdout
    assert "stop" in proc.stdout


def test_config_loader():
    cfg = load_config()
    assert cfg.network.domain_id == 42
    assert "competition" in cfg.profiles
    assert "showcase" in cfg.profiles
    assert "teleop" in cfg.profiles
    assert "mapping" in cfg.profiles
    assert "navigate" in cfg.profiles
    assert cfg.profiles["competition"].max_linear_velocity <= 0.25


def test_env_pixi_detection():
    pixi = find_pixi()
    assert pixi is not None
    manifest = get_pixi_manifest()
    assert manifest is not None
    cmd, is_pixi = build_shell_command("echo test")
    assert is_pixi is True


def test_runner_stop_mock(monkeypatch):
    cfg = load_config()
    runner = Runner(cfg, mock=True)
    monkeypatch.setattr("tools.ijk.runner.subprocess.run", lambda *args, **kwargs: None)
    # Should complete without throwing exceptions
    runner.emergency_stop()


def test_bench_subsystems_help():
    proc = subprocess.run([str(REPO_DIR / "ijk"), "bench", "--help"], stdout=subprocess.PIPE, text=True, timeout=5)
    assert proc.returncode == 0
    assert "motors" in proc.stdout
    assert "odom-calib" in proc.stdout
    assert "lidar" in proc.stdout
    assert "camera" in proc.stdout
    assert "driver" in proc.stdout
    assert "qr" in proc.stdout


def test_ops_subcommands_help():
    proc = subprocess.run([str(REPO_DIR / "ijk"), "ops", "--help"], stdout=subprocess.PIPE, text=True, timeout=5)
    assert proc.returncode == 0
    assert "timesync" in proc.stdout
    assert "wifi" in proc.stdout
    assert "bag-export" in proc.stdout
    assert "update" in proc.stdout
    assert "chrony" in proc.stdout


def test_save_odom_calibration(tmp_path, monkeypatch):
    from tools.ijk.config import save_odom_calibration, load_config
    monkeypatch.setattr("tools.ijk.config.LOCAL_CONFIG_FILE", tmp_path / "ijk.local.yaml")
    # Test saving and reading back in an isolated temporary configuration
    save_file = save_odom_calibration(0.0762, 0.2268)
    assert save_file.exists()
    cfg = load_config()
    assert abs(cfg.hardware.wheel_diameter - 0.0762) < 1e-4
    assert abs(cfg.hardware.wheel_separation - 0.2268) < 1e-4


def test_navigate_help():
    proc = subprocess.run([str(REPO_DIR / "ijk"), "navigate", "--help"], stdout=subprocess.PIPE, text=True, timeout=5)
    assert proc.returncode == 0
    assert "--map" in proc.stdout
    assert "--use-amcl" in proc.stdout


def test_mapping_help():
    proc = subprocess.run([str(REPO_DIR / "ijk"), "mapping", "--help"], stdout=subprocess.PIPE, text=True, timeout=5)
    assert proc.returncode == 0
    assert "--teleop" in proc.stdout
    assert "--save-map" in proc.stdout


def test_unreachable_robot_clean_exit():
    # 1. Unreachable explicit host
    proc1 = subprocess.run(
        [str(REPO_DIR / "ijk"), "--host", "192.0.2.1", "--no-discovery", "competition"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=10,
    )
    assert proc1.returncode != 0
    assert "не отвечает по SSH" in proc1.stdout

    # 2. No robot found on network without --host
    proc2 = subprocess.run(
        [str(REPO_DIR / "ijk"), "--no-discovery", "competition"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=10,
    )
    assert proc2.returncode != 0
    assert "Робот не обнаружен" in proc2.stdout


def test_role_resolution():
    assert resolve_role("all") == "all"
    assert resolve_role("operator") == "operator"
    assert resolve_role("ai") == "ai"
    assert resolve_role("auto", mock=True) == "all"

@pytest.mark.parametrize(('command', 'function'), [
    ('competition', 'run_competition'), ('showcase', 'run_showcase'),
    ('teleop', 'run_teleop'), ('mapping', 'run_mapping'),
    ('navigate', 'run_navigate'), ('doctor', 'run_doctor'),
])
def test_cli_dispatch_without_hardware(monkeypatch, command, function):
    from tools.ijk import cli
    calls = []
    monkeypatch.setattr(cli, function, lambda *args, **kwargs: calls.append((args, kwargs)))
    assert cli.main(['--mock', '--no-discovery', command]) == 0
    assert len(calls) == 1


def test_cyclonedds_config_uses_route_address(tmp_path, monkeypatch):
    from tools.ijk import env
    monkeypatch.setattr(env, 'get_source_ip_for_target', lambda ip: '192.168.0.187')
    monkeypatch.setattr(env.tempfile, 'gettempdir', lambda: str(tmp_path))
    uri = env.configure_cyclonedds('192.168.0.191')
    xml = Path(uri.removeprefix('file://')).read_text()
    assert 'address="192.168.0.187"' in xml
    assert '<Peer address="192.168.0.191"/>' in xml


def test_remote_launch_configures_cyclonedds_without_hardware(monkeypatch):
    from tools.ijk import runner as runner_module
    from subprocess import CompletedProcess
    import base64
    cfg = load_config()
    runner = Runner(cfg, robot_ip='192.168.0.191')
    monkeypatch.setattr(runner_module, 'get_source_ip_for_target', lambda ip: '192.168.0.187')
    commands = []
    def fake_ssh(command, timeout=5):
        commands.append(command)
        if command.startswith('ip -4 route get'):
            return CompletedProcess(command, 0, '192.168.0.187 dev wlan0 src 192.168.0.191', '')
        return CompletedProcess(command, 0, '', '')
    monkeypatch.setattr(runner, 'run_remote_ssh', fake_ssh)
    runner.start_remote_launch('ros2 launch bringup robot.launch.py')
    encoded = commands[1].split('printf %s ', 1)[1].split(' |', 1)[0]
    remote_xml = base64.b64decode(encoded).decode()
    assert 'address="192.168.0.191"' in remote_xml
    assert '<Peer address="192.168.0.187"/>' in remote_xml
    assert 'CYCLONEDDS_URI=file:///tmp/cyclonedds_ijkbot_remote.xml' in commands[-1]


@pytest.mark.parametrize('profile', ['mapping', 'navigate', 'showcase', 'competition'])
def test_no_rviz_cli_flag_preserves_other_options(monkeypatch, profile):
    from tools.ijk import cli
    calls = []
    monkeypatch.setattr(cli, 'run_' + profile, lambda *args, **kwargs: calls.append(kwargs))
    assert cli.main(['--mock', '--no-discovery', '--record', '--bag-name', 'trial', profile, '--no-rviz']) == 0
    assert calls[0]['rviz'] is False
    assert calls[0]['record'] is True
    assert calls[0]['bag_name'] == 'trial'


def test_navigation_sync_refreshes_referenced_image_and_aborts_on_error(tmp_path, monkeypatch):
    from tools.ijk.profiles import navigate
    from types import SimpleNamespace
    import yaml
    image = tmp_path / 'different_image.pgm'
    image.write_bytes(b'P5\n1 1\n255\n\xff')
    path = tmp_path / 'room.yaml'
    path.write_text(yaml.safe_dump({'image':str(image), 'resolution':.05,'origin':[0,0,0]}))
    runner = SimpleNamespace(robot_ip='192.0.2.2',local=False,remote_ws='/robot',user='robot',
        run_remote_ssh=lambda *args: subprocess.CompletedProcess(args,0,'',''))
    copies = []
    def copy(command, **kwargs):
        data = yaml.safe_load(Path(command[-2]).read_text())
        copies.append((command,data))
        return subprocess.CompletedProcess(command,0,'','')
    monkeypatch.setattr(navigate.subprocess,'run',copy)
    navigate.sync_map_to_pi(runner,path)
    navigate.sync_map_to_pi(runner,path)
    assert len(copies) == 2
    assert str(image) in copies[0][0]
    assert copies[0][1]['image'] == 'different_image.pgm'
    monkeypatch.setattr(navigate.subprocess,'run',lambda *args,**kwargs:subprocess.CompletedProcess(args,1,'','copy failed'))
    with pytest.raises(RuntimeError, match='copy failed'):
        navigate.sync_map_to_pi(runner,path)


def test_recording_does_not_skip_mock_teleop_hardware(monkeypatch):
    from tools.ijk.profiles.teleop import run_teleop
    from types import SimpleNamespace
    launches = []
    runner = SimpleNamespace(local=True, local_procs=[], domain_id=133,
        start_bag_recording=lambda **kwargs: runner.local_procs.append('bag'),
        run_local_process=lambda cmd: launches.append(cmd),wait_with_ctrl_c=lambda:None)
    run_teleop(runner,load_config(),web_mode=True,mock=True,record=True)
    assert any('robot.launch.py' in command for command in launches)
