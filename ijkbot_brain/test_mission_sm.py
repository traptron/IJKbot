#!/usr/bin/env python3
"""
test_mission_sm.py — Модульные и интеграционные тесты для конечного автомата миссии
и протоколирования IJKbot (Этап 5).

Проверяет:
1. Начальное состояние автомата
2. Преобразование судейского задания LLM и назначение ориентира
3. Сквозной цикл миссии (все состояния автомата без баллов и таймера)
4. Выдержку 5-секундного регламентного удержания в ячейке пострадавшего
5. Считывание QR-кода и переход к эвакуации
6. Возврат в стартовую ячейку [0, 0] и завершение миссии
7. Логику аварийной остановки E-STOP и паузы
8. Формирование «Протокола и хронологии событий» и экспорт в JSON на диск
9. Корректность распознавания примера судейского задания
"""

import os
import unittest
import time
import json
from pathlib import Path

from ijkbot_brain.llm_client import CommandInterpretation, LandmarkID
from ijkbot_brain.mission_sm import (
    MissionState,
    MissionStateMachine,
    Waypoint,
    LANDMARK_WAYPOINTS,
    START_WAYPOINT,
    DEFAULT_TASK_EXAMPLE,
    STATIC_ARENA_CELLS
)


class DummyLLMClient:
    """Мок LLM клиента для детерминированных тестов."""
    def __init__(self, target_id: str = "smoke_tower"):
        self.target_id = target_id

    def interpret(self, text: str, use_fallback: bool = True, on_token=None) -> CommandInterpretation:
        # Для проверки примера судейского задания с автомобильным затором
        if "затор" in text.lower() or "автомобил" in text.lower():
            target = "car_jam"
        else:
            target = self.target_id

        return CommandInterpretation(
            target_landmark_id=target,
            search_strategy="scan_adjacent_cells",
            reasoning=f"Тестовое обнаружение ориентира {target}",
            confidence=0.99,
            source="mock_llm",
            latency_sec=0.1
        )


class TestMissionStateMachine(unittest.TestCase):
    def test_real_search_requires_detection(self):
        sm = MissionStateMachine(llm_client=DummyLLMClient(), mock_mode=False)
        sm.state = MissionState.SEARCHING_VICTIM
        sm.step(10.0)
        self.assertEqual(sm.state, MissionState.SEARCHING_VICTIM)
        self.assertFalse(sm.victim_found)

    def test_qr_callback_accepts_only_reading_state_and_preserves_text(self):
        from types import SimpleNamespace
        from ijkbot_brain.mission_sm import MissionROSNode
        wrapper = SimpleNamespace(sm=self.sm)
        message = SimpleNamespace(data='  Состояние: стабильно\n')
        MissionROSNode._qr_callback(wrapper, message)
        self.assertIsNone(self.sm.qr_code_data)
        self.assertEqual(self.sm.latest_qr_text, message.data)
        self.assertIsNotNone(self.sm.latest_qr_received_at)
        self.assertFalse(self.sm.qr_scanned)
        self.sm.state = MissionState.READING_QR
        MissionROSNode._qr_callback(wrapper, message)
        self.assertEqual(self.sm.qr_code_data, message.data)

    def test_qr_dashboard_ignores_blank_and_deduplicates_log(self):
        from types import SimpleNamespace
        from ijkbot_brain.mission_sm import MissionROSNode
        wrapper = SimpleNamespace(sm=self.sm)
        self.sm.state = MissionState.WAIT_5_SECONDS
        message = SimpleNamespace(data='  QR <b>текст</b>\nстрока 2  ')
        MissionROSNode._qr_callback(wrapper, message)
        count = len(self.sm.logs)
        MissionROSNode._qr_callback(wrapper, message)
        MissionROSNode._qr_callback(wrapper, SimpleNamespace(data='  \n'))
        self.assertEqual(len(self.sm.logs), count)
        self.assertEqual(self.sm.latest_qr_text, message.data)
        self.assertEqual(self.sm.state, MissionState.WAIT_5_SECONDS)
        self.assertIsNone(self.sm.qr_code_data)
        self.sm.reset_mission()
        self.assertIsNone(self.sm.latest_qr_text)


    def setUp(self):
        self.mock_llm = DummyLLMClient("smoke_tower")
        self.sm = MissionStateMachine(llm_client=self.mock_llm, mock_mode=True)

    def test_initial_state_and_defaults(self):
        """Проверка инициализации автомата в состоянии PREPARATION."""
        self.assertEqual(self.sm.state, MissionState.PREPARATION)
        self.assertEqual(self.sm.robot_x, 0.4)
        self.assertEqual(self.sm.robot_y, 0.4)
        self.assertFalse(self.sm.llm_parsed)
        self.assertFalse(self.sm.victim_found)
        self.assertFalse(self.sm.qr_scanned)
        self.assertFalse(self.sm.evacuated_home)
        self.assertGreater(len(self.sm.logs), 0)

    def test_llm_parsing_and_waypoint(self):
        """Проверка работы LLM и назначения путевой точки."""
        self.sm.set_task_description("Пострадавший у здания Стакан с задымлением")
        interp = self.sm.parse_task_with_llm()

        self.assertEqual(self.sm.state, MissionState.READY_TO_START)
        self.assertTrue(self.sm.llm_parsed)
        self.assertEqual(interp.target_landmark_id, "smoke_tower")
        self.assertIsNotNone(self.sm.current_waypoint)
        self.assertEqual(self.sm.current_waypoint.x, LANDMARK_WAYPOINTS["smoke_tower"].x)

    def test_user_example_task_parsing(self):
        """Проверка разбора регламентного примера судейского задания."""
        self.sm.set_task_description(DEFAULT_TASK_EXAMPLE)
        interp = self.sm.parse_task_with_llm()

        self.assertEqual(interp.target_landmark_id, "car_jam")
        self.assertEqual(self.sm.current_waypoint.x, LANDMARK_WAYPOINTS["car_jam"].x)

    def test_estop_and_resume(self):
        """Проверка аварийной остановки E-STOP и возобновления."""
        self.sm.set_task_description("Тест")
        self.sm.start_mission()
        self.assertEqual(self.sm.state, MissionState.NAVIGATING_TO_LANDMARK)

        # Активация E-STOP
        self.sm.trigger_emergency_stop()
        self.assertEqual(self.sm.state, MissionState.EMERGENCY_STOP)

        # Сброс E-STOP
        self.sm.reset_emergency_stop()
        self.assertEqual(self.sm.state, MissionState.NAVIGATING_TO_LANDMARK)

    def test_pause_and_resume(self):
        """Проверка паузы и продолжения миссии."""
        self.sm.set_task_description("Тест")
        self.sm.start_mission()
        self.assertEqual(self.sm.state, MissionState.NAVIGATING_TO_LANDMARK)

        # Пауза
        self.sm.toggle_pause()
        self.assertEqual(self.sm.state, MissionState.PAUSED)

        # Возобновление
        self.sm.toggle_pause()
        self.assertEqual(self.sm.state, MissionState.NAVIGATING_TO_LANDMARK)

    def test_full_mission_cycle(self):
        """
        Сквозной тест полного цикла миссии:
        1. Ввод задания и распознавание LLM
        2. Старт и движение к первой целевой ячейке
        3. Круговой пошаговый осмотр (30° / 1.0с) и считывание QR-кода
        4. Регламентное 5-секундное удержание в ячейке пострадавшего
        5. Автоматическая эвакуация в стартовую ячейку [0.4, 0.4]
        6. Успешное завершение миссии и сохранение протокола.
        """
        self.sm.wait_duration_required = 0.1

        # 1. Задание и LLM
        self.sm.set_task_description("Пострадавший у здания Стакан")
        self.sm.start_mission()
        self.assertEqual(self.sm.state, MissionState.NAVIGATING_TO_LANDMARK)
        self.assertTrue(self.sm.llm_parsed)

        # 2. Достижение первой целевой ячейки
        self.sm.robot_x = self.sm.current_waypoint.x
        self.sm.robot_y = self.sm.current_waypoint.y
        self.sm.robot_yaw = self.sm.current_waypoint.yaw
        self.sm.step(0.1)
        self.assertEqual(self.sm.state, MissionState.SEARCHING_VICTIM)

        # 3. Круговой осмотр ячейки (12x30°). При обнаружении QR -> переход в WAIT_5_SECONDS
        self.sm.qr_code_data = "ПОСТРАДАВШИЙ #1\nСостояние: Средней тяжести"
        self.sm.step(0.1)
        self.assertEqual(self.sm.state, MissionState.WAIT_5_SECONDS)
        self.assertTrue(self.sm.victim_found)
        self.assertTrue(self.sm.qr_scanned)
        self.assertIsNotNone(self.sm.wait_timer_start)

        # 4. Ожидание регламентного времени (0.1 сек в тесте) -> возврат домой
        time.sleep(0.15)
        self.sm.step(0.1)
        self.assertEqual(self.sm.state, MissionState.RETURNING_HOME)
        self.assertEqual(self.sm.current_waypoint, START_WAYPOINT)

        # 5. Прибытие на старт [0.4, 0.4] -> MISSION_COMPLETE
        self.sm.robot_x = START_WAYPOINT.x
        self.sm.robot_y = START_WAYPOINT.y
        self.sm.robot_yaw = START_WAYPOINT.yaw
        self.sm.step(0.1)
        self.assertEqual(self.sm.state, MissionState.MISSION_COMPLETE)
        self.assertTrue(self.sm.evacuated_home)
        self.assertIsNotNone(self.sm.mission_end_time)

    def test_multi_waypoint_search_progression(self):
        """Проверка последовательного обхода нескольких ячеек при отсутствии QR."""
        self.sm.set_task_description("Пострадавший у здания Стакан")
        self.sm.parse_task_with_llm()
        self.sm.waypoints_queue = [
            Waypoint(x=1.2, y=1.2, name="Cell 1"),
            Waypoint(x=2.0, y=1.2, name="Cell 2"),
        ]
        self.sm.start_mission()
        self.assertEqual(self.sm.current_waypoint_idx, 0)
        self.assertEqual(self.sm.current_waypoint.name, "Cell 1")

        # Прибытие в первую ячейку
        self.sm.robot_x = 1.2
        self.sm.robot_y = 1.2
        self.sm.step(0.1)
        self.assertEqual(self.sm.state, MissionState.SEARCHING_VICTIM)

        # Завершение всех 12 шагов осмотра без QR
        self.sm.spin_step = 11
        self.sm.spin_phase = "CHECK"
        self.sm.qr_code_data = None
        self.sm.step(0.1)

        # Робот должен перейти к следующей ячейке Cell 2
        self.assertEqual(self.sm.state, MissionState.NAVIGATING_TO_LANDMARK)
        self.assertEqual(self.sm.current_waypoint_idx, 1)
        self.assertEqual(self.sm.current_waypoint.name, "Cell 2")

        # Прибытие во вторую ячейку и завершение 12 шагов без QR
        self.sm.robot_x = 2.0
        self.sm.robot_y = 1.2
        self.sm.step(0.1)
        self.assertEqual(self.sm.state, MissionState.SEARCHING_VICTIM)
        self.sm.spin_step = 11
        self.sm.spin_phase = "CHECK"
        self.sm.qr_code_data = None
        self.sm.step(0.1)

        # Все точки исчерпаны -> автоматический возврат домой
        self.assertEqual(self.sm.state, MissionState.RETURNING_HOME)
        self.assertEqual(self.sm.current_waypoint, START_WAYPOINT)

    def test_spin_and_scan_phases(self):
        """Проверка фаз ROTATE (30°) -> PAUSE (1.0с) -> CHECK."""
        self.sm.state = MissionState.SEARCHING_VICTIM
        self.sm.spin_step = 0
        self.sm.spin_phase = "ROTATE"
        self.sm.spin_timer = 0.0
        self.sm.spin_start_yaw = 0.0
        self.sm.robot_yaw = 0.0

        # Поворот на 30 градусов (0.50 рад)
        self.sm.robot_yaw = 0.52
        self.sm.step(0.1)
        self.assertEqual(self.sm.spin_phase, "PAUSE")
        self.assertEqual(self.sm.spin_timer, 0.0)

        # Пауза стабилизации 1.0 сек
        self.sm.step(0.5)
        self.assertEqual(self.sm.spin_phase, "PAUSE")
        self.sm.step(0.6)
        self.assertEqual(self.sm.spin_phase, "CHECK")

    def test_mission_watchdog_timeout(self):
        """Проверка сторожевого таймера 250 сек (возврат домой при остатке < 50 сек)."""
        self.sm.state = MissionState.SEARCHING_VICTIM
        self.sm.robot_x = 2.0
        self.sm.robot_y = 2.0
        self.sm.mission_start_time = time.time() - 251.0
        self.sm.step(0.1)
        self.assertEqual(self.sm.state, MissionState.RETURNING_HOME)
        self.assertEqual(self.sm.current_waypoint, START_WAYPOINT)

    def test_protocol_export_and_disk_save(self):
        """Проверка формирования протокола и сохранения на диск."""
        self.sm.set_task_description("Эвакуация пострадавшего у моста")
        self.sm.parse_task_with_llm()

        protocol = self.sm.export_protocol_dict()
        self.assertEqual(protocol["document"], "Протокол и хронология событий миссии IJKbot")
        self.assertIn("competition", protocol)
        self.assertIn("chronology", protocol)
        self.assertGreater(len(protocol["chronology"]), 0)

        # Проверка валидности JSON строки
        json_str = self.sm.export_protocol_json()
        parsed = json.loads(json_str)
        self.assertIn("execution_status", parsed)

        # Проверка сохранения на диск
        saved_file = self.sm.save_protocol_to_disk()
        self.assertIsNotNone(saved_file)
        self.assertTrue(Path(saved_file).exists())

    def test_real_mode_waits_for_qr_node_result(self):
        """Реальная миссия не может подменять отсутствие QR фиктивным текстом."""
        real_sm = MissionStateMachine(llm_client=self.mock_llm, mock_mode=False)
        real_sm.state = MissionState.READING_QR

        real_sm.step(0.1)
        self.assertEqual(real_sm.state, MissionState.READING_QR)
        self.assertFalse(real_sm.qr_scanned)

        real_sm.qr_code_data = 'Состояние: стабильное'
        real_sm.step(0.1)
        self.assertEqual(real_sm.state, MissionState.RETURNING_HOME)
        self.assertTrue(real_sm.qr_scanned)

    def test_static_arena_elements(self):
        """Проверка неизменности и наличия всех обязательных статичных элементов арены."""
        expected_static_cells = {
            (0, 0): "start",
            (1, 1): "parking",
            (1, 2): "yellow_building",
            (1, 3): "yellow_building",
            (3, 1): "blue_building",
            (3, 3): "river",
            (3, 4): "bridge",
            (4, 3): "bridge",
        }
        for cell, elem_type in expected_static_cells.items():
            self.assertIn(cell, STATIC_ARENA_CELLS, f"Ячейка {cell} отсутствует в STATIC_ARENA_CELLS")
            self.assertEqual(STATIC_ARENA_CELLS[cell]["type"], elem_type)

        # Проверка описания ячейки 1:1
        p11 = STATIC_ARENA_CELLS[(1, 1)]
        self.assertEqual(p11["title"], "ОСТАНОВКА")
        self.assertEqual(p11["subtitle"], "Парковка")
        self.assertIn("Обломки", p11["detail"])

    def test_llm_tokens_captured(self):
        """Проверка фиксации сгенерированных токенов от LLM в конечном автомате."""
        self.sm.set_task_description("Пострадавший возле моста")
        interp = self.sm.parse_task_with_llm()

        self.assertIsNotNone(interp.raw_text)
        self.assertGreater(len(self.sm.streaming_tokens), 0)
        self.assertEqual(self.sm.streaming_tokens, interp.raw_text)


if __name__ == "__main__":
    unittest.main()
