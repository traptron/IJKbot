#!/usr/bin/env python3
"""
mission_sm.py — Главный модуль координации миссии (Mission State Machine) и Web Dashboard
для мобильного робота IJKbot (Хакатон «Эвакуация», Кубок РТК Высшая Лига).

Объединяет все подсистемы робота в единый процесс:
1. LLM интерпретатор судейских заданий (Qwen 2.5 7B через Ollama)
2. Навигация Nav2 / одометрия к ориентирам полигона
3. Компьютерное зрение: детекция пострадавшего человека
4. Удержание робота в ячейке не менее 5 секунд по регламенту
5. Распознавание QR-кода состояния пострадавшего
6. Эвакуация и возврат в стартовую ячейку [0, 0]
7. Интерактивный судейский Web Dashboard на NiceGUI с протоколом и хронологией событий
"""

import os
import sys
import time
import math
import json
import signal
import subprocess
import threading
from pathlib import Path
from enum import Enum
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime

# ROS 2 импорты (с graceful fallback для автономного тестирования)
ROS2_AVAILABLE = False
try:
    import rclpy
    from rclpy.node import Node
    from geometry_msgs.msg import Twist, PoseStamped
    from nav_msgs.msg import Odometry
    from std_msgs.msg import String as RosString, Bool as RosBool
    ROS2_AVAILABLE = True
except ImportError:
    pass

# Локальный LLM клиент
try:
    from ijkbot_brain.llm_client import (
        LLMClient,
        LandmarkID,
        LANDMARK_DETAILS,
        target_details,
        CommandInterpretation
    )
except ImportError:
    from llm_client import (
        LLMClient,
        LandmarkID,
        LANDMARK_DETAILS,
        target_details,
        CommandInterpretation
    )

# NiceGUI
NICEGUI_AVAILABLE = False
try:
    from nicegui import ui, app
    NICEGUI_AVAILABLE = True
except ImportError:
    pass


# ============================================================================
# 1. СОСТОЯНИЯ И КОНТРАКТЫ МИССИИ
# ============================================================================

class MissionState(str, Enum):
    """Состояния конечного автомата миссии согласно PLAN.md (Этап 5)."""
    PREPARATION = "PREPARATION"                      # Ожидание ввода задания от судей
    LLM_PARSING = "LLM_PARSING"                      # Преобразование текста в JSON команду
    READY_TO_START = "READY_TO_START"                # Ожидание сигнала старта
    NAVIGATING_TO_LANDMARK = "NAVIGATING_TO_LANDMARK"# Движение к ориентиру полигона
    SEARCHING_VICTIM = "SEARCHING_VICTIM"            # Поиск пострадавшего камерой
    APPROACHING_VICTIM = "APPROACHING_VICTIM"        # Подъезд к пострадавшему
    WAIT_5_SECONDS = "WAIT_5_SECONDS"                # Удержание в ячейке не менее 5 сек (по регламенту)
    READING_QR = "READING_QR"                        # Считывание QR-кода состояния
    RETURNING_HOME = "RETURNING_HOME"                # Навигация в стартовую ячейку [0, 0]
    MISSION_COMPLETE = "MISSION_COMPLETE"            # Завершение миссии, фиксация итогов
    EMERGENCY_STOP = "EMERGENCY_STOP"                # Аварийная остановка (E-STOP)
    PAUSED = "PAUSED"                                # Пауза миссии


@dataclass
class Waypoint:
    """Целевая путевая точка в системе координат карты (map)."""
    x: float
    y: float
    yaw: float = 0.0
    cell: Tuple[int, int] = (0, 0)
    name: str = ""


@dataclass
class LogEntry:
    """Запись протокола с миллисекундной точностью."""
    timestamp: str
    elapsed_sec: float
    category: str  # STATE, NAV, VISION, QR, LLM, WARN, ERROR, EMERGENCY, SYS
    message: str


# Конфигурация ячеек полигона 5x5 (ячейка 800x800 мм)
# X: 0..4 (0.0..4.0 м), Y: 0..4 (0.0..4.0 м)
# Старт: [0, 0] -> центр (0.4, 0.4)
ARENA_CELL_SIZE = 0.8  # метров
ARENA_GRID_DIM = 5     # 5x5 ячеек

LANDMARK_WAYPOINTS: Dict[str, Waypoint] = {
    LandmarkID.SMOKE_TOWER.value: Waypoint(
        x=1.2, y=2.0, yaw=math.pi / 2, cell=(1, 3), name="Здание «Стакан»"
    ),
    LandmarkID.PANEL_HOUSE.value: Waypoint(
        x=2.0, y=2.8, yaw=0.0, cell=(3, 3), name="Панельный дом"
    ),
    LandmarkID.BRIDGES.value: Waypoint(
        x=1.2, y=1.2, yaw=0.0, cell=(2, 1), name="Мостовые переходы"
    ),
    LandmarkID.TANKER_TRUCK.value: Waypoint(
        x=2.0, y=1.2, yaw=0.0, cell=(3, 1), name="Аварийный бензовоз"
    ),
    LandmarkID.FALLEN_TREE.value: Waypoint(
        x=1.2, y=0.4, yaw=math.pi / 2, cell=(1, 1), name="Упавшее дерево"
    ),
    LandmarkID.CAR_JAM.value: Waypoint(
        x=2.8, y=2.0, yaw=0.0, cell=(4, 2), name="Транспортный затор"
    ),
    LandmarkID.DEBRIS_PVC.value: Waypoint(
        x=0.4, y=1.2, yaw=math.pi / 2, cell=(0, 2), name="Завал из ПВХ"
    ),
}

START_WAYPOINT = Waypoint(
    x=0.4, y=0.4, yaw=0.0, cell=(0, 0), name="Пункт сбора (Старт)"
)

DEFAULT_TASK_EXAMPLE = "Пострадавший не может выбраться из автомобильного затора, образовавшегося на мосту. Необходимо найти его среди автомобилей"


class SystemLauncher:
    """Управление единым мастером запуска robot_bringup + Nav2 (system.launch.py)."""
    def __init__(self):
        self.process: Optional[subprocess.Popen] = None
        self.is_running: bool = False
        self.log_lines: List[str] = []
        self.lock = threading.Lock()
        self.ssh_host: str = "192.168.1.10"
        self.ssh_user: str = "otmorozki"

    def is_alive(self) -> bool:
        if self.process is not None:
            if self.process.poll() is None:
                self.is_running = True
                return True
            self.is_running = False
            self.process = None
        return False

    def start(self, mock_hardware: bool = False, use_ssh: bool = False,
              initial_x: float = 0.4, initial_y: float = 0.4, initial_yaw: float = 0.0) -> Tuple[bool, str]:
        if self.is_alive():
            assert self.process
            return True, f"Система уже работает (PID {self.process.pid})"

        mock_str = "true" if mock_hardware else "false"

        if use_ssh:
            remote_cmd = (
                f"bash -c 'source /opt/ros/jazzy/setup.bash 2>/dev/null || true; "
                f"source /home/{self.ssh_user}/IJKbot/install/setup.bash 2>/dev/null || true; "
                f"ros2 launch ijkbot_bringup system.launch.py "
                f"mock_hardware:={mock_str} initial_x:={initial_x} initial_y:={initial_y} initial_yaw:={initial_yaw}'"
            )
            cmd = [
                "ssh", "-tt", "-o", "ConnectTimeout=5",
                f"{self.ssh_user}@{self.ssh_host}",
                remote_cmd
            ]
            desc = f"SSH ({self.ssh_user}@{self.ssh_host})"
        else:
            cmd = [
                "ros2", "launch", "ijkbot_bringup", "system.launch.py",
                f"mock_hardware:={mock_str}",
                f"initial_x:={initial_x}",
                f"initial_y:={initial_y}",
                f"initial_yaw:={initial_yaw}",
            ]
            desc = "локальный процесс"

        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                preexec_fn=os.setsid
            )
            self.is_running = True

            def _reader():
                assert self.process and self.process.stdout
                for line in iter(self.process.stdout.readline, ""):
                    if not line:
                        break
                    with self.lock:
                        self.log_lines.append(line.rstrip())
                        if len(self.log_lines) > 500:
                            self.log_lines.pop(0)

            t = threading.Thread(target=_reader, daemon=True)
            t.start()
            return True, f"Запущен {desc} (PID {self.process.pid})"
        except Exception as e:
            self.is_running = False
            self.process = None
            err_msg = f"Ошибка запуска system.launch.py: {e}"
            with self.lock:
                self.log_lines.append(f"[ERROR] {err_msg}")
            return False, err_msg

    def stop(self) -> str:
        if self.process is not None:
            pid = self.process.pid
            try:
                os.killpg(os.getpgid(pid), signal.SIGINT)
                self.process.wait(timeout=3)
            except Exception:
                try:
                    os.killpg(os.getpgid(pid), signal.SIGKILL)
                except Exception:
                    pass
            self.process = None
            self.is_running = False
            return f"Система остановлена (PID {pid})"
        return "Система не была запущена"


# ============================================================================
# 2. КОНЕЧНЫЙ АВТОМАТ МИССИИ (MISSION STATE MACHINE)
# ============================================================================

class MissionStateMachine:
    """
    Потокобезопасный конечный автомат миссии.
    Управляет жизненным циклом попытки, логированием и взаимодействием подсистем.
    """

    def __init__(self, llm_client: Optional[LLMClient] = None, mock_mode: bool = True):
        self.lock = threading.RLock()
        self.state = MissionState.PREPARATION
        self.previous_state = MissionState.PREPARATION
        self.mock_mode = mock_mode

        # Менеджер единого лаунча (Bringup + Nav2)
        self.system_launcher = SystemLauncher()

        # LLM клиент
        self.llm_client = llm_client or LLMClient()
        self.current_task_text: str = DEFAULT_TASK_EXAMPLE
        self.command_interpretation: Optional[CommandInterpretation] = None

        # Статусы выполнения ключевых этапов
        self.llm_parsed: bool = False
        self.victim_found: bool = False
        self.qr_scanned: bool = False
        self.evacuated_home: bool = False

        # Хронология событий (протокол)
        self.logs: List[LogEntry] = []

        # Временные метки
        self.mission_start_time: Optional[float] = None
        self.mission_end_time: Optional[float] = None
        self.wait_timer_start: Optional[float] = None
        self.wait_duration_required: float = 5.0

        # Навигация и координаты робота (в системе map)
        self.robot_x: float = 0.4
        self.robot_y: float = 0.4
        self.robot_yaw: float = 0.0
        self.path_history: List[Tuple[float, float]] = [(0.4, 0.4)]
        self.current_waypoint: Optional[Waypoint] = None

        # Состояние зрения и QR-кода
        self.victim_detected: bool = False
        self.qr_code_data: Optional[str] = None

        # ROS 2 узел (если инициализирован)
        self.ros_node: Optional[Any] = None

        # Инициализация первого лога
        self._log("SYS", "Конечный автомат миссии IJKbot инициализирован. Режим: " +
                  ("СИМУЛЯЦИЯ (Mock)" if self.mock_mode else "РЕАЛЬНОЕ ЖЕЛЕЗО"))

    # ------------------------------------------------------------------------
    # Логирование и таймстемпы
    # ------------------------------------------------------------------------
    def _now_str(self) -> str:
        now = datetime.now()
        return now.strftime("%H:%M:%S") + f".{int(now.microsecond / 1000):03d}"

    def get_elapsed_mission_sec(self) -> float:
        if self.mission_start_time is None:
            return 0.0
        if self.mission_end_time is not None:
            return max(0.0, self.mission_end_time - self.mission_start_time)
        return max(0.0, time.time() - self.mission_start_time)

    def _log(self, category: str, message: str) -> None:
        elapsed = self.get_elapsed_mission_sec()
        entry = LogEntry(
            timestamp=self._now_str(),
            elapsed_sec=elapsed,
            category=category,
            message=message
        )
        self.logs.append(entry)
        if len(self.logs) > 1000:
            self.logs.pop(0)

        # Вывод в ROS 2 логгер при наличии
        if self.ros_node and hasattr(self.ros_node, "node") and self.ros_node.node:
            try:
                self.ros_node.node.get_logger().info(f"[{category}] {message}")
            except Exception:
                pass

    # ------------------------------------------------------------------------
    # Внешние действия пользователя и судей
    # ------------------------------------------------------------------------
    def set_task_description(self, task_text: str) -> None:
        with self.lock:
            self.current_task_text = task_text.strip()
            self._log("LLM", f"Задано задание от судей: «{self.current_task_text}»")

    def parse_task_with_llm(self) -> CommandInterpretation:
        """
        Запуск анализа задания моделью Qwen 2.5 7B.
        """
        with self.lock:
            if not self.current_task_text:
                raise ValueError("Текст задания судей не может быть пустым")

            self.previous_state = self.state
            self.state = MissionState.LLM_PARSING
            self.command_interpretation = None
            self.current_waypoint = None
            self.llm_parsed = False
            self._log("LLM", "Запуск инференса языковой модели Qwen 2.5 7B...")

        try:
            interp = self.llm_client.interpret(self.current_task_text)
            if interp.nav2_goal is not None:
                from ijkbot_brain.llm_client import load_arena, validate_nav2_goal
                arena = getattr(self.llm_client, 'arena', None) or load_arena()
                goal = validate_nav2_goal(interp.nav2_goal, interp.target_landmark_id, arena)
                waypoint = Waypoint(
                    x=goal['x'], y=goal['y'], yaw=goal['yaw'],
                    cell=(int(goal['x'] / 0.8), int(goal['y'] / 0.8)),
                    name=interp.target_landmark_id)
            elif self.mock_mode:
                waypoint = LANDMARK_WAYPOINTS.get(interp.target_landmark_id, START_WAYPOINT)
            else:
                raise ValueError('Нет проверенной nav2_goal; уточните объект и его координаты в карте')
        except Exception as e:
            with self.lock:
                self.state = MissionState.PREPARATION
                self._log("ERROR", f"Сбой обработки LLM: {str(e)}")
            raise e

        with self.lock:
            self.command_interpretation = interp
            self.llm_parsed = True
            lm_id = interp.target_landmark_id
            lm_info = target_details(lm_id)
            lm_name = lm_info.get("name_ru", lm_id)

            self._log(
                "LLM",
                f"Задание успешно распознано ({interp.source}, задержка: {interp.latency_sec:.2f}с). "
                f"Целевой ориентир: «{lm_name}» [{lm_id}], тактика: {interp.search_strategy}"
            )
            self._log("LLM", f"Обоснование модели: {interp.reasoning}")

            # Назначение путевой точки к ориентиру
            self.current_waypoint = waypoint
            self.state = MissionState.READY_TO_START
            return interp

    def start_mission(self) -> None:
        """Старт выполнения миссии по кнопке судей/оператора."""
        with self.lock:
            if self.state not in [MissionState.READY_TO_START, MissionState.PREPARATION]:
                self._log("WARN", f"Попытка старта из недопустимого состояния {self.state}")
                return

            if not self.command_interpretation:
                if self.current_task_text:
                    self.parse_task_with_llm()
                else:
                    self.set_task_description(DEFAULT_TASK_EXAMPLE)
                    self.parse_task_with_llm()

            self.mission_start_time = time.time()
            self.mission_end_time = None
            self.state = MissionState.NAVIGATING_TO_LANDMARK
            self._log("STATE", f"СТАРТ МИССИИ! Движение к ориентиру: {self.current_waypoint.name}")

            # Публикация цели Nav2 в ROS 2
            self._publish_goal_pose(self.current_waypoint)

    def trigger_emergency_stop(self) -> None:
        """Аварийная остановка робота (E-STOP)."""
        with self.lock:
            self.previous_state = self.state
            self.state = MissionState.EMERGENCY_STOP
            if self.ros_node and getattr(self.ros_node, 'trial_mode', False):
                self.ros_node.set_trial_stop(True)
            self._publish_zero_velocity()
            self._log("EMERGENCY", "ВНИМАНИЕ: АКТИВИРОВАН E-STOP! Движение мгновенно остановлено.")

    def reset_emergency_stop(self) -> None:
        """Сброс аварийной остановки."""
        with self.lock:
            if self.state == MissionState.EMERGENCY_STOP:
                if self.ros_node and getattr(self.ros_node, 'trial_mode', False):
                    self.ros_node.set_trial_stop(False)
                    self.state = MissionState.READY_TO_START
                    return
                self.state = self.previous_state or MissionState.PREPARATION
                self._log("SYS", f"E-STOP сброшен. Возврат в состояние: {self.state}")

    def toggle_pause(self) -> None:
        """Пауза / возобновление миссии."""
        with self.lock:
            if not self.mock_mode and self.ros_node and getattr(self.ros_node, 'trial_mode', False):
                self.trigger_emergency_stop()
                self._log('WARN', 'Испытание отменено; для повторного запуска сбросьте E-STOP и нажмите Старт')
                return
            if self.state == MissionState.PAUSED:
                self.state = self.previous_state or MissionState.READY_TO_START
                self._log("STATE", f"Миссия возобновлена. Состояние: {self.state}")
            elif self.state not in [MissionState.PREPARATION, MissionState.MISSION_COMPLETE, MissionState.EMERGENCY_STOP]:
                self.previous_state = self.state
                self.state = MissionState.PAUSED
                self._publish_zero_velocity()
                self._log("STATE", "Миссия приостановлена (ПАУЗА)")

    def reset_mission(self) -> None:
        """Полный сброс автомата миссии к исходному состоянию."""
        with self.lock:
            if not self.mock_mode and self.ros_node and getattr(self.ros_node, 'trial_mode', False):
                self.ros_node.set_trial_stop(True)
            self.state = MissionState.PREPARATION
            self.previous_state = MissionState.PREPARATION
            self.llm_parsed = False
            self.victim_found = False
            self.qr_scanned = False
            self.evacuated_home = False
            self.mission_start_time = None
            self.mission_end_time = None
            self.wait_timer_start = None
            self.command_interpretation = None
            self.robot_x = 0.4
            self.robot_y = 0.4
            self.robot_yaw = 0.0
            self.path_history = [(0.4, 0.4)]
            self.current_waypoint = None
            self.victim_detected = False
            self.qr_code_data = None
            self._publish_zero_velocity()
            self._log("SYS", "Сброс миссии выполнен. Все состояния и координаты возвращены в исходное положение.")

    # ------------------------------------------------------------------------
    # Внутренний цикл автомата (вызывается с шагом dt)
    # ------------------------------------------------------------------------
    def step(self, dt: float = 0.1) -> None:
        with self.lock:
            if not self.mock_mode and self.ros_node and getattr(self.ros_node, 'trial_mode', False):
                # Реальную последовательность ведёт trial_planner; GUI отображает его статус.
                self.ros_node.publish_mission_status()
                return
            # 1. Симуляция движения в mock-режиме
            if self.mock_mode and self.current_waypoint and self.state in [
                MissionState.NAVIGATING_TO_LANDMARK,
                MissionState.APPROACHING_VICTIM,
                MissionState.RETURNING_HOME
            ]:
                self._step_mock_kinematics(dt)

            # 2. Логика переходов автомата состояний
            if self.state == MissionState.NAVIGATING_TO_LANDMARK:
                if self._check_reached_waypoint(self.current_waypoint):
                    self._log("NAV", f"Робот прибыл к точке ориентира «{self.current_waypoint.name}». Начало визуального поиска пострадавшего...")
                    self.state = MissionState.SEARCHING_VICTIM

            elif self.state == MissionState.SEARCHING_VICTIM:
                self._handle_victim_search(dt)

            elif self.state == MissionState.APPROACHING_VICTIM:
                if self._check_reached_waypoint(self.current_waypoint):
                    self._log("NAV", "Робот прибыл в ячейку к пострадавшему. Начало регламентного 5-секундного удержания...")
                    self.state = MissionState.WAIT_5_SECONDS
                    self.wait_timer_start = time.time()
                    self._publish_zero_velocity()

            elif self.state == MissionState.WAIT_5_SECONDS:
                self._publish_zero_velocity()
                if self.wait_timer_start is not None:
                    wait_elapsed = time.time() - self.wait_timer_start
                    if wait_elapsed >= self.wait_duration_required:
                        self._log("STATE", f"Регламентная 5-секундная фиксация выполнена ({wait_elapsed:.1f}с). Переход к считыванию QR-кода...")
                        self.state = MissionState.READING_QR
                        self.qr_code_data = None

            elif self.state == MissionState.READING_QR:
                self._handle_qr_reading(dt)

            elif self.state == MissionState.RETURNING_HOME:
                if self._check_reached_waypoint(START_WAYPOINT):
                    self._handle_mission_completion()

            # 3. Публикация статуса в топики ROS 2
            if self.ros_node and hasattr(self.ros_node, "publish_mission_status"):
                self.ros_node.publish_mission_status()

    # ------------------------------------------------------------------------
    # Обработчики конкретных состояний
    # ------------------------------------------------------------------------
    def _handle_victim_search(self, dt: float) -> None:
        """Поиск человека камерой."""
        if not hasattr(self, "_search_time"):
            self._search_time = 0.0
        self._search_time += dt

        if self.mock_mode:
            # Плавный поворот камеры/робота для осмотра
            self.robot_yaw = (self.robot_yaw + 0.3 * dt) % (2 * math.pi)

            # Через 1.5 секунды осмотра находим пострадавшего
            if self._search_time >= 1.5:
                self._search_time = 0.0
                self.victim_detected = True
                self.victim_found = True
                self._log("VISION", "Пострадавший человек обнаружен в смежной ячейке!")

                # Назначаем путевую точку вплотную к пострадавшему
                target_x = self.current_waypoint.x + 0.3 * math.cos(self.robot_yaw)
                target_y = self.current_waypoint.y + 0.3 * math.sin(self.robot_yaw)
                self.current_waypoint = Waypoint(
                    x=min(3.6, max(0.4, target_x)),
                    y=min(3.6, max(0.4, target_y)),
                    yaw=self.robot_yaw,
                    name="Ячейка пострадавшего"
                )
                self.state = MissionState.APPROACHING_VICTIM
                self._log("NAV", "Начало подъезда в ячейку пострадавшего...")
                self._publish_goal_pose(self.current_waypoint)
        else:
            # Реальный режим: ожидание флага детекции
            if self.victim_detected:
                self._search_time = 0.0
                self.victim_detected = True
                self.victim_found = True
                self._log("VISION", "Пострадавший человек обнаружен!")
                if self.current_waypoint:
                    target_x = self.current_waypoint.x + 0.25 * math.cos(self.robot_yaw)
                    target_y = self.current_waypoint.y + 0.25 * math.sin(self.robot_yaw)
                    self.current_waypoint = Waypoint(
                        x=min(3.6, max(0.4, target_x)),
                        y=min(3.6, max(0.4, target_y)),
                        yaw=self.robot_yaw,
                        name="Ячейка пострадавшего"
                    )
                    self._publish_goal_pose(self.current_waypoint)
                self.state = MissionState.APPROACHING_VICTIM
                self._log("NAV", "Начало подъезда в ячейку пострадавшего...")

    def _handle_qr_reading(self, dt: float) -> None:
        """Ожидание результата отдельной ноды ijkbot_vision/qr_reader_node."""
        self._publish_zero_velocity()
        if self.mock_mode and not self.qr_code_data:
            mock_qr = (
                "ПОСТРАДАВШИЙ #1\n"
                "ФИО: Иванов И.И.\n"
                "Состояние: Средней тяжести\n"
                "Пульс: 74 уд/мин, SpO2: 96%\n"
                "Травма: Перелом голени, сознание сохранено"
            )
            self.qr_code_data = mock_qr

        if not self.qr_code_data:
            return

        if not self.qr_scanned:
            self.qr_scanned = True
            self._log("QR", f"Данные с QR-кода состояния успешно считаны:\n{self.qr_code_data}")

            # Направляем робота домой в стартовую ячейку [0, 0]
            self.current_waypoint = START_WAYPOINT
            self.state = MissionState.RETURNING_HOME
            self._log("NAV", "Начало эвакуации пострадавшего в пункт сбора (ячейка [0, 0])...")
            self._publish_goal_pose(START_WAYPOINT)

    def _handle_mission_completion(self) -> None:
        """Фиксация успешной эвакуации и завершения миссии."""
        self.evacuated_home = True
        self.state = MissionState.MISSION_COMPLETE
        self.mission_end_time = time.time()
        self._publish_zero_velocity()

        self._log("STATE", "Пострадавший успешно эвакуирован в стартовую ячейку [0, 0]!")
        self._log("STATE", "=== МИССИЯ ПОЛНОСТЬЮ ЗАВЕРШЕНА ===")

        # Автоматическое сохранение протокола на диск в папку log/
        saved_path = self.save_protocol_to_disk()
        if saved_path:
            self._log("SYS", f"Протокол миссии автоматически сохранен на диск: {saved_path}")

    # ------------------------------------------------------------------------
    # Кинематика симулятора (Mock Differential Drive)
    # ------------------------------------------------------------------------
    def _step_mock_kinematics(self, dt: float) -> None:
        """Моделирование дифференциального движения со скоростью V <= 0.24 м/с."""
        wp = self.current_waypoint
        if not wp:
            return

        dx = wp.x - self.robot_x
        dy = wp.y - self.robot_y
        dist = math.hypot(dx, dy)
        target_yaw = math.atan2(dy, dx)

        yaw_diff = (target_yaw - self.robot_yaw + math.pi) % (2 * math.pi) - math.pi
        max_v = 0.24
        max_w = 0.8

        if dist > 0.05:
            if abs(yaw_diff) > 0.35:
                w = math.copysign(min(max_w, abs(yaw_diff) * 1.5), yaw_diff)
                v = 0.0
            else:
                v = min(max_v, dist * 1.2)
                w = math.copysign(min(max_w, abs(yaw_diff) * 1.2), yaw_diff)

            self.robot_yaw = (self.robot_yaw + w * dt) % (2 * math.pi)
            self.robot_x += v * math.cos(self.robot_yaw) * dt
            self.robot_y += v * math.sin(self.robot_yaw) * dt

            last_x, last_y = self.path_history[-1]
            if math.hypot(self.robot_x - last_x, self.robot_y - last_y) > 0.05:
                self.path_history.append((self.robot_x, self.robot_y))
        else:
            final_yaw_diff = (wp.yaw - self.robot_yaw + math.pi) % (2 * math.pi) - math.pi
            if abs(final_yaw_diff) > 0.08:
                w = math.copysign(min(max_w, abs(final_yaw_diff) * 1.5), final_yaw_diff)
                self.robot_yaw = (self.robot_yaw + w * dt) % (2 * math.pi)

    def _check_reached_waypoint(self, wp: Optional[Waypoint]) -> bool:
        if not wp:
            return False
        dist = math.hypot(wp.x - self.robot_x, wp.y - self.robot_y)
        yaw_diff = abs((wp.yaw - self.robot_yaw + math.pi) % (2 * math.pi) - math.pi)
        tol_dist = 0.08 if self.mock_mode else 0.18
        tol_yaw = 0.25 if self.mock_mode else 0.35
        return dist < tol_dist and yaw_diff < tol_yaw

    # ------------------------------------------------------------------------
    # ROS 2 интеграция (публикация команд и целей)
    # ------------------------------------------------------------------------
    def _publish_goal_pose(self, wp: Waypoint) -> None:
        if self.ros_node and ROS2_AVAILABLE and not self.mock_mode:
            try:
                self.ros_node.send_nav_goal(wp.x, wp.y, wp.yaw)
            except Exception as e:
                self._log("WARN", f"Ошибка отправки цели в Nav2: {e}")

    def _publish_zero_velocity(self) -> None:
        if self.ros_node and ROS2_AVAILABLE and not self.mock_mode:
            try:
                self.ros_node.send_cmd_vel(0.0, 0.0)
            except Exception:
                pass

    # ------------------------------------------------------------------------
    # Экспорт и сохранение протокола
    # ------------------------------------------------------------------------
    def export_protocol_dict(self) -> Dict[str, Any]:
        with self.lock:
            return {
                "document": "Протокол и хронология событий миссии IJKbot",
                "competition": "Кубок РТК Высшая Лига — Хакатон «Эвакуация» (Ижевск)",
                "timestamp": datetime.now().isoformat(),
                "task_text": self.current_task_text,
                "command_interpretation": self.command_interpretation.to_dict() if self.command_interpretation else None,
                "execution_status": {
                    "llm_parsed": self.llm_parsed,
                    "victim_found": self.victim_found,
                    "qr_scanned": self.qr_scanned,
                    "evacuated_home": self.evacuated_home,
                    "final_state": self.state.value,
                },
                "qr_code_data": self.qr_code_data,
                "chronology": [asdict(l) for l in self.logs]
            }

    def export_protocol_json(self) -> str:
        return json.dumps(self.export_protocol_dict(), ensure_ascii=False, indent=2)

    def save_protocol_to_disk(self) -> Optional[str]:
        """Сохранение протокола в директорию log/."""
        try:
            log_dir = Path(os.environ.get("IJKBOT_LOG_DIR", Path.cwd() / "log"))
            log_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            file_path = log_dir / f"protocol_{ts}.json"
            file_path.write_text(self.export_protocol_json(), encoding="utf-8")
            return str(file_path)
        except Exception as e:
            print(f"[PROTOCOL] Ошибка сохранения протокола на диск: {e}")
            return None


# ============================================================================
# 3. ROS 2 НОДА ДЛЯ MISSION_SM
# ============================================================================

class MissionROSNode:
    """Обёртка ROS 2 узла для связи State Machine с Nav2, драйвером и топиками."""

    def __init__(self, sm: MissionStateMachine):
        self.sm = sm
        self.node: Optional[Any] = None
        self.cmd_vel_pub: Optional[Any] = None
        self.goal_pub: Optional[Any] = None
        self.state_pub: Optional[Any] = None

        if ROS2_AVAILABLE:
            try:
                if not rclpy.ok():
                    rclpy.init()
                self.node = Node("mission_state_machine")
                self.node.declare_parameter('trial_mode', True)
                self.trial_mode = self.node.get_parameter('trial_mode').value
                self.stop_pub = self.node.create_publisher(RosBool, '/emergency_stop', 10)
                if not self.trial_mode:
                    self.cmd_vel_pub = self.node.create_publisher(Twist, "/cmd_vel", 10)
                else:
                    self.node.create_subscription(RosString, '/trial/state', self._trial_callback, 10)
                self.node.declare_parameter('goal_topic', '/goal_pose')
                self.goal_pub = self.node.create_publisher(
                    PoseStamped, self.node.get_parameter('goal_topic').value, 10)
                self.state_pub = self.node.create_publisher(RosString, "/mission/state", 10)

                # Подписки на сенсоры и топики
                self.node.create_subscription(Odometry, "/odom", self._odom_callback, 10)
                self.node.create_subscription(RosString, "/victim_status", self._qr_callback, 10)
                self.node.create_subscription(RosBool, "/victim_detected", self._victim_detected_callback, 10)
                if not self.trial_mode:
                    self.node.create_subscription(RosString, "/mission/judge_task", self._judge_task_callback, 10)
                self.node.create_subscription(RosBool, "/emergency_stop", self._estop_callback, 10)

                self.sm.ros_node = self
                self.node.get_logger().info("MissionROSNode успешно запущен")
            except Exception as e:
                print(f"[ROS2] Ошибка запуска ROS 2 ноды: {e}")

    def _odom_callback(self, msg: Any) -> None:
        with self.sm.lock:
            if not self.sm.mock_mode:
                self.sm.robot_x = msg.pose.pose.position.x
                self.sm.robot_y = msg.pose.pose.position.y
                q = msg.pose.pose.orientation
                siny_cosp = 2 * (q.w * q.z + q.x * q.y)
                cosy_cosp = 1 - 2 * (q.y * q.y + q.z * q.z)
                self.sm.robot_yaw = math.atan2(siny_cosp, cosy_cosp)
                self.sm.path_history.append((self.sm.robot_x, self.sm.robot_y))

    def _victim_detected_callback(self, msg: Any) -> None:
        with self.sm.lock:
            if msg.data and not self.sm.victim_detected:
                self.sm.victim_detected = True

    def _judge_task_callback(self, msg: Any) -> None:
        text = msg.data.strip()
        if text:
            with self.sm.lock:
                self.sm.set_task_description(text)
            try:
                self.sm.parse_task_with_llm()
            except Exception as e:
                self.sm._log("ERROR", f"Ошибка обработки топика /mission/judge_task: {e}")

    def _qr_callback(self, msg: Any) -> None:
        with self.sm.lock:
            if self.sm.state == MissionState.READING_QR and msg.data.strip():
                self.sm.qr_code_data = msg.data

    def _estop_callback(self, msg: Any) -> None:
        if msg.data:
            if getattr(self, 'trial_mode', False):
                with self.sm.lock:
                    if not self.sm.mock_mode:
                        self.sm.state = MissionState.EMERGENCY_STOP
            else:
                self.sm.trigger_emergency_stop()

    def set_trial_stop(self, stopped: bool) -> None:
        if not self.sm.mock_mode:
            self.stop_pub.publish(RosBool(data=stopped))

    def _trial_callback(self, msg: Any) -> None:
        states = {
            'OUTBOUND': MissionState.NAVIGATING_TO_LANDMARK,
            'HOLDING': MissionState.WAIT_5_SECONDS,
            'RETURNING': MissionState.RETURNING_HOME,
            'COMPLETE': MissionState.MISSION_COMPLETE,
            'FAILED': MissionState.EMERGENCY_STOP,
            'STOPPED': MissionState.EMERGENCY_STOP,
        }
        with self.sm.lock:
            if self.sm.mock_mode or msg.data not in states:
                return
            if getattr(self, '_last_trial_state', None) == msg.data:
                return
            self._last_trial_state = msg.data
            state = states[msg.data]
            if self.sm.state != state:
                self.sm._log('NAV', f'Планер испытания: {msg.data}')
                self.sm.state = state
                if msg.data == 'COMPLETE':
                    self.sm.mission_end_time = time.time()
                    self.sm.save_protocol_to_disk()

    def publish_mission_status(self) -> None:
        if self.state_pub:
            s_msg = RosString()
            s_msg.data = self.sm.state.value
            self.state_pub.publish(s_msg)

    def send_cmd_vel(self, linear_x: float, angular_z: float) -> None:
        if self.cmd_vel_pub:
            msg = Twist()
            msg.linear.x = float(linear_x)
            msg.angular.z = float(angular_z)
            self.cmd_vel_pub.publish(msg)

    def send_nav_goal(self, x: float, y: float, yaw: float) -> None:
        if self.goal_pub and self.node:
            msg = PoseStamped()
            msg.header.frame_id = "map"
            msg.header.stamp = self.node.get_clock().now().to_msg()
            msg.pose.position.x = float(x)
            msg.pose.position.y = float(y)
            msg.pose.position.z = 0.0
            msg.pose.orientation.z = math.sin(yaw / 2.0)
            msg.pose.orientation.w = math.cos(yaw / 2.0)
            self.goal_pub.publish(msg)

    def spin_in_background(self) -> None:
        if self.node:
            def _spin():
                try:
                    rclpy.spin(self.node)
                except Exception:
                    pass
            t = threading.Thread(target=_spin, daemon=True)
            t.start()


# ============================================================================
# 4. СУДЕЙСКИЙ WEB DASHBOARD (NICEGUI)
# ============================================================================

STATE_COLORS = {
    MissionState.PREPARATION: "bg-gray-700 text-gray-200",
    MissionState.LLM_PARSING: "bg-blue-600 text-white animate-pulse",
    MissionState.READY_TO_START: "bg-purple-600 text-white",
    MissionState.NAVIGATING_TO_LANDMARK: "bg-amber-600 text-white",
    MissionState.SEARCHING_VICTIM: "bg-yellow-600 text-black animate-pulse",
    MissionState.APPROACHING_VICTIM: "bg-lime-600 text-black",
    MissionState.WAIT_5_SECONDS: "bg-cyan-600 text-white animate-pulse",
    MissionState.READING_QR: "bg-sky-500 text-black",
    MissionState.RETURNING_HOME: "bg-indigo-600 text-white",
    MissionState.MISSION_COMPLETE: "bg-emerald-600 text-white font-bold",
    MissionState.EMERGENCY_STOP: "bg-rose-700 text-white font-bold animate-bounce",
    MissionState.PAUSED: "bg-orange-500 text-black",
}


def build_judge_dashboard(sm: MissionStateMachine):
    """Создание интерфейса NiceGUI без баллов и видеопотока."""
    if not NICEGUI_AVAILABLE:
        print("[DASHBOARD] Пакет nicegui не установлен. Работает в headless-режиме.")
        return

    ui.page_title("IJKbot — Центр Управления Миссией")
    ui.dark_mode().enable()

    # ------------------------------------------------------------------------
    # ШАПКА ИНТЕРФЕЙСА
    # ------------------------------------------------------------------------
    with ui.header().classes("bg-slate-900 border-b border-slate-700 px-6 py-3 flex justify-between items-center"):
        with ui.row().classes("items-center gap-4"):
            ui.icon("smart_toy", size="2.4rem").classes("text-emerald-400")
            with ui.column().classes("gap-0"):
                ui.label("IJKbot • Судейский Центр Управления Миссией").classes("text-xl font-bold text-slate-100")
                ui.label("Хакатон «Эвакуация» • Кубок РТК Высшая Лига (Ижевск)").classes("text-xs text-slate-400")

        with ui.row().classes("items-center gap-4"):
            mock_switch = ui.switch("Режим симуляции (Mock)", value=sm.mock_mode).classes("text-sm text-slate-300")
            mock_switch.on_value_change(lambda e: setattr(sm, "mock_mode", e.value))
            state_badge = ui.badge("PREPARATION").classes("px-4 py-2 text-sm font-bold rounded-lg shadow-md uppercase")

    # ------------------------------------------------------------------------
    # ОСНОВНОЙ КОНТЕНТ
    # ------------------------------------------------------------------------
    with ui.column().classes("w-full max-w-7xl mx-auto p-4 gap-4"):

        # 0. ПАНЕЛЬ УПРАВЛЕНИЯ БОРТОВЫМ СТЕКОМ (system.launch.py)
        with ui.card().classes("w-full bg-slate-800/80 border border-slate-700 rounded-xl p-4 shadow-lg"):
            with ui.row().classes("w-full justify-between items-center"):
                with ui.row().classes("items-center gap-3"):
                    ui.icon("rocket_launch", size="1.4rem").classes("text-cyan-400")
                    ui.label("Бортовой стек робота (Bringup + Nav2)").classes("text-base font-semibold text-slate-200")
                    launch_status_badge = ui.badge("ОСТАНОВЛЕН", color="gray-600").classes("px-3 py-1 text-xs font-bold rounded uppercase")

                with ui.row().classes("items-center gap-3"):
                    ssh_switch = ui.switch("Запуск по SSH на робота (192.168.1.10)", value=False).classes("text-xs text-slate-300")

                    def handle_launch_system():
                        ok, msg = sm.system_launcher.start(
                            mock_hardware=sm.mock_mode,
                            use_ssh=ssh_switch.value
                        )
                        sm._log("SYS", f"Запуск стека: {msg}")
                        ui.notify(msg, type="positive" if ok else "negative")

                    def handle_stop_system():
                        msg = sm.system_launcher.stop()
                        sm._log("SYS", msg)
                        ui.notify(msg, type="info")

                    ui.button("Запустить стек", on_click=handle_launch_system, icon="play_arrow").classes(
                        "bg-cyan-600 hover:bg-cyan-500 font-semibold px-4 text-xs"
                    )
                    ui.button("Остановить", on_click=handle_stop_system, icon="stop").classes(
                        "bg-slate-700 hover:bg-rose-700 font-semibold px-3 text-xs text-slate-200"
                    )

                    with ui.dialog() as launch_log_dialog, ui.card().classes("w-[800px] max-w-4xl bg-slate-900 border border-slate-700"):
                        ui.label("Консольный вывод system.launch.py").classes("text-sm font-bold text-cyan-300 mb-2")
                        launch_log_view = ui.column().classes("w-full max-h-96 overflow-y-auto font-mono text-xs bg-black p-3 rounded border border-slate-800 gap-0.5")
                        ui.button("Закрыть", on_click=launch_log_dialog.close).classes("mt-3 self-end text-xs")

                    def open_launch_log():
                        launch_log_view.clear()
                        with launch_log_view:
                            for line in sm.system_launcher.log_lines[-200:]:
                                ui.label(line).classes("text-slate-300 whitespace-pre-wrap")
                        launch_log_dialog.open()

                    ui.button("Логи стека", on_click=open_launch_log, icon="terminal").classes(
                        "bg-slate-700 hover:bg-slate-600 text-xs text-slate-200"
                    )

        # 1. ПАНЕЛЬ ВВОДА ЗАДАНИЯ И КНОПКИ УПРАВЛЕНИЯ
        with ui.card().classes("w-full bg-slate-800/80 border border-slate-700 rounded-xl p-4 shadow-lg"):
            with ui.row().classes("w-full items-center gap-2 mb-2"):
                ui.icon("gavel", size="1.3rem").classes("text-amber-400")
                ui.label("Судейское задание").classes("text-base font-semibold text-slate-200")

            # Свободное поле ввода с возможностью быстрой очистки
            task_input = ui.input(
                label="Текст задания для робота (русский язык)",
                value=sm.current_task_text,
                placeholder="Введите текст задания судей...",
            ).props("clearable").classes("w-full text-sm font-sans")

            with ui.row().classes("w-full justify-between items-center mt-3 pt-3 border-t border-slate-700/60"):
                with ui.row().classes("gap-3 items-center"):
                    # Кнопка «ВСЁ В 1 КЛИК: Распознать и Поехать»
                    def handle_all_in_one():
                        text = task_input.value or ""
                        if not text.strip():
                            ui.notify("Пожалуйста, введите текст задания судей!", type="warning")
                            return
                        sm.set_task_description(text)

                        # Шаг 1: LLM
                        try:
                            sm.parse_task_with_llm()
                            ui.notify("1/3 Задание успешно распознано LLM!", type="positive")
                        except Exception as ex:
                            ui.notify(f"Ошибка LLM: {ex}", type="negative")
                            return

                        # Шаг 2: System Launch (если ещё не запущен)
                        if not sm.system_launcher.is_alive():
                            ok, msg = sm.system_launcher.start(
                                mock_hardware=sm.mock_mode,
                                use_ssh=ssh_switch.value
                            )
                            sm._log("SYS", f"Автозапуск стека: {msg}")
                            ui.notify(f"2/3 {msg}", type="info" if ok else "warning")

                        # Шаг 3: Старт миссии
                        sm.start_mission()
                        ui.notify("3/3 МИССИЯ ЗАПУЩЕНА! Робот следует к цели.", type="positive")

                    ui.button(
                        "ВСЁ В 1 КЛИК",
                        on_click=handle_all_in_one,
                        icon="bolt"
                    ).classes(
                        "bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white font-black px-6 text-base shadow-lg tracking-wide"
                    )

                    # 1. Шаг 1: Распознать задание
                    def handle_llm_parse():
                        text = task_input.value or ""
                        if not text.strip():
                            ui.notify("Пожалуйста, введите текст задания!", type="warning")
                            return
                        sm.set_task_description(text)
                        try:
                            sm.parse_task_with_llm()
                            ui.notify("Задание успешно распознано LLM!", type="positive")
                        except Exception as ex:
                            ui.notify(f"Ошибка LLM: {ex}", type="negative")

                    ui.button("Распознать (LLM)", on_click=handle_llm_parse, icon="psychology").classes(
                        "bg-blue-600 hover:bg-blue-500 font-semibold px-4"
                    )

                    # 2. Шаг 2: СТАРТ МИССИИ
                    def handle_start():
                        sm.set_task_description(task_input.value or "")
                        sm.start_mission()
                        ui.notify("Миссия запущена!", type="info")

                    ui.button("СТАРТ МИССИИ", on_click=handle_start, icon="play_arrow").classes(
                        "bg-emerald-600 hover:bg-emerald-500 font-bold px-6 text-base"
                    )

                    # Пауза
                    ui.button("Пауза", on_click=sm.toggle_pause, icon="pause").classes(
                        "bg-slate-700 hover:bg-slate-600 text-slate-200"
                    )

                    # Сброс
                    ui.button("Сброс", on_click=sm.reset_mission, icon="replay").classes(
                        "bg-slate-700 hover:bg-slate-600 text-slate-200"
                    )

                # Кнопка E-STOP
                ui.button(
                    "E-STOP",
                    on_click=lambda: (sm.trigger_emergency_stop(), ui.notify("АВАРИЙНАЯ ОСТАНОВКА АКТИВИРОВАНА!", type="negative")),
                    icon="stop"
                ).classes("bg-rose-700 hover:bg-rose-600 text-white font-black px-6 text-base tracking-wider")

        # 2. СРЕДНИЙ БЛОК: КАРТА ПОЛИГОНА (СЛЕВА) И КАРТОЧКИ LLM + QR (СПРАВА)
        with ui.row().classes("w-full gap-4 items-start"):

            # ЛЕВАЯ КОЛОНКА: ВЕКТОРНАЯ КАРТА ПОЛИГОНА 5x5
            with ui.column().classes("w-7/12 gap-4"):
                with ui.card().classes("w-full bg-slate-800/80 border border-slate-700 rounded-xl p-4 shadow-lg"):
                    with ui.row().classes("w-full justify-between items-center mb-2"):
                        with ui.row().classes("items-center gap-2"):
                            ui.icon("map", size="1.4rem").classes("text-emerald-400")
                            ui.label("Карта арены 5×5 (4.0 × 4.0 м)").classes("text-base font-semibold text-slate-200")
                        coords_label = ui.label("X: 0.40 м | Y: 0.40 м | Yaw: 0°").classes(
                            "text-xs font-mono text-cyan-300 bg-slate-900 px-3 py-1 rounded"
                        )

                    map_html = ui.html("").classes("w-full flex justify-center")

            # ПРАВАЯ КОЛОНКА: КАРТОЧКА LLM И КАРТОЧКА QR-КОДА
            with ui.column().classes("w-5/12 gap-4"):

                # Карточка анализа LLM
                with ui.card().classes("w-full bg-slate-800/80 border border-slate-700 rounded-xl p-4 shadow-lg"):
                    with ui.row().classes("items-center gap-2 mb-2"):
                        ui.icon("psychology", size="1.4rem").classes("text-blue-400")
                        ui.label("Результат анализа LLM (Qwen 2.5 7B)").classes("text-base font-semibold text-slate-200")

                    landmark_name_label = ui.label("Ориентир: ожидание задания").classes("text-base font-bold text-blue-300")
                    strategy_label = ui.label("Тактика поиска: —").classes("text-xs font-mono text-slate-400")
                    reasoning_label = ui.label("Обоснование: введите текст задания и нажмите «Распознать (LLM)»").classes(
                        "text-xs text-slate-300 italic bg-slate-900/60 p-2.5 rounded-lg border border-slate-700/50"
                    )

                # Карточка считанного QR-кода
                with ui.card().classes("w-full bg-slate-800/80 border border-slate-700 rounded-xl p-4 shadow-lg"):
                    with ui.row().classes("items-center gap-2 mb-2"):
                        ui.icon("qr_code_2", size="1.4rem").classes("text-cyan-400")
                        ui.label("Данные QR-кода пострадавшего").classes("text-base font-semibold text-slate-200")

                    qr_status_badge = ui.badge("QR не считан", color="gray-600").classes("text-xs w-fit mb-2")
                    qr_text_label = ui.label("Ожидание считывания кода при приближении к человеку...").classes(
                        "text-xs font-mono text-slate-300 whitespace-pre-line bg-slate-900/60 p-2.5 rounded-lg border border-slate-700/50 w-full"
                    )

        # 3. НИЖНИЙ БЛОК: ПРОТОКОЛ И ХРОНОЛОГИЯ СОБЫТИЙ (ВО ВСЮ ШИРИНУ)
        with ui.card().classes("w-full bg-slate-800/80 border border-slate-700 rounded-xl p-4 shadow-lg"):
            with ui.row().classes("w-full justify-between items-center mb-2"):
                with ui.row().classes("items-center gap-2"):
                    ui.icon("format_list_bulleted", size="1.4rem").classes("text-indigo-400")
                    ui.label("Протокол и хронология событий").classes("text-base font-semibold text-slate-200")

                # Кнопка скачивания протокола в JSON
                def handle_download_protocol():
                    json_data = sm.export_protocol_json()
                    saved_path = sm.save_protocol_to_disk()
                    ui.download(json_data.encode("utf-8"), filename=f"protocol_{int(time.time())}.json")
                    ui.notify(f"Протокол скачан и сохранен: {saved_path}", type="positive")

                ui.button("Скачать протокол (JSON)", on_click=handle_download_protocol, icon="download").classes(
                    "bg-slate-700 hover:bg-slate-600 text-xs text-slate-200"
                )

            # Терминал логов
            log_container = ui.column().classes(
                "w-full max-h-72 overflow-y-auto font-mono text-xs bg-slate-950 p-3 rounded-lg border border-slate-800 gap-1"
            )

    # ------------------------------------------------------------------------
    # РЕНДЕРИНГ ИНТЕРАКТИВНОЙ SVG КАРТЫ ПОЛИГОНА
    # ------------------------------------------------------------------------
    def render_arena_svg() -> str:
        svg_size = 460
        scale = svg_size / 4.0  # 115 px на метр

        svg_parts = [
            f'<svg width="{svg_size}" height="{svg_size}" viewBox="0 0 {svg_size} {svg_size}" xmlns="http://www.w3.org/2000/svg" class="rounded-lg shadow-inner">'
            f'<rect width="{svg_size}" height="{svg_size}" fill="#0f172a" stroke="#334155" stroke-width="3"/>'
        ]

        # 25 ячеек полигона 5x5
        cell_px = 0.8 * scale
        for r in range(5):
            for c in range(5):
                x = c * cell_px
                y = svg_size - (r + 1) * cell_px
                is_start = (c == 0 and r == 0)

                fill = "#1e293b" if not is_start else "#064e3b"
                stroke = "#334155"
                svg_parts.append(
                    f'<rect x="{x}" y="{y}" width="{cell_px}" height="{cell_px}" fill="{fill}" stroke="{stroke}" stroke-width="1"/>'
                    f'<text x="{x + 6}" y="{y + 16}" fill="#64748b" font-size="10" font-family="monospace">[{c},{r}]</text>'
                )

        # Стартовая ячейка [0, 0]
        start_y = svg_size - cell_px
        svg_parts.append(
            f'<text x="{cell_px/2}" y="{start_y + cell_px/2 + 4}" fill="#34d399" font-size="11" font-weight="bold" text-anchor="middle">ПУНКТ СБОРА</text>'
        )

        # Отрисовка ориентиров полигона
        for lm_id, wp in LANDMARK_WAYPOINTS.items():
            col, row = wp.cell
            center_x = (col + 0.5) * cell_px
            center_y = svg_size - (row + 0.5) * cell_px
            is_target = (sm.command_interpretation and sm.command_interpretation.target_landmark_id == lm_id)

            color = "#f59e0b" if not is_target else "#ef4444"
            radius = 16 if not is_target else 22

            svg_parts.append(
                f'<circle cx="{center_x}" cy="{center_y}" r="{radius}" fill="{color}" fill-opacity="0.3" stroke="{color}" stroke-width="2"/>'
                f'<circle cx="{center_x}" cy="{center_y}" r="4" fill="{color}"/>'
                f'<text x="{center_x}" y="{center_y + 24}" fill="{color}" font-size="9" font-weight="bold" text-anchor="middle">{wp.name}</text>'
            )

        # Траектория движения робота
        if len(sm.path_history) > 1:
            pts = []
            for px, py in sm.path_history:
                sx = px * scale
                sy = svg_size - py * scale
                pts.append(f"{sx:.1f},{sy:.1f}")
            path_str = " ".join(pts)
            svg_parts.append(
                f'<polyline points="{path_str}" fill="none" stroke="#38bdf8" stroke-width="2" stroke-dasharray="3,3" opacity="0.8"/>'
            )

        # Текущая цель (Waypoint)
        if sm.current_waypoint:
            gx = sm.current_waypoint.x * scale
            gy = svg_size - sm.current_waypoint.y * scale
            svg_parts.append(
                f'<line x1="{sm.robot_x * scale}" y1="{svg_size - sm.robot_y * scale}" x2="{gx}" y2="{gy}" stroke="#a855f7" stroke-width="2" stroke-dasharray="4,4"/>'
                f'<circle cx="{gx}" cy="{gy}" r="8" fill="none" stroke="#c084fc" stroke-width="2"/>'
            )

        # Робот: положение (X, Y) и стрелка ориентации (Yaw)
        rx = sm.robot_x * scale
        ry = svg_size - sm.robot_y * scale
        arrow_len = 18
        ax = rx + arrow_len * math.cos(sm.robot_yaw)
        ay = ry - arrow_len * math.sin(sm.robot_yaw)

        svg_parts.append(
            f'<circle cx="{rx}" cy="{ry}" r="14" fill="#0284c7" stroke="#38bdf8" stroke-width="2.5"/>'
            f'<line x1="{rx}" y1="{ry}" x2="{ax}" y2="{ay}" stroke="#f8fafc" stroke-width="3" stroke-linecap="round"/>'
            f'<circle cx="{ax}" cy="{ay}" r="3" fill="#38bdf8"/>'
        )

        svg_parts.append("</svg>")
        return "".join(svg_parts)

    # ------------------------------------------------------------------------
    # ПЕРИОДИЧЕСКИЙ ТАЙМЕР ОБНОВЛЕНИЯ ДАШБОРДА (10 Гц)
    # ------------------------------------------------------------------------
    last_rendered_log_count = 0

    def update_dashboard():
        nonlocal last_rendered_log_count

        # Шаг автомата состояний
        sm.step(dt=0.1)

        # 1. Бейдж состояния
        st = sm.state
        state_badge.text = st.value
        state_badge.classes(replace=STATE_COLORS.get(st, "bg-gray-700 text-white"))

        # 1b. Статус запуска бортового стека
        if sm.system_launcher.is_alive():
            pid = sm.system_launcher.process.pid if sm.system_launcher.process else "?"
            launch_status_badge.text = f"АКТИВЕН (PID {pid})"
            launch_status_badge.classes(replace="bg-emerald-600 text-white px-3 py-1 text-xs font-bold rounded uppercase")
        else:
            launch_status_badge.text = "ОСТАНОВЛЕН"
            launch_status_badge.classes(replace="bg-gray-600 text-white px-3 py-1 text-xs font-bold rounded uppercase")

        # 2. Координаты робота
        yaw_deg = int(math.degrees(sm.robot_yaw)) % 360
        coords_label.text = f"X: {sm.robot_x:.2f} м | Y: {sm.robot_y:.2f} м | Yaw: {yaw_deg}°"

        # 3. SVG карта
        map_html.content = render_arena_svg()

        # 4. Карточка LLM
        if sm.command_interpretation:
            lm_id = sm.command_interpretation.target_landmark_id
            lm_info = target_details(lm_id)
            landmark_name_label.text = f"Ориентир: {lm_info.get('name_ru', lm_id)} [{lm_id}]"
            strategy_label.text = f"Тактика: {sm.command_interpretation.search_strategy} (задержка: {sm.command_interpretation.latency_sec:.2f}с)"
            reasoning_label.text = f"Обоснование модели:\n{sm.command_interpretation.reasoning}"

        # 5. Карточка QR-кода
        if sm.qr_code_data:
            qr_status_badge.text = "QR-код успешно считан"
            qr_status_badge.classes(replace="bg-emerald-600 text-white text-xs w-fit mb-2 font-bold")
            qr_text_label.text = sm.qr_code_data
        else:
            qr_status_badge.text = "QR не считан"
            qr_status_badge.classes(replace="bg-gray-600 text-white text-xs w-fit mb-2")

        # 6. Добавление новых строк в судейский лог
        current_len = len(sm.logs)
        if current_len > last_rendered_log_count:
            new_entries = sm.logs[last_rendered_log_count:current_len]
            last_rendered_log_count = current_len

            with log_container:
                for entry in new_entries:
                    color_class = "text-slate-300"
                    if entry.category == "EMERGENCY":
                        color_class = "text-rose-400 font-bold"
                    elif entry.category == "WARN":
                        color_class = "text-yellow-400"
                    elif entry.category == "NAV":
                        color_class = "text-cyan-300"
                    elif entry.category == "LLM":
                        color_class = "text-blue-300 font-semibold"
                    elif entry.category == "VISION":
                        color_class = "text-emerald-300 font-semibold"
                    elif entry.category == "QR":
                        color_class = "text-sky-300 font-bold"
                    elif entry.category == "STATE":
                        color_class = "text-amber-300 font-semibold"

                    ui.label(f"[{entry.timestamp}] [{entry.category:8s}] {entry.message}").classes(color_class)

    ui.timer(0.1, update_dashboard)


# ============================================================================
# 5. ТОЧКА ВХОДА (MAIN)
# ============================================================================

def main(args=None):
    """Точка запуска Mission Orchestrator и Web Dashboard."""
    import argparse
    parser = argparse.ArgumentParser(description="IJKbot Mission State Machine & Judge Dashboard")
    parser.add_argument("--port", type=int, default=8080, help="Порт NiceGUI веб-сервера (по умолчанию 8080)")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Хост веб-сервера")
    parser.add_argument("--mock", action="store_true", default=True, help="Запуск в режиме симуляции (по умолчанию True)")
    parser.add_argument("--no-mock", dest="mock", action="store_false", help="Запуск с реальным ROS 2 железом")
    parser.add_argument("--headless", action="store_true", help="Запуск без Web GUI (только ROS 2)")

    clean_args = []
    if args is None:
        args = sys.argv[1:]
    skip_next = False
    for a in args:
        if skip_next:
            skip_next = False
            continue
        if a.startswith("--ros-args") or a.startswith("-r"):
            continue
        clean_args.append(a)

    parsed_args, _ = parser.parse_known_args(clean_args)

    print("=" * 70)
    print("IJKbot — Mission State Machine & Judge Web Dashboard (Этап 5)")
    print(f"Режим: {'СИМУЛЯЦИЯ (Mock)' if parsed_args.mock else 'ФИЗИЧЕСКОЕ ЖЕЛЕЗО (Hardware)'}")
    print(f"Веб-интерфейс: http://{parsed_args.host}:{parsed_args.port}")
    print("=" * 70)

    sm = MissionStateMachine(mock_mode=parsed_args.mock)

    if ROS2_AVAILABLE:
        ros_wrapper = MissionROSNode(sm)
        ros_wrapper.spin_in_background()

    if parsed_args.headless or not NICEGUI_AVAILABLE:
        print("[HEADLESS] Запуск в консольном режиме.")
        try:
            while True:
                sm.step(0.1)
                time.sleep(0.1)
        except KeyboardInterrupt:
            print("Остановка по сигналу.")
    else:
        build_judge_dashboard(sm)
        ui.run(
            host=parsed_args.host,
            port=parsed_args.port,
            title="IJKbot — Центр Управления Миссией",
            favicon="🤖",
            reload=False,
            show=False
        )


if __name__ in {"__main__", "__mp_main__"}:
    main()
