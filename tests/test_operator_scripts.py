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
    'start_all_laptop1.sh',
    'start_all_laptop2.sh',
    'start_robot_pi.sh',
    'start_nav2_pi.sh',
    'start_rviz.sh',
    'stop_all.sh',
    'teleop.sh',
    'setup_chrony.sh',
    'update_pi.sh',
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
    'start_all_laptop1.sh',
    'start_all_laptop2.sh',
    'start_robot_pi.sh',
    'start_nav2_pi.sh',
    'start_rviz.sh',
    'stop_all.sh',
    'teleop.sh',
    'update_pi.sh',
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
    rviz_file = os.path.join(REPO_DIR, 'src', 'nav2', 'rviz', 'nav2_default_view.rviz')
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


def test_update_pi_help_options():
    """Verify update_pi.sh lists all required arguments in help."""
    script_path = os.path.join(SCRIPTS_DIR, 'update_pi.sh')
    proc = subprocess.run([script_path, '--help'], capture_output=True, text=True, timeout=5)
    assert proc.returncode == 0
    output = proc.stdout + proc.stderr
    assert "--host" in output
    assert "--user" in output
    assert "--branch" in output
    assert "--no-build" in output
    assert "--clean" in output
    assert "--local" in output


def test_update_pi_unreachable_host_fails():
    """Verify update_pi.sh fails when host is unreachable."""
    script_path = os.path.join(SCRIPTS_DIR, 'update_pi.sh')
    proc = subprocess.run(
        [script_path, '--host', '192.0.2.1'],
        capture_output=True,
        text=True,
        timeout=15
    )
    assert proc.returncode != 0
    assert "не отвечает" in proc.stdout or "не отвечает" in proc.stderr or "timed out" in proc.stderr


def test_update_pi_unknown_arg():
    """Verify update_pi.sh rejects unknown arguments with code 1."""
    script_path = os.path.join(SCRIPTS_DIR, 'update_pi.sh')
    proc = subprocess.run(
        [script_path, '--invalid-argument'],
        capture_output=True,
        text=True,
        timeout=5
    )
    assert proc.returncode == 1
    assert "Неизвестный аргумент" in proc.stderr or "Неизвестный аргумент" in proc.stdout


def test_update_pi_local_stash_and_no_build(tmp_path):
    """Verify update_pi.sh safely stashes local changes, updates repo, and skips build with --no-build."""
    repo_dir = tmp_path / "mock_robot_repo"
    repo_dir.mkdir()
    subprocess.run(['git', 'init', '-b', 'dev'], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(['git', 'config', 'user.name', 'Test User'], cwd=str(repo_dir), check=True)
    subprocess.run(['git', 'config', 'user.email', 'test@example.com'], cwd=str(repo_dir), check=True)

    test_file = repo_dir / "test.txt"
    test_file.write_text("initial commit\n")
    subprocess.run(['git', 'add', 'test.txt'], cwd=str(repo_dir), check=True)
    subprocess.run(['git', 'commit', '-m', 'initial commit'], cwd=str(repo_dir), check=True)

    test_file.write_text("dirty local change\n")

    script_path = os.path.join(SCRIPTS_DIR, 'update_pi.sh')
    proc = subprocess.run(
        [script_path, '--local', '--ws', str(repo_dir), '--branch', 'dev', '--no-build'],
        capture_output=True,
        text=True,
        timeout=15
    )
    assert proc.returncode == 0
    output = proc.stdout + proc.stderr
    assert "Обнаружены незакоммиченные локальные изменения" in output or "stash" in output
    assert "Сборка пакетов пропущена по флагу --no-build" in output
    assert "Обновление робота завершено успешно" in output
    assert test_file.read_text() == "dirty local change\n"


def test_update_pi_clean_flag(tmp_path):
    """Verify update_pi.sh removes build/ install/ log/ when --clean is specified."""
    repo_dir = tmp_path / "mock_clean_repo"
    repo_dir.mkdir()
    subprocess.run(['git', 'init', '-b', 'dev'], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(['git', 'config', 'user.name', 'Test User'], cwd=str(repo_dir), check=True)
    subprocess.run(['git', 'config', 'user.email', 'test@example.com'], cwd=str(repo_dir), check=True)

    test_file = repo_dir / "test.txt"
    test_file.write_text("v1\n")
    subprocess.run(['git', 'add', 'test.txt'], cwd=str(repo_dir), check=True)
    subprocess.run(['git', 'commit', '-m', 'v1'], cwd=str(repo_dir), check=True)

    build_dir = repo_dir / "build"
    install_dir = repo_dir / "install"
    log_dir = repo_dir / "log"
    build_dir.mkdir()
    install_dir.mkdir()
    log_dir.mkdir()
    (build_dir / "dummy.o").write_text("dummy")

    script_path = os.path.join(SCRIPTS_DIR, 'update_pi.sh')
    proc = subprocess.run(
        [script_path, '--local', '--ws', str(repo_dir), '--clean', '--no-build'],
        capture_output=True,
        text=True,
        timeout=15
    )
    assert proc.returncode == 0
    assert not build_dir.exists()
    assert not install_dir.exists()
    assert not log_dir.exists()


@pytest.mark.parametrize("script_and_flag", [
    ('start_all_laptop2.sh', '--host'),
    ('start_robot_pi.sh', '--host'),
    ('start_nav2_pi.sh', '--initial-x'),
    ('start_rviz.sh', '-d'),
    ('stop_all.sh', '--host'),
    ('teleop.sh', '--speed'),
    ('update_pi.sh', '--host'),
    ('update_pi.sh', '--user'),
    ('update_pi.sh', '--branch'),
    ('update_pi.sh', '--ws'),
    ('update_pi.sh', '--packages'),
])
def test_script_missing_argument_value_fails_cleanly(script_and_flag):
    """Verify that omitting a required option argument exits with code 1 instead of crashing."""
    script_name, flag = script_and_flag
    script_path = os.path.join(SCRIPTS_DIR, script_name)
    proc = subprocess.run([script_path, flag], capture_output=True, text=True, timeout=5)
    assert proc.returncode != 0
    output = proc.stdout + proc.stderr
    assert "требует" in output or "ERROR" in output or "Использование" in output


def test_teleop_negative_speed_clamped():
    """Verify teleop.sh clamps negative speed magnitude > 0.25 to 0.25 m/s."""
    script_path = os.path.join(SCRIPTS_DIR, 'teleop.sh')
    try:
        proc = subprocess.run(
            [script_path, '--speed', '-0.5'],
            capture_output=True,
            text=True,
            timeout=1
        )
        output = proc.stdout + proc.stderr
    except subprocess.TimeoutExpired as e:
        output = (e.stdout or b'').decode('utf-8', errors='ignore') + (e.stderr or b'').decode('utf-8', errors='ignore')

    assert "превышает регламентный лимит" in output
    assert "0.25" in output


def test_teleop_invalid_and_empty_speed_fallback():
    """Verify teleop.sh falls back to default 0.2 m/s when given empty or non-numeric speed."""
    script_path = os.path.join(SCRIPTS_DIR, 'teleop.sh')
    for bad_speed in ['', 'invalid_speed', '0.0']:
        try:
            proc = subprocess.run(
                [script_path, '--speed', bad_speed],
                capture_output=True,
                text=True,
                timeout=1
            )
            output = proc.stdout + proc.stderr
        except subprocess.TimeoutExpired as e:
            output = (e.stdout or b'').decode('utf-8', errors='ignore') + (e.stderr or b'').decode('utf-8', errors='ignore')

        assert "Сброс на дефолт: 0.2" in output or "0.2" in output


def test_stop_all_local_flag():
    """Verify stop_all.sh --local executes quickly without attempting SSH connection."""
    script_path = os.path.join(SCRIPTS_DIR, 'stop_all.sh')
    proc = subprocess.run(
        [script_path, '--local', '--no-vel'],
        capture_output=True,
        text=True,
        timeout=5
    )
    assert proc.returncode == 0
    assert "Локальный режим (--local)" in proc.stdout
    assert "ВСЕ СИСТЕМЫ УСПЕШНО ОСТАНОВЛЕНЫ" in proc.stdout


def test_start_robot_pi_invalid_hostname_fails():
    """Verify start_robot_pi.sh detects invalid hostname without hanging."""
    script_path = os.path.join(SCRIPTS_DIR, 'start_robot_pi.sh')
    proc = subprocess.run(
        [script_path, '--host', 'non_existent_robot_hostname_xyz'],
        capture_output=True,
        text=True,
        timeout=10
    )
    assert proc.returncode != 0
    output = proc.stdout + proc.stderr
    assert "не отвечает" in output or "FAIL" in output


def test_update_pi_remote_branch_fetch_and_checkout(tmp_path):
    """Verify update_pi.sh fetches remote branch from origin before checking out."""
    remote_dir = tmp_path / "remote_repo"
    remote_dir.mkdir()
    subprocess.run(['git', 'init', '--bare'], cwd=str(remote_dir), check=True, capture_output=True)

    dev_clone = tmp_path / "dev_clone"
    subprocess.run(['git', 'clone', str(remote_dir), str(dev_clone)], check=True, capture_output=True)
    subprocess.run(['git', 'checkout', '-b', 'dev'], cwd=str(dev_clone), check=True, capture_output=True)
    subprocess.run(['git', 'config', 'user.name', 'Test Dev'], cwd=str(dev_clone), check=True)
    subprocess.run(['git', 'config', 'user.email', 'dev@example.com'], cwd=str(dev_clone), check=True)
    (dev_clone / "base.txt").write_text("initial")
    subprocess.run(['git', 'add', '.'], cwd=str(dev_clone), check=True)
    subprocess.run(['git', 'commit', '-m', 'init dev'], cwd=str(dev_clone), check=True)
    subprocess.run(['git', 'push', 'origin', 'dev'], cwd=str(dev_clone), check=True)

    # Robot clones dev branch
    robot_clone = tmp_path / "robot_clone"
    subprocess.run(['git', 'clone', '--branch', 'dev', str(remote_dir), str(robot_clone)], check=True, capture_output=True)

    # Developer creates a new branch and pushes it to origin
    subprocess.run(['git', 'checkout', '-b', 'feature-target'], cwd=str(dev_clone), check=True, capture_output=True)
    (dev_clone / "feature.txt").write_text("feature content")
    subprocess.run(['git', 'add', '.'], cwd=str(dev_clone), check=True)
    subprocess.run(['git', 'commit', '-m', 'add feature'], cwd=str(dev_clone), check=True)
    subprocess.run(['git', 'push', 'origin', 'feature-target'], cwd=str(dev_clone), check=True)

    # Robot updates to the new branch
    script_path = os.path.join(SCRIPTS_DIR, 'update_pi.sh')
    proc = subprocess.run(
        [script_path, '--local', '--ws', str(robot_clone), '--branch', 'feature-target', '--no-build'],
        capture_output=True,
        text=True,
        timeout=15
    )
    assert proc.returncode == 0
    assert (robot_clone / "feature.txt").exists()
    assert (robot_clone / "feature.txt").read_text() == "feature content"


def test_update_pi_user_recomputes_remote_ws():
    """Verify update_pi.sh recomputes default REMOTE_WS when --user is specified without --ws."""
    script_path = os.path.join(SCRIPTS_DIR, 'update_pi.sh')
    proc = subprocess.run(
        [script_path, '--host', '192.0.2.1', '--user', 'custom_operator'],
        capture_output=True,
        text=True,
        timeout=5
    )
    output = proc.stdout + proc.stderr
    assert "custom_operator@192.0.2.1" in output
    assert "/home/custom_operator/IJKbot" in output


def test_update_pi_stash_conflict_fails_cleanly(tmp_path):
    """Verify update_pi.sh aborts with non-zero exit code when stash pop encounters a conflict."""
    remote_dir = tmp_path / "remote_stash_conflict"
    remote_dir.mkdir()
    subprocess.run(['git', 'init', '--bare'], cwd=str(remote_dir), check=True, capture_output=True)

    clone_a = tmp_path / "clone_a"
    subprocess.run(['git', 'clone', str(remote_dir), str(clone_a)], check=True, capture_output=True)
    subprocess.run(['git', 'checkout', '-b', 'dev'], cwd=str(clone_a), check=True, capture_output=True)
    subprocess.run(['git', 'config', 'user.name', 'Test A'], cwd=str(clone_a), check=True)
    subprocess.run(['git', 'config', 'user.email', 'a@example.com'], cwd=str(clone_a), check=True)
    (clone_a / "conflict.txt").write_text("line1\nline2\n")
    subprocess.run(['git', 'add', '.'], cwd=str(clone_a), check=True)
    subprocess.run(['git', 'commit', '-m', 'base'], cwd=str(clone_a), check=True)
    subprocess.run(['git', 'push', 'origin', 'dev'], cwd=str(clone_a), check=True)

    # Robot clone
    robot_clone = tmp_path / "robot_stash_repo"
    subprocess.run(['git', 'clone', '--branch', 'dev', str(remote_dir), str(robot_clone)], check=True, capture_output=True)

    # Upstream commit
    (clone_a / "conflict.txt").write_text("line1-upstream\nline2\n")
    subprocess.run(['git', 'add', '.'], cwd=str(clone_a), check=True)
    subprocess.run(['git', 'commit', '-m', 'upstream change'], cwd=str(clone_a), check=True)
    subprocess.run(['git', 'push', 'origin', 'dev'], cwd=str(clone_a), check=True)

    # Robot local uncommitted change on conflicting line
    (robot_clone / "conflict.txt").write_text("line1-robot-local\nline2\n")

    script_path = os.path.join(SCRIPTS_DIR, 'update_pi.sh')
    proc = subprocess.run(
        [script_path, '--local', '--ws', str(robot_clone), '--branch', 'dev', '--no-build'],
        capture_output=True,
        text=True,
        timeout=15
    )
    assert proc.returncode != 0
    output = proc.stdout + proc.stderr
    assert "Конфликт при восстановлении изменений из stash" in output


def test_start_all_laptop1_invalid_arg():
    """Verify start_all_laptop1.sh rejects unknown options."""
    script_path = os.path.join(SCRIPTS_DIR, 'start_all_laptop1.sh')
    proc = subprocess.run(
        [script_path, '--invalid-flag-test'],
        capture_output=True,
        text=True,
        timeout=5
    )
    assert proc.returncode != 0
    output = proc.stdout + proc.stderr
    assert "Неизвестный параметр" in output


def test_start_all_laptop1_missing_arg_value():
    """Verify start_all_laptop1.sh requires argument value."""
    script_path = os.path.join(SCRIPTS_DIR, 'start_all_laptop1.sh')
    proc = subprocess.run(
        [script_path, '--port'],
        capture_output=True,
        text=True,
        timeout=5
    )
    assert proc.returncode != 0
    output = proc.stdout + proc.stderr
    assert "требует номера порта" in output


def test_start_all_laptop1_unreachable_ollama_fails():
    """Verify start_all_laptop1.sh detects unreachable Ollama server and exits with error."""
    script_path = os.path.join(SCRIPTS_DIR, 'start_all_laptop1.sh')
    proc = subprocess.run(
        [script_path, '--llm-host', 'http://127.0.0.1:59999', '--no-browser'],
        capture_output=True,
        text=True,
        timeout=10
    )
    assert proc.returncode != 0
    output = proc.stdout + proc.stderr
    assert "Ollama не отвечает" in output
