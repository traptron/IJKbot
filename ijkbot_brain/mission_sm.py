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
from typing import Dict, Any, Optional, List, Tuple, Callable
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

# Статичные элементы арены (по регламенту: 0:0, 1:1, 1:2, 1:3, 3:2, 3:3, 3:4, 4:3)
STATIC_ARENA_CELLS: Dict[Tuple[int, int], Dict[str, Any]] = {
    (0, 0): {
        "title": "СТАРТ",
        "subtitle": "Пункт сбора",
        "fill": "#064e3b",
        "stroke": "#10b981",
        "text_color": "#34d399",
        "type": "start",
    },
    (1, 1): {
        "title": "ОСТАНОВКА",
        "subtitle": "Парковка",
        "detail": "Обломки жёлтого зд.",
        "fill": "#78350f",
        "stroke": "#f59e0b",
        "text_color": "#fbbf24",
        "type": "parking",
    },
    (1, 2): {
        "title": "ЖЁЛТОЕ ЗДАНИЕ",
        "subtitle": "Секция 1 (1:2)",
        "fill": "#854d0e",
        "stroke": "#eab308",
        "text_color": "#fef08a",
        "type": "yellow_building",
    },
    (1, 3): {
        "title": "ЖЁЛТОЕ ЗДАНИЕ",
        "subtitle": "Секция 2 (1:3)",
        "fill": "#854d0e",
        "stroke": "#eab308",
        "text_color": "#fef08a",
        "type": "yellow_building",
    },
    (3, 1): {
        "title": "СИНЕЕ ЗДАНИЕ",
        "subtitle": "Капитальный макет (3:1)",
        "fill": "#1e3a8a",
        "stroke": "#3b82f6",
        "text_color": "#93c5fd",
        "type": "blue_building",
    },
    (3, 3): {
        "title": "РЕКА",
        "subtitle": "Водная преграда",
        "fill": "#075985",
        "stroke": "#0284c7",
        "text_color": "#38bdf8",
        "type": "river",
    },
    (3, 4): {
        "title": "МОСТ ЧЕРЕЗ РЕКУ",
        "subtitle": "Северный переход (3:4)",
        "fill": "#3f3f46",
        "stroke": "#a1a1aa",
        "text_color": "#f4f4f5",
        "type": "bridge",
    },
    (4, 3): {
        "title": "МОСТ ЧЕРЕЗ РЕКУ",
        "subtitle": "Восточный переход (4:3)",
        "fill": "#3f3f46",
        "stroke": "#a1a1aa",
        "text_color": "#f4f4f5",
        "type": "bridge",
    },
}

LANDMARK_WAYPOINTS: Dict[str, Waypoint] = {
    LandmarkID.SMOKE_TOWER.value: Waypoint(
        x=0.4, y=2.8, yaw=0.0, cell=(0, 3), name="Здание «Стакан»"
    ),
    LandmarkID.PANEL_HOUSE.value: Waypoint(
        x=2.0, y=2.8, yaw=3.141593, cell=(2, 3), name="Панельный дом"
    ),
    LandmarkID.BRIDGES.value: Waypoint(
        x=2.8, y=3.6, yaw=0.0, cell=(3, 4), name="Мосты через реку"
    ),
    LandmarkID.TANKER_TRUCK.value: Waypoint(
        x=2.0, y=1.2, yaw=0.0, cell=(2, 1), name="Аварийный бензовоз"
    ),
    LandmarkID.FALLEN_TREE.value: Waypoint(
        x=1.2, y=0.4, yaw=math.pi / 2, cell=(1, 0), name="Упавшее дерево"
    ),
    LandmarkID.CAR_JAM.value: Waypoint(
        x=2.8, y=0.4, yaw=math.pi / 2, cell=(3, 0), name="Транспортный затор"
    ),
    LandmarkID.DEBRIS_PVC.value: Waypoint(
        x=0.4, y=1.2, yaw=0.0, cell=(0, 1), name="Завал из ПВХ"
    ),
    # Статичные элементы арены
    "blue_building": Waypoint(
        x=2.0, y=1.2, yaw=0.0, cell=(2, 1), name="Синее здание"
    ),
    "yellow_building": Waypoint(
        x=2.0, y=2.0, yaw=math.pi, cell=(2, 2), name="Жёлтое здание"
    ),
    "parking": Waypoint(
        x=0.4, y=1.2, yaw=0.0, cell=(0, 1), name="Остановка / парковка"
    ),
    "river": Waypoint(
        x=2.0, y=2.8, yaw=0.0, cell=(2, 3), name="Река"
    ),
    "start": Waypoint(
        x=0.4, y=0.4, yaw=0.0, cell=(0, 0), name="Пункт сбора (Старт)"
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

        # Токены LLM (стриминг и сохранение всех токенов)
        self.llm_raw_tokens: str = ""
        self.llm_token_count: int = 0
        self.llm_is_generating: bool = False

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

        # Очередь целевых ячеек поиска (до 4 точек по регламенту)
        self.waypoints_queue: List[Waypoint] = []
        self.current_waypoint_idx: int = 0

        # Состояние кругового пошагового осмотра ячейки (12 шагов по 30 градусов = 360°)
        self.spin_step: int = 0  # 0..11
        self.spin_phase: str = "ROTATE"  # "ROTATE", "PAUSE", "CHECK"
        self.spin_timer: float = 0.0
        self.spin_start_yaw: float = 0.0

        # Состояние зрения и QR-кода
        self.victim_detected: bool = False
        self.qr_code_data: Optional[str] = None
        self.latest_qr_text: Optional[str] = None
        self.latest_qr_received_at: Optional[str] = None

        # Состояние стриминга токенов LLM
        self.streaming_tokens: str = ""
        self.is_streaming: bool = False

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
    def set_llm_config(self, host: str, model: Optional[str] = None) -> bool:
        """Динамическое изменение адреса хоста и модели Ollama (например с другого ПК в сети)."""
        with self.lock:
            h = host.strip()
            if not h.startswith("http://") and not h.startswith("https://"):
                h = f"http://{h}"
            self.llm_client.host = h.rstrip("/")
            if model and model.strip():
                self.llm_client.model = model.strip()
            is_ok = self.llm_client.is_available()
            self._log("LLM", f"Настройки Ollama обновлены: {self.llm_client.host} (модель: {self.llm_client.model}). Связь: {'OK' if is_ok else 'НЕТ СВЯЗИ'}")
            return is_ok

    def set_task_description(self, task_text: str) -> None:
        with self.lock:
            self.current_task_text = task_text.strip()
            self._log("LLM", f"Задано задание от судей: «{self.current_task_text}»")

    def parse_task_with_llm(self, on_token: Optional[Callable[[str], None]] = None) -> CommandInterpretation:
        """
        Запуск анализа задания моделью Qwen 2.5 7B.
        """
        with self.lock:
            if not self.current_task_text:
                raise ValueError("Текст задания судей не может быть пустым")

            self.previous_state = self.state
            self.state = MissionState.LLM_PARSING
            self.command_interpretation = None
            self.llm_parsed = False
            self.is_streaming = True
            self.streaming_tokens = "Инициализация Qwen 2.5 7B и получение токенов...\n"
            self._log("LLM", "Запуск инференса языковой модели Qwen 2.5 7B...")

        first_token = [True]
        def _token_handler(token: str):
            with self.lock:
                if first_token[0]:
                    self.streaming_tokens = token
                    first_token[0] = False
                else:
                    self.streaming_tokens += token
            if on_token:
                try:
                    on_token(token)
                except Exception:
                    pass

        try:
            try:
                interp = self.llm_client.interpret(self.current_task_text, on_token=_token_handler)
            except TypeError:
                interp = self.llm_client.interpret(self.current_task_text)
            if interp.nav2_goal is not None:
                from ijkbot_brain.llm_client import load_arena, validate_nav2_goal
                arena = getattr(self.llm_client, 'arena', None) or load_arena()
                goal = validate_nav2_goal(interp.nav2_goal, interp.target_landmark_id, arena)
                waypoint = Waypoint(
                    x=goal['x'], y=goal['y'], yaw=goal['yaw'],
                    cell=(int(goal['x'] / 0.8), int(goal['y'] / 0.8)),
                    name=interp.target_landmark_id)
            else:
                waypoint = LANDMARK_WAYPOINTS.get(interp.target_landmark_id, START_WAYPOINT)
                interp.nav2_goal = {
                    "frame_id": "map",
                    "x": waypoint.x,
                    "y": waypoint.y,
                    "yaw": waypoint.yaw
                }
        except Exception as e:
            with self.lock:
                self.is_streaming = False
                self.state = MissionState.PREPARATION
                self._log("ERROR", f"Сбой обработки LLM: {str(e)}")
            raise e
        finally:
            with self.lock:
                self.is_streaming = False

        with self.lock:
            if not getattr(interp, "raw_text", None):
                interp.raw_text = json.dumps(interp.to_dict(), ensure_ascii=False, indent=2)
                interp.token_count = len(interp.raw_text.split())
            if not self.streaming_tokens or self.streaming_tokens.startswith("Инициализация"):
                self.streaming_tokens = interp.raw_text
            else:
                self.streaming_tokens = interp.raw_text or self.streaming_tokens
            self.command_interpretation = interp
            self.llm_parsed = True
            lm_id = interp.target_landmark_id
            lm_info = target_details(lm_id)
            lm_name = lm_info.get("name_ru", lm_id)

            self._log(
                "LLM",
                f"Задание успешно распознано ({interp.source}, задержка: {interp.latency_sec:.2f}с, токенов: {interp.token_count}). "
                f"Целевой ориентир: «{lm_name}» [{lm_id}], тактика: {interp.search_strategy}"
            )
            self._log("LLM", f"Обоснование модели: {interp.reasoning}")
            if interp.nav2_goal:
                self._log("LLM", f"Сформирован nav2_goal: X={interp.nav2_goal['x']:.2f}м, Y={interp.nav2_goal['y']:.2f}м, Yaw={interp.nav2_goal['yaw']:.2f}")

            # Формирование очереди целевых ячеек поиска (до 4 точек по регламенту)
            self.waypoints_queue = []
            if getattr(interp, "target_waypoints", None):
                for i, wp_dict in enumerate(interp.target_waypoints[:4]):
                    wx = float(wp_dict.get("x", 0.4))
                    wy = float(wp_dict.get("y", 0.4))
                    wyaw = float(wp_dict.get("yaw", 0.0))
                    cx = int(wx / ARENA_CELL_SIZE)
                    cy = int(wy / ARENA_CELL_SIZE)
                    self.waypoints_queue.append(
                        Waypoint(
                            x=wx,
                            y=wy,
                            yaw=wyaw,
                            cell=(cx, cy),
                            name=f"{interp.target_landmark_id}_{i+1} [{cx}:{cy}]"
                        )
                    )

            if not self.waypoints_queue:
                self.waypoints_queue = [waypoint]

            self.current_waypoint_idx = 0
            self.current_waypoint = self.waypoints_queue[0]
            self.spin_step = 0
            self.spin_phase = "ROTATE"
            self.spin_timer = 0.0
            self.spin_start_yaw = self.robot_yaw
            self.state = MissionState.READY_TO_START
            self._log("LLM", f"Сформирована очередь из {len(self.waypoints_queue)} точек поиска для обхода.")
            return interp

    def publish_nav2_goal(self) -> bool:
        """Передача текущей цели nav2_goal в ROS 2 стек Nav2 (/goal_pose)."""
        with self.lock:
            if not self.current_waypoint:
                self._log("WARN", "Целевая путевая точка еще не определена. Сначала выполните анализ задания LLM.")
                return False

            self._publish_goal_pose(self.current_waypoint)
            yaw_deg = int(math.degrees(self.current_waypoint.yaw)) % 360
            total_wp = len(self.waypoints_queue) if self.waypoints_queue else 1
            self._log(
                "NAV",
                f"Цель nav2_goal [{self.current_waypoint_idx + 1}/{total_wp}] передана в Nav2 (/goal_pose): "
                f"X={self.current_waypoint.x:.2f}м, Y={self.current_waypoint.y:.2f}м, Yaw={yaw_deg}°"
            )
            return True

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
            self.current_waypoint_idx = 0
            self.spin_step = 0
            self.spin_phase = "ROTATE"
            self.spin_timer = 0.0
            self.spin_start_yaw = self.robot_yaw

            if self.waypoints_queue:
                self.current_waypoint = self.waypoints_queue[0]

            self.state = MissionState.NAVIGATING_TO_LANDMARK
            total_wp = len(self.waypoints_queue) if self.waypoints_queue else 1
            self._log("STATE", f"СТАРТ МИССИИ! Движение к точке [1/{total_wp}]: {self.current_waypoint.name}")

            # Публикация цели Nav2 в ROS 2
            self._publish_goal_pose(self.current_waypoint)

    def trigger_emergency_stop(self) -> None:
        """Аварийная остановка робота (E-STOP)."""
        with self.lock:
            self.previous_state = self.state
            self.state = MissionState.EMERGENCY_STOP
            self._publish_zero_velocity()
            self._log("EMERGENCY", "ВНИМАНИЕ: АКТИВИРОВАН E-STOP! Движение мгновенно остановлено.")

    def reset_emergency_stop(self) -> None:
        """Сброс аварийной остановки."""
        with self.lock:
            if self.state == MissionState.EMERGENCY_STOP:
                self.state = self.previous_state or MissionState.PREPARATION
                self._log("SYS", f"E-STOP сброшен. Возврат в состояние: {self.state}")

    def toggle_pause(self) -> None:
        """Пауза / возобновление миссии."""
        with self.lock:
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
            self.waypoints_queue = []
            self.current_waypoint_idx = 0
            self.spin_step = 0
            self.spin_phase = "ROTATE"
            self.spin_timer = 0.0
            self.spin_start_yaw = 0.0
            self.victim_detected = False
            self.qr_code_data = None
            self.latest_qr_text = None
            self.latest_qr_received_at = None
            self._publish_zero_velocity()
            self._log("SYS", "Сброс миссии выполнен. Все состояния и координаты возвращены в исходное положение.")

    # ------------------------------------------------------------------------
    # Внутренний цикл автомата (вызывается с шагом dt)
    # ------------------------------------------------------------------------
    def step(self, dt: float = 0.1) -> None:
        with self.lock:
            # 0. Проверка лимита времени (5 минут = 300 сек). При t >= 250 сек (< 50 сек до конца) — автовозврат на базу
            elapsed = self.get_elapsed_mission_sec()
            if elapsed >= 250.0 and self.state not in [
                MissionState.PREPARATION,
                MissionState.READY_TO_START,
                MissionState.RETURNING_HOME,
                MissionState.MISSION_COMPLETE,
                MissionState.EMERGENCY_STOP,
                MissionState.PAUSED,
            ]:
                self._log("WARN", f"ТАЙМАУТ МИССИИ ({elapsed:.1f}с / 300с)! До конца осталось менее 50с. Экстренный возврат на базу [0.4, 0.4]!")
                self.current_waypoint = START_WAYPOINT
                self.state = MissionState.RETURNING_HOME
                self._publish_goal_pose(START_WAYPOINT)

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
                    total_wp = len(self.waypoints_queue) if self.waypoints_queue else 1
                    self._log(
                        "NAV",
                        f"Робот прибыл в ячейку [{self.current_waypoint_idx + 1}/{total_wp}] «{self.current_waypoint.name}». "
                        f"Начало кругового сканирования (12 шагов по 30° с паузой 1.0с)..."
                    )
                    self.state = MissionState.SEARCHING_VICTIM
                    self.spin_step = 0
                    self.spin_phase = "ROTATE"
                    self.spin_timer = 0.0
                    self.spin_start_yaw = self.robot_yaw
                    self._publish_zero_velocity()

            elif self.state == MissionState.SEARCHING_VICTIM:
                self._handle_spin_and_scan(dt)

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
                        self._log("STATE", f"Регламентная 5-секундная фиксация выполнена ({wait_elapsed:.1f}с). Начало эвакуации в стартовую ячейку [0.4, 0.4]...")
                        self.current_waypoint = START_WAYPOINT
                        self.state = MissionState.RETURNING_HOME
                        self._publish_goal_pose(START_WAYPOINT)

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
    def _handle_spin_and_scan(self, dt: float) -> None:
        """
        Круговой пошаговый осмотр ячейки:
        12 дискретных шагов по 30 градусов (12 * 30° = 360°).
        Каждый шаг:
          1. ROTATE: поворот на месте на 30° со скоростью 0.4 рад/с.
          2. PAUSE: полная остановка на 1.0 сек для стабилизации камеры RealSense D435.
          3. CHECK: проверка считывания QR-кода.
             - Если QR считан: переход в WAIT_5_SECONDS.
             - Если нет: следующий шаг (spin_step += 1).
        Если все 12 шагов завершены без QR: переход к следующей ячейке из waypoints_queue.
        Если все ячейки исчерпаны: возврат на базу [0.4, 0.4].
        """
        TURN_SPEED = 0.4  # рад/с
        total_wp = len(self.waypoints_queue) if self.waypoints_queue else 1

        # Проверка: если в любой момент во время сканирования пришел QR-код
        if self.qr_code_data and not self.qr_scanned:
            self.victim_detected = True
            self.victim_found = True
            self.qr_scanned = True
            self._log(
                "QR",
                f"QR-код успешно считан в ячейке [{self.current_waypoint_idx + 1}/{total_wp}] "
                f"(шаг {self.spin_step + 1}/12):\n{self.qr_code_data}"
            )
            self.state = MissionState.WAIT_5_SECONDS
            self.wait_timer_start = time.time()
            self._publish_zero_velocity()
            self._log("STATE", "Фиксация в ячейке на 5 секунд по регламенту...")
            return

        if self.spin_phase == "ROTATE":
            self.spin_timer += dt
            if self.mock_mode:
                self.robot_yaw = (self.robot_yaw + TURN_SPEED * dt) % (2 * math.pi)
            else:
                if self.ros_node:
                    self.ros_node.send_cmd_vel(0.0, TURN_SPEED)

            yaw_diff = abs((self.robot_yaw - self.spin_start_yaw + math.pi) % (2 * math.pi) - math.pi)

            # 30 градусов = ~0.5236 рад. Поворот завершен по углу (>= 0.50 рад) или по таймауту (1.5с)
            if yaw_diff >= 0.50 or self.spin_timer >= 1.5:
                self._publish_zero_velocity()
                self.spin_phase = "PAUSE"
                self.spin_timer = 0.0
                deg_turned = (self.spin_step + 1) * 30
                self._log(
                    "VISION",
                    f"Ячейка [{self.current_waypoint_idx + 1}/{total_wp}], "
                    f"шаг {self.spin_step + 1}/12 ({deg_turned}°): поворот 30° завершен. Стабилизация камеры 1.0с..."
                )

        elif self.spin_phase == "PAUSE":
            self._publish_zero_velocity()
            self.spin_timer += dt
            if self.spin_timer >= 1.0:
                self.spin_phase = "CHECK"
                self.spin_timer = 0.0

        elif self.spin_phase == "CHECK":
            self._publish_zero_velocity()

            # В mock-режиме имитируем чтение QR на 4-м шаге первой ячейки
            if self.mock_mode and not self.qr_code_data:
                if self.current_waypoint_idx == 0 and self.spin_step == 3:
                    self.qr_code_data = (
                        "ПОСТРАДАВШИЙ #1\n"
                        "ФИО: Иванов И.И.\n"
                        "Состояние: Средней тяжести\n"
                        "Пульс: 74 уд/мин, SpO2: 96%\n"
                        "Травма: Перелом голени, сознание сохранено"
                    )

            if self.qr_code_data and not self.qr_scanned:
                self.victim_detected = True
                self.victim_found = True
                self.qr_scanned = True
                self._log(
                    "QR",
                    f"QR-код успешно считан в ячейке [{self.current_waypoint_idx + 1}/{total_wp}] "
                    f"(шаг {self.spin_step + 1}/12):\n{self.qr_code_data}"
                )
                self.state = MissionState.WAIT_5_SECONDS
                self.wait_timer_start = time.time()
                self._publish_zero_velocity()
                self._log("STATE", "Фиксация в ячейке на 5 секунд по регламенту...")
                return

            # QR не обнаружен — переход к следующему шагу осмотра
            self.spin_step += 1
            if self.spin_step >= 12:
                self._log(
                    "VISION",
                    f"В ячейке [{self.current_waypoint_idx + 1}/{total_wp}] "
                    f"({self.current_waypoint.name}) QR-код не обнаружен за полный оборот 360°."
                )
                if self.current_waypoint_idx + 1 < len(self.waypoints_queue):
                    self.current_waypoint_idx += 1
                    self.current_waypoint = self.waypoints_queue[self.current_waypoint_idx]
                    self.state = MissionState.NAVIGATING_TO_LANDMARK
                    self._log(
                        "NAV",
                        f"Переход к следующей ячейке поиска [{self.current_waypoint_idx + 1}/{total_wp}]: "
                        f"{self.current_waypoint.name} (X={self.current_waypoint.x:.2f}м, Y={self.current_waypoint.y:.2f}м)..."
                    )
                    self._publish_goal_pose(self.current_waypoint)
                else:
                    self._log("NAV", "Все ячейки проверены, QR-код не найден. Возврат на базу в стартовую ячейку [0.4, 0.4]...")
                    self.current_waypoint = START_WAYPOINT
                    self.state = MissionState.RETURNING_HOME
                    self._publish_goal_pose(START_WAYPOINT)
            else:
                self.spin_phase = "ROTATE"
                self.spin_start_yaw = self.robot_yaw
                self.spin_timer = 0.0

    def _handle_victim_search(self, dt: float) -> None:
        """Совместимость — делегирует в _handle_spin_and_scan."""
        self._handle_spin_and_scan(dt)

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
        if self.ros_node and ROS2_AVAILABLE:
            try:
                self.ros_node.send_nav_goal(wp.x, wp.y, wp.yaw)
            except Exception as e:
                self._log("WARN", f"Ошибка отправки цели в Nav2: {e}")

    def _publish_zero_velocity(self) -> None:
        if self.ros_node and ROS2_AVAILABLE:
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
                "latest_qr_text": self.latest_qr_text,
                "latest_qr_received_at": self.latest_qr_received_at,
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
                self.cmd_vel_pub = self.node.create_publisher(Twist, "/cmd_vel", 10)
                self.node.declare_parameter('goal_topic', '/goal_pose')
                self.goal_pub = self.node.create_publisher(
                    PoseStamped, self.node.get_parameter('goal_topic').value, 10)
                self.state_pub = self.node.create_publisher(RosString, "/mission/state", 10)

                # Подписки на сенсоры и топики
                self.node.create_subscription(Odometry, "/odom", self._odom_callback, 10)
                self.node.create_subscription(RosString, "/victim_status", self._qr_callback, 10)
                self.node.create_subscription(RosBool, "/victim_detected", self._victim_detected_callback, 10)
                self.node.create_subscription(RosBool, "/vision/qr/detected", self._qr_detected_callback, 10)
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

    def _qr_detected_callback(self, msg: Any) -> None:
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
                self.sm.publish_nav2_goal()
            except Exception as e:
                self.sm._log("ERROR", f"Ошибка обработки топика /mission/judge_task: {e}")

    def _qr_callback(self, msg: Any) -> None:
        with self.sm.lock:
            if not msg.data.strip():
                return
            if msg.data != self.sm.latest_qr_text:
                self.sm._log('QR', f'Получен текст QR:\n{msg.data}')
            self.sm.latest_qr_text = msg.data
            self.sm.latest_qr_received_at = self.sm._now_str()
            if self.sm.state in [MissionState.SEARCHING_VICTIM, MissionState.READING_QR]:
                self.sm.qr_code_data = msg.data
                if not self.sm.qr_scanned and self.sm.state == MissionState.SEARCHING_VICTIM:
                    self.sm.victim_detected = True
                    self.sm.victim_found = True
                    self.sm.qr_scanned = True
                    self.sm._log("QR", f"Получены данные QR-кода из топика /victim_status:\n{msg.data.strip()}")
                    self.sm.state = MissionState.WAIT_5_SECONDS
                    self.sm.wait_timer_start = time.time()
                    self.sm._publish_zero_velocity()
                    self.sm._log("STATE", "Фиксация в ячейке на 5 секунд по регламенту...")

    def _estop_callback(self, msg: Any) -> None:
        if msg.data:
            self.sm.trigger_emergency_stop()

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
            mission_timer_badge = ui.badge("ТАЙМЕР: 00:00 / 05:00").classes("px-3 py-1.5 text-xs font-mono font-bold rounded bg-slate-700 text-slate-300")
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

                    # 1. Шаг 1: Распознать задание (со стримингом токенов)
                    def handle_llm_parse():
                        text = task_input.value or ""
                        if not text.strip():
                            ui.notify("Пожалуйста, введите текст задания!", type="warning")
                            return
                        sm.set_task_description(text)
                        llm_parse_btn.props("loading")
                        sm.streaming_tokens = "Инициализация Qwen 2.5 7B и получение токенов...\n"
                        first_chunk = [True]

                        def on_token_cb(token: str):
                            if first_chunk[0]:
                                sm.streaming_tokens = token
                                first_chunk[0] = False
                            else:
                                sm.streaming_tokens += token

                        def _worker():
                            try:
                                interp = sm.parse_task_with_llm(on_token=on_token_cb)
                                ui.notify(
                                    f"Задание успешно распознано ({interp.source}, токенов: {interp.token_count})!",
                                    type="positive"
                                )
                                # Автоматически передаем полученную цель в Nav2
                                sm.publish_nav2_goal()
                            except Exception as ex:
                                ui.notify(f"Ошибка LLM: {ex}", type="negative")
                            finally:
                                llm_parse_btn.props(remove="loading")

                        threading.Thread(target=_worker, daemon=True).start()

                    llm_parse_btn = ui.button("Распознать (LLM)", on_click=handle_llm_parse, icon="psychology").classes(
                        "bg-blue-600 hover:bg-blue-500 font-semibold px-4"
                    )

                    # Кнопка прямой передачи nav2_goal
                    def handle_send_goal_direct():
                        if sm.command_interpretation and sm.current_waypoint:
                            if sm.publish_nav2_goal():
                                ui.notify(
                                    f"Цель nav2_goal передана в Nav2 (/goal_pose): X={sm.current_waypoint.x:.2f}м, Y={sm.current_waypoint.y:.2f}м",
                                    type="positive"
                                )
                            else:
                                ui.notify("Ошибка публикации цели в топик /goal_pose", type="negative")
                        else:
                            ui.notify("Целевая точка nav2_goal еще не определена. Нажмите «Распознать (LLM)»!", type="warning")

                    ui.button("Передать nav2_goal", on_click=handle_send_goal_direct, icon="send").classes(
                        "bg-purple-700 hover:bg-purple-600 text-purple-100 font-semibold px-3"
                    )

                    # 2. Шаг 2: СТАРТ МИССИИ
                    def handle_start():
                        sm.set_task_description(task_input.value or "")
                        sm.start_mission()
                        sm.publish_nav2_goal()
                        ui.notify("Миссия запущена! nav2_goal передан в стек навигации.", type="info")

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

                    # Статичные элементы арены (легенда)
                    with ui.row().classes("w-full justify-center gap-2 text-[11px] text-slate-300 pt-2 border-t border-slate-700/60 flex-wrap"):
                        ui.html('<span class="inline-flex items-center gap-1"><span class="w-2.5 h-2.5 rounded bg-emerald-700 border border-emerald-400 inline-block"></span> 0:0 Старт</span>')
                        ui.html('<span class="inline-flex items-center gap-1"><span class="w-2.5 h-2.5 rounded bg-amber-800 border border-amber-400 inline-block"></span> 1:1 Остановка/Парковка/Обломки</span>')
                        ui.html('<span class="inline-flex items-center gap-1"><span class="w-2.5 h-2.5 rounded bg-yellow-800 border border-yellow-400 inline-block"></span> 1:2, 1:3 Жёлтое зд.</span>')
                        ui.html('<span class="inline-flex items-center gap-1"><span class="w-2.5 h-2.5 rounded bg-blue-900 border border-blue-400 inline-block"></span> 3:2 Синее зд.</span>')
                        ui.html('<span class="inline-flex items-center gap-1"><span class="w-2.5 h-2.5 rounded bg-sky-900 border border-sky-400 inline-block"></span> 3:3 Река</span>')
                        ui.html('<span class="inline-flex items-center gap-1"><span class="w-2.5 h-2.5 rounded bg-zinc-700 border border-zinc-400 inline-block"></span> 3:4, 4:3 Мосты</span>')

            # ПРАВАЯ КОЛОНКА: КАРТОЧКА LLM И КАРТОЧКА QR-КОДА
            with ui.column().classes("w-5/12 gap-4"):

                # Карточка анализа LLM
                with ui.card().classes("w-full bg-slate-800/90 border border-slate-700 rounded-xl p-4 shadow-lg flex flex-col gap-2.5"):
                    with ui.row().classes("w-full justify-between items-center mb-1"):
                        with ui.row().classes("items-center gap-2"):
                            ui.icon("psychology", size="1.4rem").classes("text-blue-400")
                            ui.label("Результат анализа LLM (Qwen 2.5 7B)").classes("text-base font-semibold text-slate-100")
                        llm_tokens_badge = ui.badge("0 токенов", color="slate-700").classes("text-xs font-mono px-2 py-0.5 rounded")

                    # 0. Настройки подключения к Ollama (на другом ПК / ноутбуке)
                    with ui.row().classes("w-full items-center justify-between gap-2 bg-slate-950/70 p-2 rounded-lg border border-slate-700/60"):
                        with ui.row().classes("items-center gap-2 flex-grow"):
                            ui.icon("lan", size="1.2rem").classes("text-blue-400")
                            llm_host_input = ui.input(
                                label="Хост Ollama (IP другого ПК)",
                                value=sm.llm_client.host,
                                placeholder="http://192.168.1.20:11434"
                            ).props("dense").classes("text-xs w-52 font-mono")
                            llm_model_input = ui.input(
                                label="Модель",
                                value=sm.llm_client.model,
                                placeholder="qwen2.5:7b"
                            ).props("dense").classes("text-xs w-32 font-mono")

                        def check_llm_connection():
                            h = llm_host_input.value or "http://localhost:11434"
                            m = llm_model_input.value or "qwen2.5:7b"
                            ok = sm.set_llm_config(h, m)
                            if ok:
                                llm_conn_badge.text = "СВЯЗЬ: OK"
                                llm_conn_badge.classes(replace="text-[10px] font-mono px-2 py-0.5 rounded bg-emerald-600 text-white font-bold")
                                ui.notify(f"Связь с Ollama установлена ({sm.llm_client.host})!", type="positive")
                            else:
                                llm_conn_badge.text = "НЕТ СВЯЗИ"
                                llm_conn_badge.classes(replace="text-[10px] font-mono px-2 py-0.5 rounded bg-rose-600 text-white font-bold")
                                ui.notify(f"Не удалось подключиться к Ollama на {sm.llm_client.host}. Убедитесь, что на том ПК запущен 'OLLAMA_HOST=0.0.0.0:11434 ollama serve'!", type="negative")

                        with ui.row().classes("items-center gap-1"):
                            llm_conn_badge = ui.badge("ПРОВЕРИТЬ", color="slate-700").classes("text-[10px] font-mono px-2 py-0.5 rounded")
                            ui.button("Ping", on_click=check_llm_connection, icon="sync").props("dense flat").classes("text-xs text-blue-300 hover:bg-blue-900/40")

                    # 1. Ориентир и тактика
                    with ui.row().classes("w-full items-center justify-between gap-2 bg-slate-900/80 p-2 rounded-lg border border-slate-700/60"):
                        landmark_name_label = ui.label("Ориентир: ожидание задания").classes("text-sm font-bold text-blue-300")
                        strategy_label = ui.label("Тактика: —").classes("text-xs font-mono text-slate-400")

                    # 2. Целевая точка Nav2 (nav2_goal из JSON)
                    with ui.column().classes("w-full bg-slate-950/80 p-2.5 rounded-lg border border-purple-800/50 gap-1.5"):
                        with ui.row().classes("w-full items-center justify-between"):
                            with ui.row().classes("items-center gap-1.5"):
                                ui.icon("explore", size="1.1rem").classes("text-purple-400")
                                ui.label("Целевая точка Nav2 (nav2_goal из JSON):").classes("text-xs font-bold text-purple-300 uppercase tracking-wider")
                            nav2_goal_status = ui.badge("Не задана", color="gray-700").classes("text-xs")
                        nav2_goal_coords_label = ui.label("frame_id: — | X: — | Y: — | Yaw: —").classes("text-xs font-mono text-slate-300")

                    # 2b. Очередь ячеек поиска (до 4 точек по регламенту)
                    with ui.column().classes("w-full bg-slate-950/80 p-2.5 rounded-lg border border-indigo-800/50 gap-1.5"):
                        with ui.row().classes("w-full items-center justify-between"):
                            with ui.row().classes("items-center gap-1.5"):
                                ui.icon("alt_route", size="1.1rem").classes("text-indigo-400")
                                ui.label("Очередь ячеек поиска (до 4 точек):").classes("text-xs font-bold text-indigo-300 uppercase tracking-wider")
                            waypoints_queue_badge = ui.badge("0/0", color="gray-700").classes("text-xs")
                        waypoints_list_label = ui.label("Маршрут не сформирован").classes("text-xs font-mono text-slate-300 whitespace-pre-wrap")

                    # 3. Обоснование модели
                    with ui.column().classes("w-full gap-1"):
                        ui.label("Обоснование модели:").classes("text-xs font-semibold text-slate-400")
                        reasoning_label = ui.label("Введите текст судейского задания и нажмите «Распознать (LLM)»").classes(
                            "text-xs text-slate-200 italic bg-slate-900/60 p-2 rounded-lg border border-slate-700/50 w-full"
                        )

                    # 4. ВСЕ ТОКЕНЫ ОТ LLM
                    with ui.column().classes("w-full gap-1"):
                        with ui.row().classes("w-full items-center justify-between"):
                            with ui.row().classes("items-center gap-1.5"):
                                ui.icon("terminal", size="1.1rem").classes("text-emerald-400")
                                ui.label("Все сгенерированные токены от LLM (JSON):").classes("text-xs font-bold text-emerald-400")
                            ui.label("Qwen 2.5 7B [Raw Tokens]").classes("text-[10px] font-mono text-slate-500")

                        tokens_display = ui.code("Ожидание запуска генерации...", language="json").classes(
                            "w-full max-h-48 overflow-y-auto font-mono text-xs bg-slate-950 p-2 rounded-lg border border-slate-800 text-emerald-300 select-all"
                        )

                # Карточка кругового осмотра ячейки (12x30°) и удержания
                with ui.card().classes("w-full bg-slate-800/80 border border-slate-700 rounded-xl p-4 shadow-lg"):
                    with ui.row().classes("w-full justify-between items-center mb-1"):
                        with ui.row().classes("items-center gap-2"):
                            ui.icon("radar", size="1.4rem").classes("text-amber-400")
                            ui.label("Круговой осмотр ячейки (12×30°)").classes("text-base font-semibold text-slate-200")
                        scan_step_badge = ui.badge("НЕАКТИВЕН", color="gray-700").classes("text-xs")
                    scan_info_label = ui.label("Осмотр запускается при прибытии в целевую ячейку").classes("text-xs font-mono text-slate-300")
                    hold_timer_label = ui.label("Удержание в ячейке: —").classes("text-xs font-mono text-cyan-300")

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
            f'<svg width="{svg_size}" height="{svg_size}" viewBox="0 0 {svg_size} {svg_size}" xmlns="http://www.w3.org/2000/svg" class="rounded-lg shadow-inner select-none">'
            f'<rect width="{svg_size}" height="{svg_size}" fill="#0f172a" stroke="#334155" stroke-width="3"/>'
        ]

        # 25 ячеек полигона 5x5 (статичные объекты и координатная сетка)
        cell_px = 0.8 * scale
        for r in range(5):
            for c in range(5):
                x = c * cell_px
                y = svg_size - (r + 1) * cell_px
                coord_key = (c, r)

                if coord_key in STATIC_ARENA_CELLS:
                    st = STATIC_ARENA_CELLS[coord_key]
                    fill = st["fill"]
                    stroke = st["stroke"]
                    text_col = st["text_color"]

                    svg_parts.append(
                        f'<rect x="{x}" y="{y}" width="{cell_px}" height="{cell_px}" fill="{fill}" stroke="{stroke}" stroke-width="2"/>'
                    )

                    # Стилизованные графические элементы
                    if st["type"] == "river":
                        # Волна реки
                        w_y1 = y + cell_px * 0.38
                        w_y2 = y + cell_px * 0.68
                        svg_parts.append(
                            f'<path d="M {x+10} {w_y1} Q {x+cell_px*0.3} {w_y1-6}, {x+cell_px*0.5} {w_y1} T {x+cell_px-10} {w_y1}" fill="none" stroke="#38bdf8" stroke-width="2.5" opacity="0.9"/>'
                            f'<path d="M {x+10} {w_y2} Q {x+cell_px*0.3} {w_y2-6}, {x+cell_px*0.5} {w_y2} T {x+cell_px-10} {w_y2}" fill="none" stroke="#38bdf8" stroke-width="2.5" opacity="0.9"/>'
                        )
                    elif st["type"] == "bridge":
                        # Ограждения и настил моста
                        svg_parts.append(
                            f'<line x1="{x+6}" y1="{y+6}" x2="{x+cell_px-6}" y2="{y+6}" stroke="#facc15" stroke-dasharray="4,3" stroke-width="2.5"/>'
                            f'<line x1="{x+6}" y1="{y+cell_px-6}" x2="{x+cell_px-6}" y2="{y+cell_px-6}" stroke="#facc15" stroke-dasharray="4,3" stroke-width="2.5"/>'
                        )
                    elif st["type"] == "yellow_building":
                        # Контуры окон желтого здания
                        for ox in [x + 14, x + cell_px - 26]:
                            for oy in [y + 14, y + cell_px - 22]:
                                svg_parts.append(f'<rect x="{ox}" y="{oy}" width="12" height="9" fill="#fef08a" opacity="0.35" rx="1.5"/>')
                    elif st["type"] == "blue_building":
                        # Контуры окон синего здания
                        for ox in [x + 14, x + cell_px - 26]:
                            for oy in [y + 14, y + cell_px - 22]:
                                svg_parts.append(f'<rect x="{ox}" y="{oy}" width="12" height="9" fill="#93c5fd" opacity="0.4" rx="1.5"/>')
                    elif st["type"] == "parking":
                        # Разметка парковки и символические обломки
                        svg_parts.append(
                            f'<line x1="{x+10}" y1="{y+14}" x2="{x+10}" y2="{y+cell_px-14}" stroke="#f59e0b" stroke-dasharray="3,2" stroke-width="2"/>'
                            f'<line x1="{x+22}" y1="{y+14}" x2="{x+22}" y2="{y+cell_px-14}" stroke="#f59e0b" stroke-dasharray="3,2" stroke-width="2"/>'
                        )
                    elif st["type"] == "start":
                        # Мишень старта
                        cx = x + cell_px / 2
                        cy = y + cell_px / 2
                        svg_parts.append(
                            f'<circle cx="{cx}" cy="{cy}" r="22" fill="none" stroke="#10b981" stroke-width="1.5" stroke-dasharray="4,3"/>'
                        )

                    # Метка координат ячейки [c,r]
                    svg_parts.append(
                        f'<text x="{x + 6}" y="{y + 14}" fill="#cbd5e1" font-size="9" font-weight="bold" font-family="monospace">[{c}:{r}]</text>'
                    )

                    # Текстовые подписи объекта
                    cx = x + cell_px / 2
                    cy = y + cell_px / 2
                    svg_parts.append(
                        f'<text x="{cx}" y="{cy - 2}" fill="{text_col}" font-size="9" font-weight="bold" font-family="sans-serif" text-anchor="middle">{st["title"]}</text>'
                        f'<text x="{cx}" y="{cy + 12}" fill="{text_col}" font-size="7.5" font-family="sans-serif" text-anchor="middle" opacity="0.95">{st["subtitle"]}</text>'
                    )
                else:
                    # Обычная проходимая ячейка полигона
                    fill = "#1e293b"
                    stroke = "#334155"
                    svg_parts.append(
                        f'<rect x="{x}" y="{y}" width="{cell_px}" height="{cell_px}" fill="{fill}" stroke="{stroke}" stroke-width="1"/>'
                        f'<text x="{x + 6}" y="{y + 14}" fill="#64748b" font-size="9" font-family="monospace">[{c}:{r}]</text>'
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

        # Очередь целевых точек Nav2 (до 4 точек)
        for idx, wp in enumerate(sm.waypoints_queue):
            gx = wp.x * scale
            gy = svg_size - wp.y * scale
            is_active = (idx == sm.current_waypoint_idx) and (sm.state != MissionState.RETURNING_HOME)

            if is_active:
                rx = sm.robot_x * scale
                ry = svg_size - sm.robot_y * scale
                svg_parts.append(
                    f'<line x1="{rx}" y1="{ry}" x2="{gx}" y2="{gy}" stroke="#c084fc" stroke-width="2" stroke-dasharray="5,4"/>'
                    f'<circle cx="{gx}" cy="{gy}" r="15" fill="#9333ea" fill-opacity="0.35" stroke="#c084fc" stroke-width="2.5"/>'
                    f'<circle cx="{gx}" cy="{gy}" r="4" fill="#f3e8ff"/>'
                    f'<text x="{gx}" y="{gy - 18}" fill="#f3e8ff" font-size="9" font-weight="bold" font-family="monospace" text-anchor="middle">[{idx+1}/{len(sm.waypoints_queue)}] {wp.x:.2f},{wp.y:.2f}</text>'
                )
            else:
                svg_parts.append(
                    f'<circle cx="{gx}" cy="{gy}" r="11" fill="#312e81" fill-opacity="0.5" stroke="#818cf8" stroke-width="1.5" stroke-dasharray="3,2"/>'
                    f'<text x="{gx}" y="{gy + 3}" fill="#c7d2fe" font-size="8" font-weight="bold" font-family="monospace" text-anchor="middle">{idx+1}</text>'
                )

        if not sm.waypoints_queue and sm.current_waypoint:
            gx = sm.current_waypoint.x * scale
            gy = svg_size - sm.current_waypoint.y * scale
            rx = sm.robot_x * scale
            ry = svg_size - sm.robot_y * scale
            svg_parts.append(
                f'<line x1="{rx}" y1="{ry}" x2="{gx}" y2="{gy}" stroke="#c084fc" stroke-width="2" stroke-dasharray="5,4"/>'
                f'<circle cx="{gx}" cy="{gy}" r="14" fill="#9333ea" fill-opacity="0.3" stroke="#c084fc" stroke-width="2.5"/>'
                f'<circle cx="{gx}" cy="{gy}" r="3.5" fill="#f3e8ff"/>'
                f'<text x="{gx}" y="{gy - 17}" fill="#f3e8ff" font-size="9" font-weight="bold" font-family="monospace" text-anchor="middle">nav2_goal [{sm.current_waypoint.x:.2f},{sm.current_waypoint.y:.2f}]</text>'
            )

        # Линия возврата на базу при эвакуации
        if sm.state == MissionState.RETURNING_HOME:
            hx = START_WAYPOINT.x * scale
            hy = svg_size - START_WAYPOINT.y * scale
            rx = sm.robot_x * scale
            ry = svg_size - sm.robot_y * scale
            svg_parts.append(
                f'<line x1="{rx}" y1="{ry}" x2="{hx}" y2="{hy}" stroke="#10b981" stroke-width="2.5" stroke-dasharray="4,3"/>'
                f'<circle cx="{hx}" cy="{hy}" r="14" fill="#059669" fill-opacity="0.3" stroke="#10b981" stroke-width="2"/>'
                f'<text x="{hx}" y="{hy - 18}" fill="#34d399" font-size="9" font-weight="bold" font-family="monospace" text-anchor="middle">БАЗА (Эвакуация)</text>'
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

        # 1c. Таймер миссии (5 минут = 300 сек)
        elapsed_sec = sm.get_elapsed_mission_sec()
        mins = int(elapsed_sec // 60)
        secs = int(elapsed_sec % 60)
        rem_sec = max(0, 300 - int(elapsed_sec))
        rem_m = rem_sec // 60
        rem_s = rem_sec % 60

        if sm.mission_start_time is not None and sm.mission_end_time is None:
            if rem_sec < 50:
                mission_timer_badge.text = f"ТАЙМЕР: {mins:02d}:{secs:02d} (Осталось {rem_m:02d}:{rem_s:02d}!)"
                mission_timer_badge.classes(replace="px-3 py-1.5 text-xs font-mono font-bold rounded bg-rose-600 text-white animate-pulse")
            else:
                mission_timer_badge.text = f"ТАЙМЕР: {mins:02d}:{secs:02d} (Осталось {rem_m:02d}:{rem_s:02d})"
                mission_timer_badge.classes(replace="px-3 py-1.5 text-xs font-mono font-bold rounded bg-indigo-600 text-white")
        elif sm.mission_end_time is not None:
            mission_timer_badge.text = f"ИТОГ: {mins:02d}:{secs:02d}"
            mission_timer_badge.classes(replace="px-3 py-1.5 text-xs font-mono font-bold rounded bg-emerald-600 text-white")
        else:
            mission_timer_badge.text = "ТАЙМЕР: 00:00 / 05:00"
            mission_timer_badge.classes(replace="px-3 py-1.5 text-xs font-mono font-bold rounded bg-slate-700 text-slate-300")

        # 2. Координаты робота
        yaw_deg = int(math.degrees(sm.robot_yaw)) % 360
        coords_label.text = f"X: {sm.robot_x:.2f} м | Y: {sm.robot_y:.2f} м | Yaw: {yaw_deg}°"

        # 3. SVG карта
        map_html.content = render_arena_svg()

        # 4. Карточка LLM
        if sm.is_streaming:
            tokens_display.content = sm.streaming_tokens
            llm_tokens_badge.text = "Генерация..."
        elif sm.command_interpretation:
            lm_id = sm.command_interpretation.target_landmark_id
            lm_info = target_details(lm_id)
            landmark_name_label.text = f"Ориентир: {lm_info.get('name_ru', lm_id)} [{lm_id}]"
            strategy_label.text = f"Тактика: {sm.command_interpretation.search_strategy} (задержка: {sm.command_interpretation.latency_sec:.2f}с | {sm.command_interpretation.token_count} токенов)"
            reasoning_label.text = f"{sm.command_interpretation.reasoning}"

            # Данные nav2_goal из JSON
            goal = sm.command_interpretation.nav2_goal
            if goal:
                yaw_deg = int(math.degrees(goal.get('yaw', 0.0))) % 360
                nav2_goal_coords_label.text = f"frame_id: {goal.get('frame_id','map')} | X: {goal.get('x',0.0):.2f} м | Y: {goal.get('y',0.0):.2f} м | Yaw: {yaw_deg}°"
                nav2_goal_status.text = "АКТИВНА"
                nav2_goal_status.classes(replace="text-xs bg-purple-700 text-purple-100 font-bold")
            else:
                nav2_goal_coords_label.text = "nav2_goal: null (не определена на карте)"
                nav2_goal_status.text = "NULL"
                nav2_goal_status.classes(replace="text-xs bg-slate-800 text-slate-400")

            # Очередь ячеек поиска (до 4 точек)
            if sm.waypoints_queue:
                waypoints_queue_badge.text = f"Точка {sm.current_waypoint_idx + 1} из {len(sm.waypoints_queue)}"
                waypoints_queue_badge.classes(replace="text-xs bg-indigo-700 text-indigo-100 font-bold")
                lines = []
                for idx, wp in enumerate(sm.waypoints_queue):
                    marker = "▶ " if idx == sm.current_waypoint_idx else "  "
                    lines.append(f"{marker}[{idx+1}] ({wp.x:.2f}, {wp.y:.2f}) {wp.name}")
                waypoints_list_label.text = "\n".join(lines)
            else:
                waypoints_queue_badge.text = "0/0"
                waypoints_list_label.text = "Маршрут не сформирован"

            # Все токены от LLM
            if sm.command_interpretation.raw_text:
                tokens_display.content = sm.command_interpretation.raw_text
                llm_tokens_badge.text = f"{sm.command_interpretation.token_count} токенов"

        # 4b. Карточка кругового осмотра ячейки (12×30°) и удержания
        if sm.state == MissionState.SEARCHING_VICTIM:
            phase_ru = {"ROTATE": "Поворот 30°", "PAUSE": "Стабилизация 1.0с", "CHECK": "Анализ QR"}.get(sm.spin_phase, sm.spin_phase)
            deg = (sm.spin_step + 1) * 30
            scan_step_badge.text = f"ШАГ {sm.spin_step + 1}/12 ({deg}°)"
            scan_step_badge.classes(replace="text-xs bg-amber-600 text-black font-bold animate-pulse")
            scan_info_label.text = f"Фаза: {phase_ru} | Время фазы: {sm.spin_timer:.1f}с"
        elif sm.state == MissionState.WAIT_5_SECONDS:
            wait_el = (time.time() - sm.wait_timer_start) if sm.wait_timer_start else 0.0
            scan_step_badge.text = f"ФИКСАЦИЯ 5с ({min(5.0, wait_el):.1f}/5.0с)"
            scan_step_badge.classes(replace="text-xs bg-cyan-600 text-white font-bold animate-pulse")
            scan_info_label.text = "QR обнаружен! Остановка на 5 секунд по регламенту"
        else:
            scan_step_badge.text = "НЕАКТИВЕН"
            scan_step_badge.classes(replace="text-xs bg-gray-700 text-slate-400")
            scan_info_label.text = "Осмотр запускается при прибытии в целевую ячейку"

        if sm.wait_timer_start is not None and sm.state == MissionState.WAIT_5_SECONDS:
            wait_el = time.time() - sm.wait_timer_start
            hold_timer_label.text = f"Удержание: {wait_el:.1f} / 5.0 с {'(ГОТОВО)' if wait_el >= 5.0 else ''}"
        else:
            hold_timer_label.text = "Удержание в ячейке: —"

        # 5. Карточка QR-кода
        if sm.latest_qr_text:
            qr_status_badge.text = f"QR получен: {sm.latest_qr_received_at}"
            qr_status_badge.classes(replace="bg-emerald-600 text-white text-xs w-fit mb-2 font-bold")
            qr_text_label.text = sm.latest_qr_text
        elif sm.mock_mode and sm.qr_code_data:
            qr_status_badge.text = "QR: симуляция"
            qr_status_badge.classes(replace="bg-amber-600 text-white text-xs w-fit mb-2")
            qr_text_label.text = sm.qr_code_data
        elif sm.qr_code_data:
            qr_status_badge.text = "QR-код успешно считан"
            qr_status_badge.classes(replace="bg-emerald-600 text-white text-xs w-fit mb-2 font-bold")
            qr_text_label.text = sm.qr_code_data
        else:
            qr_status_badge.text = "QR не считан"
            qr_status_badge.classes(replace="bg-gray-600 text-white text-xs w-fit mb-2")
            qr_text_label.text = "Ожидание подтверждённого QR-кода с камеры..."

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
    parser.add_argument("--llm-host", type=str, default=os.environ.get("OLLAMA_HOST", "http://192.168.1.20:11434"), help="URL хоста Ollama (например http://192.168.1.20:11434)")
    parser.add_argument("--llm-model", type=str, default=os.environ.get("OLLAMA_MODEL", "qwen2.5:7b"), help="Имя модели Ollama")
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
    print(f"Ollama Хост: {parsed_args.llm_host} | Модель: {parsed_args.llm_model}")
    print(f"Веб-интерфейс: http://{parsed_args.host}:{parsed_args.port}")
    print("=" * 70)

    llm_client = LLMClient(host=parsed_args.llm_host, model=parsed_args.llm_model)
    sm = MissionStateMachine(llm_client=llm_client, mock_mode=parsed_args.mock)

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
        @ui.page('/')
        def index():
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
