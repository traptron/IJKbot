"""Teleoperation profile (Keyboard or DS4 gamepad)."""

from typing import Optional
from tools.ijk.config import IjkConfig
from tools.ijk.runner import Runner


def run_teleop(
    runner: Runner,
    config: IjkConfig,
    use_gamepad: bool = False,
    web_mode: bool = False,
    speed: Optional[float] = None,
    mock: bool = False,
    record: bool = False,
    bag_name: Optional[str] = None,
) -> None:
    prof = config.profiles.get("teleop")
    base_speed = prof.max_linear_velocity if prof else 0.35

    # Safe ceiling: max 0.4 m/s outside competition as agreed
    if speed is not None:
        target_speed = min(max(speed, 0.05), 0.40)
        if speed > 0.40:
            print(f"[teleop] Предупреждение: скорость ограничена безопасным максимумом 0.40 м/с")
    else:
        target_speed = base_speed

    print(f"\n==================================================================")
    print(f"  IJKbot — Ручное телеуправление [teleop]                          ")
    source = 'Веб-джойстик (/cmd_vel_joy)' if web_mode else ('Геймпад DS4 (/cmd_vel_joy)' if use_gamepad else 'Клавиатура (/cmd_vel_sm)')
    print(f"  Устройство: {source}")
    print(f"  Линейная скорость: {target_speed:.2f} м/с, ROS_DOMAIN_ID={runner.domain_id}")
    print(f"==================================================================")

    if record:
        runner.start_bag_recording(bag_name=bag_name)

    # 1. Start robot hardware on Pi if needed
    if mock or runner.local:
        print("[teleop] Запуск симуляции моторов локально (mock_hardware:=true)...")
        local_robot_cmd = [
            "ros2", "launch", "bringup", "robot.launch.py",
            "enable_lidar:=false",
            "enable_camera:=false",
            "mock_hardware:=true",
            f"max_linear_velocity:={target_speed}",
            f"wheel_diameter:={config.hardware.wheel_diameter}",
            f"wheel_separation:={config.hardware.wheel_separation}",
        ]
        runner.run_local_process(local_robot_cmd)
    elif runner.robot_ip:
        if not runner.is_remote_tmux_running():
            print(f"[teleop] Базовый стек на Pi ({runner.robot_ip}) не запущен. Запуск diff_drive_node...")
            remote_launch = (
                f"ros2 launch bringup robot.launch.py "
                f"enable_lidar:=false enable_camera:=false mock_hardware:=false "
                f"max_linear_velocity:={target_speed} "
                f"wheel_diameter:={config.hardware.wheel_diameter} "
                f"wheel_separation:={config.hardware.wheel_separation}"
            )
            runner.start_remote_launch(remote_launch)

    # 2. Control source
    if web_mode:
        print('[teleop] Ожидание команд веб-джойстика. Для выхода нажмите Ctrl+C.')
        runner.wait_with_ctrl_c()
    elif use_gamepad:
        print("[teleop] Запуск DS4_teleop на Pi -> топик /cmd_vel_joy (приоритет 60)...")
        if runner.robot_ip and not runner.local:
            cmd = "ros2 run DS4_teleop teleop_node --ros-args -r /cmd_vel:=/cmd_vel_joy"
            runner.run_remote_ssh(f"tmux new-window -t ijk -n ds4 '{cmd}' || true")
        print("[teleop] Геймпад активен. Для выхода нажмите Ctrl+C.")
        runner.wait_with_ctrl_c()
    else:
        print("[teleop] Инструкция по управлению:")
        print("  u  i  o   — Вперед-влево / Вперед / Вперед-вправо")
        print("  j  k  l   — Разворот влево / СТОП / Разворот вправо")
        print("  m  ,  .   — Назад-влево / Назад / Назад-вправо")
        print("  Пробел    — Экстренная остановка")
        print("  Ctrl+C    — Выход и штатная остановка\n")
        teleop_cmd = [
            "ros2", "run", "teleop_twist_keyboard", "teleop_twist_keyboard",
            "--ros-args",
            "-r", "/cmd_vel:=/cmd_vel_sm",
            "-p", f"speed:={target_speed}",
            "-p", "turn:=0.8",
        ]
        runner.run_local_process(teleop_cmd, interactive=True)
        runner.wait_with_ctrl_c()
