#!/usr/bin/env python3
"""
test_operator_scripts.py — Unit & Integration tests for Laptop 2 operator scripts.
"""

import os
import subprocess
import sys
import yaml
import pytest

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.join(REPO_DIR, 'scripts')

SCRIPTS = [
    'start_all_laptop2.sh',
    'start_robot_pi.sh',
    'start_nav2_pi.sh',
    'start_rviz.sh',
    'stop_all.sh',
    'teleop.sh',
    'setup_chrony.sh',
]


def test_scripts_exist_and_executable():
    """Verify that all operator scripts exist and are executable."""
    for script_name in SCRIPTS:
        script_path = os.path.join(SCRIPTS_DIR, script_name)
        assert os.path.isfile(script_path), f"Script {script_name} does not exist"
        assert os.access(script_path, os.X_OK), f"Script {script_name} is not executable"


@pytest.mark.parametrize("script_name", SCRIPTS)
def test_script_syntax_with_bash_n(script_name):
    """Verify bash syntax with bash -n."""
    script_path = os.path.join(SCRIPTS_DIR, script_name)
    proc = subprocess.run(['bash', '-n', script_path], capture_output=True, text=True)
    assert proc.returncode == 0, f"Syntax error in {script_name}: {proc.stderr}"


@pytest.mark.parametrize("script_name", [
    'start_all_laptop2.sh',
    'start_robot_pi.sh',
    'start_nav2_pi.sh',
    'start_rviz.sh',
    'stop_all.sh',
    'teleop.sh',
])
def test_script_help_flag(script_name):
    """Verify that every script supports -h/--help and prints useful instructions."""
    script_path = os.path.join(SCRIPTS_DIR, script_name)
    proc = subprocess.run([script_path, '--help'], capture_output=True, text=True, timeout=5)
    assert proc.returncode == 0, f"{script_name} --help failed with code {proc.returncode}"
    output = proc.stdout + proc.stderr
    assert "ROS_DOMAIN_ID" in output or "Использование" in output or "Usage" in output


def test_rviz_default_view_config():
    """Verify that nav2_default_view.rviz exists and has all required displays."""
    rviz_file = os.path.join(REPO_DIR, 'ijkbot_nav2', 'rviz', 'nav2_default_view.rviz')
    assert os.path.isfile(rviz_file), "nav2_default_view.rviz not found"

    with open(rviz_file, 'r') as f:
        data = yaml.safe_load(f)

    assert 'Visualization Manager' in data
    displays = data['Visualization Manager'].get('Displays', [])
    display_names = [d.get('Name') for d in displays if isinstance(d, dict)]

    # Check required displays per specification
    assert any('RobotModel' in name for name in display_names if name)
    assert any('TF' in name for name in display_names if name)
    assert any('LaserScan' in name for name in display_names if name)
    assert any('Global Costmap' in name for name in display_names if name)
    assert any('Local Costmap' in name for name in display_names if name)
    assert any('Footprint' in name for name in display_names if name)
    assert any('Global Plan' in name for name in display_names if name)
    assert any('Local Plan' in name for name in display_names if name)
    assert any('QR' in name for name in display_names if name)


def test_stop_all_offline():
    """Verify stop_all.sh handles unreachable host gracefully without hanging."""
    script_path = os.path.join(SCRIPTS_DIR, 'stop_all.sh')
    proc = subprocess.run(
        [script_path, '--host', '192.0.2.1', '--no-vel'],
        capture_output=True,
        text=True,
        timeout=10
    )
    assert proc.returncode == 0
    assert "ВСЕ СИСТЕМЫ УСПЕШНО ОСТАНОВЛЕНЫ" in proc.stdout


def test_start_robot_pi_unreachable_host_fails():
    """Verify start_robot_pi.sh aborts with non-zero code if robot is not reachable."""
    script_path = os.path.join(SCRIPTS_DIR, 'start_robot_pi.sh')
    proc = subprocess.run(
        [script_path, '--host', '192.0.2.1'],
        capture_output=True,
        text=True,
        timeout=15
    )
    assert proc.returncode != 0
    assert "не отвечает" in proc.stdout or "не отвечает" in proc.stderr or "timed out" in proc.stderr


def test_start_nav2_pi_unreachable_host_fails():
    """Verify start_nav2_pi.sh aborts with non-zero code if robot is not reachable."""
    script_path = os.path.join(SCRIPTS_DIR, 'start_nav2_pi.sh')
    proc = subprocess.run(
        [script_path, '--host', '192.0.2.1'],
        capture_output=True,
        text=True,
        timeout=15
    )
    assert proc.returncode != 0
    assert "не отвечает" in proc.stdout or "не отвечает" in proc.stderr or "timed out" in proc.stderr


def test_teleop_unknown_arg():
    """Verify teleop.sh rejects unknown arguments with code 1."""
    script_path = os.path.join(SCRIPTS_DIR, 'teleop.sh')
    proc = subprocess.run(
        [script_path, '--unknown-flag'],
        capture_output=True,
        text=True,
        timeout=5
    )
    assert proc.returncode == 1
    assert "Неизвестный аргумент" in proc.stderr or "Неизвестный аргумент" in proc.stdout


def test_teleop_speed_limit_clamp():
    """Verify teleop.sh warns and clamps speed > 0.25 m/s to 0.25 m/s."""
    script_path = os.path.join(SCRIPTS_DIR, 'teleop.sh')
    try:
        proc = subprocess.run(
            [script_path, '--speed', '0.5'],
            capture_output=True,
            text=True,
            timeout=1
        )
        output = proc.stdout + proc.stderr
    except subprocess.TimeoutExpired as e:
        output = (e.stdout or b'').decode('utf-8', errors='ignore') + (e.stderr or b'').decode('utf-8', errors='ignore')

    assert "превышает регламентный лимит" in output
    assert "0.25" in output


def test_start_all_laptop2_unreachable_host_fails():
    """Verify start_all_laptop2.sh cleanly fails when host is unreachable."""
    script_path = os.path.join(SCRIPTS_DIR, 'start_all_laptop2.sh')
    proc = subprocess.run(
        [script_path, '--host', '192.0.2.1', '--no-rviz'],
        capture_output=True,
        text=True,
        timeout=15
    )
    assert proc.returncode != 0
    output = proc.stdout + proc.stderr
    assert "Не удалось связаться с Raspberry Pi" in output or "не отвечает" in output


def test_start_all_laptop2_help_new_options():
    """Verify start_all_laptop2.sh lists all new supported options."""
    script_path = os.path.join(SCRIPTS_DIR, 'start_all_laptop2.sh')
    proc = subprocess.run([script_path, '--help'], capture_output=True, text=True, timeout=5)
    assert proc.returncode == 0
    output = proc.stdout + proc.stderr
    assert "--use-amcl" in output
    assert "--map" in output
    assert "--local" in output
    assert "--force" in output
    assert "--no-camera" in output


def test_start_nav2_pi_help_new_options():
    """Verify start_nav2_pi.sh lists --map and --local."""
    script_path = os.path.join(SCRIPTS_DIR, 'start_nav2_pi.sh')
    proc = subprocess.run([script_path, '--help'], capture_output=True, text=True, timeout=5)
    assert proc.returncode == 0
    output = proc.stdout + proc.stderr
    assert "--map" in output
    assert "--local" in output


def test_start_robot_pi_help_new_options():
    """Verify start_robot_pi.sh lists --local."""
    script_path = os.path.join(SCRIPTS_DIR, 'start_robot_pi.sh')
    proc = subprocess.run([script_path, '--help'], capture_output=True, text=True, timeout=5)
    assert proc.returncode == 0
    output = proc.stdout + proc.stderr
    assert "--local" in output


def test_stop_all_caller_pid_arg():
    """Verify stop_all.sh accepts --caller-pid and does not error."""
    script_path = os.path.join(SCRIPTS_DIR, 'stop_all.sh')
    proc = subprocess.run(
        [script_path, '--host', '192.0.2.1', '--no-vel', '--caller-pid', str(os.getpid())],
        capture_output=True,
        text=True,
        timeout=10
    )
    assert proc.returncode == 0
    assert "ВСЕ СИСТЕМЫ УСПЕШНО ОСТАНОВЛЕНЫ" in proc.stdout


def test_check_clock_sync_reads_pi_host_env():
    """Verify check_clock_sync.py prioritizes PI_HOST and PI_USER env vars."""
    script_path = os.path.join(SCRIPTS_DIR, 'check_clock_sync.py')
    env = os.environ.copy()
    env['PI_HOST'] = '10.20.30.40'
    env['PI_USER'] = 'custom_user'
    proc = subprocess.run(
        [sys.executable, script_path, '--mock'],
        capture_output=True,
        text=True,
        timeout=5,
        env=env
    )
    assert proc.returncode == 0
    assert "custom_user" in proc.stdout


def test_documentation_files():
    """Verify README.md and OPERATOR_GUIDE.md exist and contain essential guidance."""
    readme_path = os.path.join(SCRIPTS_DIR, 'README.md')
    assert os.path.isfile(readme_path)
    assert os.path.getsize(readme_path) > 1000

    guide_path = os.path.join(REPO_DIR, 'OPERATOR_GUIDE.md')
    assert os.path.exists(guide_path)

    with open(readme_path, 'r', encoding='utf-8') as f:
        content = f.read()

    assert "start_all_laptop2.sh" in content
    assert "stop_all.sh" in content
    assert "teleop.sh" in content
    assert "start_robot_pi.sh" in content
    assert "start_nav2_pi.sh" in content
    assert "start_rviz.sh" in content
    assert "ROS_DOMAIN_ID=42" in content
    assert "192.168.1.10" in content

