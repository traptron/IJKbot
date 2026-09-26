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

import unittest
import time
import json
import math
from pathlib import Path

from brain.llm_client import CommandInterpretation
from brain.mission_sm import (
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
        from brain.mission_sm import MissionROSNode
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
        from brain.mission_sm import MissionROSNode
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

    def test_qr_image_callback_stores_bytes_and_b64(self):
        import base64
        from types import SimpleNamespace
        from brain.mission_sm import MissionROSNode
        wrapper = SimpleNamespace(sm=self.sm)
        dummy_jpeg = b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00'
        message = SimpleNamespace(data=dummy_jpeg)
        MissionROSNode._qr_image_callback(wrapper, message)
        self.assertEqual(self.sm.latest_qr_image_bytes, dummy_jpeg)
        expected_b64 = base64.b64encode(dummy_jpeg).decode('ascii')
        self.assertEqual(self.sm.latest_qr_image_b64, expected_b64)
        # Empty message data should be ignored
        MissionROSNode._qr_image_callback(wrapper, SimpleNamespace(data=b''))
        self.assertEqual(self.sm.latest_qr_image_bytes, dummy_jpeg)
        # Reset clears image
        self.sm.reset_mission()
        self.assertIsNone(self.sm.latest_qr_image_bytes)
        self.assertIsNone(self.sm.latest_qr_image_b64)


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
        self.assertIn("ОБЛОМКИ ЖЁЛТОГО ЗДАНИЯ", p11["detail"])
        self.assertIn("yellow_building_debris", LANDMARK_WAYPOINTS)
        self.assertEqual(LANDMARK_WAYPOINTS["yellow_building_debris"].cell, (0, 1))

    def test_llm_tokens_captured(self):
        """Проверка фиксации сгенерированных токенов от LLM в конечном автомате."""
        self.sm.set_task_description("Пострадавший возле моста")
        interp = self.sm.parse_task_with_llm()

        self.assertIsNotNone(interp.raw_text)
        self.assertGreater(len(self.sm.streaming_tokens), 0)
        self.assertEqual(self.sm.streaming_tokens, interp.raw_text)

    def test_odom_callback_updates_repeatedly_d28(self):
        """Проверка устранения D28: _odom_callback обновляет координаты на каждом вызове."""
        from types import SimpleNamespace
        from brain.mission_sm import MissionROSNode

        wrapper = SimpleNamespace(sm=self.sm, update_pose_from_tf=lambda: False)
        self.sm.mock_mode = False
        self.sm.path_history = [(0.4, 0.4)]

        # Первая одометрия
        msg1 = SimpleNamespace(
            pose=SimpleNamespace(
                pose=SimpleNamespace(
                    position=SimpleNamespace(x=0.1, y=0.2),
                    orientation=SimpleNamespace(x=0.0, y=0.0, z=0.0, w=1.0)
                )
            )
        )
        MissionROSNode._odom_callback(wrapper, msg1)
        # При fallback к координатам добавляется initial_x=0.4, initial_y=0.4
        self.assertAlmostEqual(self.sm.robot_x, 0.5)
        self.assertAlmostEqual(self.sm.robot_y, 0.6)

        # Вторая одометрия (раньше блокировалась условием if not self.sm.path_history)
        msg2 = SimpleNamespace(
            pose=SimpleNamespace(
                pose=SimpleNamespace(
                    position=SimpleNamespace(x=0.3, y=0.4),
                    orientation=SimpleNamespace(x=0.0, y=0.0, z=0.0, w=1.0)
                )
            )
        )
        MissionROSNode._odom_callback(wrapper, msg2)
        self.assertAlmostEqual(self.sm.robot_x, 0.7)
        self.assertAlmostEqual(self.sm.robot_y, 0.8)

    def test_tf2_pose_lookup_and_fallback_d02(self):
        """Проверка устранения D02: привязка позы в фрейме map через TF2 и fallback."""
        from types import SimpleNamespace
        from brain.mission_sm import MissionROSNode

        # 1. Тест успешного TF2 lookup
        mock_transform = SimpleNamespace(
            transform=SimpleNamespace(
                translation=SimpleNamespace(x=1.23, y=2.34),
                rotation=SimpleNamespace(x=0.0, y=0.0, z=0.7071, w=0.7071)
            )
        )
        mock_tf_buffer = SimpleNamespace(
            lookup_transform=lambda target, source, time: mock_transform
        )
        wrapper = SimpleNamespace(
            sm=self.sm,
            node=SimpleNamespace(),
            tf_buffer=mock_tf_buffer
        )
        self.sm.mock_mode = False
        res = MissionROSNode.update_pose_from_tf(wrapper)
        self.assertTrue(res)
        self.assertAlmostEqual(self.sm.robot_x, 1.23)
        self.assertAlmostEqual(self.sm.robot_y, 2.34)
        self.assertAlmostEqual(self.sm.robot_yaw, math.pi / 2.0, places=3)

        # 2. Тест fallback при исключении TF2
        def throw_tf_err(target, source, time):
            raise RuntimeError("No TF")

        failing_tf_buffer = SimpleNamespace(lookup_transform=throw_tf_err)
        wrapper_failing = SimpleNamespace(
            sm=self.sm,
            node=SimpleNamespace(),
            tf_buffer=failing_tf_buffer,
            update_pose_from_tf=lambda: False
        )
        odom_msg = SimpleNamespace(
            pose=SimpleNamespace(
                pose=SimpleNamespace(
                    position=SimpleNamespace(x=0.0, y=0.0),
                    orientation=SimpleNamespace(x=0.0, y=0.0, z=0.0, w=1.0)
                )
            )
        )
        MissionROSNode._odom_callback(wrapper_failing, odom_msg)
        # Стартовый одом (0, 0) с учетом initial_x=0.4, initial_y=0.4 дает (0.4, 0.4) на карте
        self.assertAlmostEqual(self.sm.robot_x, 0.4)
        self.assertAlmostEqual(self.sm.robot_y, 0.4)

    def test_nav2_action_client_and_cancellation_d24(self):
        """Проверка D24: ActionClient NavigateToPose и явная отмена цели при смене фаз."""
        from types import SimpleNamespace
        from brain.mission_sm import MissionROSNode

        cancelled_goals = []
        sent_goals = []

        class MockGoalHandle:
            def cancel_goal_async(self):
                cancelled_goals.append(True)

        class MockActionClient:
            def send_goal_async(self, goal):
                sent_goals.append(goal)
                future = SimpleNamespace(
                    result=lambda: SimpleNamespace(accepted=True),
                    add_done_callback=lambda cb: cb(future)
                )
                return future

        handle = MockGoalHandle()
        action_client = MockActionClient()
        wrapper = SimpleNamespace(
            sm=self.sm,
            node=SimpleNamespace(
                get_clock=lambda: SimpleNamespace(now=lambda: SimpleNamespace(to_msg=lambda: None))
            ),
            goal_pub=SimpleNamespace(publish=lambda msg: None),
            nav_action_client=action_client,
            current_goal_handle=None,
            goal_status=None,
            _nav_goal_seq=0,
            _nav_goal_pending=False,
            cancel_nav_goal=lambda: MissionROSNode.cancel_nav_goal(wrapper),
            _goal_response_callback=lambda f, s=None: MissionROSNode._goal_response_callback(wrapper, f, s),
            _goal_result_callback=lambda f, s=None: MissionROSNode._goal_result_callback(wrapper, f, s)
        )
        self.sm.ros_node = wrapper
        self.sm.state = MissionState.NAVIGATING_TO_LANDMARK

        # Отправка цели
        MissionROSNode.send_nav_goal(wrapper, 1.0, 2.0, 0.0)
        self.assertEqual(len(sent_goals), 1)
        self.assertEqual(sent_goals[0].pose.pose.position.x, 1.0)
        self.assertEqual(sent_goals[0].pose.pose.position.y, 2.0)

        # Установка активного goal_handle
        wrapper.current_goal_handle = handle

        # Отмена цели при переходе в SEARCHING_VICTIM
        self.sm.current_waypoint = Waypoint(x=0.4, y=0.4, name="Test")
        self.sm.robot_x = 0.4
        self.sm.robot_y = 0.4
        self.sm.step(0.1)
        self.assertEqual(self.sm.state, MissionState.SEARCHING_VICTIM)
        self.assertEqual(len(cancelled_goals), 1)

        # Отмена цели при переходе в EMERGENCY_STOP
        wrapper.current_goal_handle = handle
        self.sm.trigger_emergency_stop()
        self.assertEqual(self.sm.state, MissionState.EMERGENCY_STOP)
        self.assertGreaterEqual(len(cancelled_goals), 2)

    def test_nav2_pending_goal_cancelled_on_estop(self):
        """Проверка отмены цели, если E-STOP нажат до подтверждения сервером (race condition)."""
        from types import SimpleNamespace
        from brain.mission_sm import MissionROSNode

        cancelled_handles = []

        class MockGoalHandle:
            def cancel_goal_async(self):
                cancelled_handles.append(True)

        callbacks = []

        class MockActionClient:
            def send_goal_async(self, goal):
                future = SimpleNamespace(
                    result=lambda: SimpleNamespace(accepted=True, cancel_goal_async=handle.cancel_goal_async, get_result_async=lambda: SimpleNamespace(add_done_callback=lambda cb: None)),
                    add_done_callback=lambda cb: callbacks.append(cb)
                )
                return future

        handle = MockGoalHandle()
        action_client = MockActionClient()
        wrapper = SimpleNamespace(
            sm=self.sm,
            node=SimpleNamespace(
                get_clock=lambda: SimpleNamespace(now=lambda: SimpleNamespace(to_msg=lambda: None))
            ),
            goal_pub=SimpleNamespace(publish=lambda msg: None),
            nav_action_client=action_client,
            current_goal_handle=None,
            goal_status=None,
            _nav_goal_seq=0,
            _nav_goal_pending=False,
            cancel_nav_goal=lambda: MissionROSNode.cancel_nav_goal(wrapper),
            _goal_response_callback=lambda f, s=None: MissionROSNode._goal_response_callback(wrapper, f, s),
            _goal_result_callback=lambda f, s=None: MissionROSNode._goal_result_callback(wrapper, f, s)
        )
        self.sm.ros_node = wrapper
        self.sm.state = MissionState.NAVIGATING_TO_LANDMARK

        # 1. Отправляем цель — она уходит в pending
        MissionROSNode.send_nav_goal(wrapper, 1.0, 2.0, 0.0)
        self.assertTrue(wrapper._nav_goal_pending)
        self.assertEqual(len(callbacks), 1)

        # 2. До получения ответа от сервера нажимается E-STOP
        self.sm.trigger_emergency_stop()
        self.assertEqual(self.sm.state, MissionState.EMERGENCY_STOP)
        self.assertFalse(wrapper._nav_goal_pending)

        # 3. Сервер Nav2 наконец отвечает и отдает handle
        mock_future = SimpleNamespace(
            result=lambda: SimpleNamespace(accepted=True, cancel_goal_async=handle.cancel_goal_async)
        )
        callbacks[0](mock_future)

        # Handle должен быть немедленно отменен через cancel_goal_async()
        self.assertEqual(len(cancelled_handles), 1)
        self.assertIsNone(wrapper.current_goal_handle)

    def test_nav2_action_client_replaces_goal_pose_and_falls_back(self):
        """Проверка: send_nav_goal не дублирует цель в /goal_pose при рабочем ActionClient, но использует fallback при его отсутствии."""
        from types import SimpleNamespace
        from brain.mission_sm import MissionROSNode

        published_goal_poses = []
        sent_action_goals = []

        class MockActionClient:
            def server_is_ready(self):
                return True
            def send_goal_async(self, goal):
                sent_action_goals.append(goal)
                future = SimpleNamespace(
                    result=lambda: SimpleNamespace(accepted=True),
                    add_done_callback=lambda cb: None
                )
                return future

        wrapper = SimpleNamespace(
            sm=self.sm,
            node=SimpleNamespace(
                get_clock=lambda: SimpleNamespace(now=lambda: SimpleNamespace(to_msg=lambda: None))
            ),
            goal_pub=SimpleNamespace(publish=lambda msg: published_goal_poses.append(msg)),
            nav_action_client=MockActionClient(),
            current_goal_handle=None,
            goal_status=None,
            _nav_goal_seq=0,
            _nav_goal_pending=False,
            cancel_nav_goal=lambda: MissionROSNode.cancel_nav_goal(wrapper),
            _goal_response_callback=lambda f, s=None: None,
            _goal_result_callback=lambda f, s=None: None
        )

        # 1. При наличии ActionClient топик /goal_pose НЕ вызывается
        MissionROSNode.send_nav_goal(wrapper, 1.0, 2.0, 0.0)
        self.assertEqual(len(sent_action_goals), 1)
        self.assertEqual(len(published_goal_poses), 0)

        # 2. Если ActionClient отсутствует (None), цель отправляется через fallback /goal_pose
        wrapper.nav_action_client = None
        MissionROSNode.send_nav_goal(wrapper, 3.0, 4.0, 0.5)
        self.assertEqual(len(published_goal_poses), 1)
        self.assertAlmostEqual(published_goal_poses[0].pose.position.x, 3.0)
        self.assertAlmostEqual(published_goal_poses[0].pose.position.y, 4.0)

    def test_manual_cmd_vel_cancels_nav2_goal(self):
        """Проверка: ручные команды скорости send_cmd_vel отменяют активную цель Nav2."""
        from types import SimpleNamespace
        from brain.mission_sm import MissionROSNode

        cancelled = []
        sent_twists = []

        class MockGoalHandle:
            def cancel_goal_async(self):
                cancelled.append(True)

        wrapper = SimpleNamespace(
            sm=self.sm,
            cmd_vel_sm_pub=SimpleNamespace(publish=lambda msg: sent_twists.append(msg)),
            cmd_vel_emergency_pub=SimpleNamespace(publish=lambda msg: None),
            cmd_vel_pub=None,
            current_goal_handle=MockGoalHandle(),
            _nav_goal_seq=1,
            _nav_goal_pending=True,
            cancel_nav_goal=lambda: MissionROSNode.cancel_nav_goal(wrapper)
        )
        self.sm.ros_node = wrapper

        # Отправка ненулевой скорости (ручное управление / поворот)
        MissionROSNode.send_cmd_vel(wrapper, 0.2, 0.1)
        self.assertEqual(len(cancelled), 1)
        self.assertIsNone(wrapper.current_goal_handle)
        self.assertEqual(len(sent_twists), 1)

    def test_pause_and_estop_resume_redispatches_nav_goal(self):
        """Проверка: возобновление после PAUSED или E-STOP переотправляет цель Nav2."""
        published_goals = []
        self.sm._publish_goal_pose = lambda wp: published_goals.append(wp)
        self.sm.current_waypoint = Waypoint(x=2.0, y=2.0, name="Target")
        self.sm.state = MissionState.NAVIGATING_TO_LANDMARK

        # 1. Пауза отменяет цель и ставит PAUSED
        self.sm.toggle_pause()
        self.assertEqual(self.sm.state, MissionState.PAUSED)

        # Возобновление возвращает NAVIGATING_TO_LANDMARK и переотправляет цель
        self.sm.toggle_pause()
        self.assertEqual(self.sm.state, MissionState.NAVIGATING_TO_LANDMARK)
        self.assertEqual(len(published_goals), 1)
        self.assertEqual(published_goals[0].name, "Target")

        # 2. E-STOP останавливает
        self.sm.trigger_emergency_stop()
        self.assertEqual(self.sm.state, MissionState.EMERGENCY_STOP)

        # Сброс E-STOP восстанавливает движение и переотправляет цель
        self.sm.reset_emergency_stop()
        self.assertEqual(self.sm.state, MissionState.NAVIGATING_TO_LANDMARK)
        self.assertEqual(len(published_goals), 2)

    def test_fallback_odom_with_initial_yaw(self):
        """Проверка: fallback одометрии корректно учитывает угол поворота арены initial_yaw."""
        from types import SimpleNamespace
        from brain.mission_sm import MissionROSNode

        wrapper = SimpleNamespace(sm=self.sm, update_pose_from_tf=lambda: False)
        self.sm.mock_mode = False
        self.sm.initial_x = 0.4
        self.sm.initial_y = 0.4
        self.sm.initial_yaw = math.pi / 2.0  # Поворот на 90 градусов
        self.sm.path_history = [(0.4, 0.4)]

        # Робот проехал вперед по одометрии (x=1.0, y=0.0)
        # При повороте на 90° вперед — это по оси Y карты!
        msg = SimpleNamespace(
            pose=SimpleNamespace(
                pose=SimpleNamespace(
                    position=SimpleNamespace(x=1.0, y=0.0),
                    orientation=SimpleNamespace(x=0.0, y=0.0, z=0.0, w=1.0)
                )
            )
        )
        MissionROSNode._odom_callback(wrapper, msg)
        self.assertAlmostEqual(self.sm.robot_x, 0.4, places=5)
        self.assertAlmostEqual(self.sm.robot_y, 1.4, places=5)
        self.assertAlmostEqual(self.sm.robot_yaw, math.pi / 2.0, places=5)

    def test_cmd_vel_arbitration_topics_d04(self):
        """Проверка D04: разделение топиков /cmd_vel_sm и /cmd_vel_emergency."""
        from types import SimpleNamespace
        from brain.mission_sm import MissionROSNode

        sm_messages = []
        emergency_messages = []

        wrapper = SimpleNamespace(
            sm=self.sm,
            cmd_vel_sm_pub=SimpleNamespace(publish=lambda msg: sm_messages.append(msg)),
            cmd_vel_emergency_pub=SimpleNamespace(publish=lambda msg: emergency_messages.append(msg)),
            cmd_vel_pub=None,
            current_goal_handle=None,
            _nav_goal_pending=False,
            cancel_nav_goal=lambda: None
        )
        self.sm.ros_node = wrapper

        # 1. Штатная отправка скорости (поисковый разворот / ручное управление)
        MissionROSNode.send_cmd_vel(wrapper, 0.15, 0.4)
        self.assertEqual(len(sm_messages), 1)
        self.assertEqual(len(emergency_messages), 0)
        self.assertAlmostEqual(sm_messages[0].linear.x, 0.15)
        self.assertAlmostEqual(sm_messages[0].angular.z, 0.4)

        # 2. Аварийная остановка E-STOP
        MissionROSNode.send_emergency_stop(wrapper)
        self.assertEqual(len(emergency_messages), 1)
        self.assertAlmostEqual(emergency_messages[0].linear.x, 0.0)
        self.assertAlmostEqual(emergency_messages[0].angular.z, 0.0)

        # 3. _publish_zero_velocity в состоянии EMERGENCY_STOP публикует в /cmd_vel_emergency
        wrapper.send_emergency_stop = lambda: MissionROSNode.send_emergency_stop(wrapper)
        wrapper.send_cmd_vel = lambda vx, wz: MissionROSNode.send_cmd_vel(wrapper, vx, wz)
        self.sm.state = MissionState.EMERGENCY_STOP
        self.sm._publish_zero_velocity()
        self.assertGreaterEqual(len(emergency_messages), 2)

    def test_ros_node_init_handles_missing_nav2_action(self):
        """Проверка: при отсутствии nav2_msgs нода MissionROSNode не падает с AttributeError и работает через fallback."""
        from unittest.mock import patch
        import brain.mission_sm as sm_mod

        with patch.object(sm_mod, 'NAV2_ACTION_AVAILABLE', False):
            # Создаем ноду в окружении, где NAV2_ACTION_AVAILABLE = False
            ros_node = sm_mod.MissionROSNode(self.sm)
            if ros_node.node:
                self.assertIsNone(ros_node.nav_action_client)
                self.assertIsNotNone(ros_node.goal_pub)
                self.assertIsNotNone(ros_node.cmd_vel_sm_pub)
                self.assertIsNotNone(ros_node.cmd_vel_emergency_pub)
                ros_node.node.destroy_node()


    def test_system_launcher_safe_launch_guard_d25(self):
        """Проверка D25: защита от ошибочного локального запуска на ноутбуке без /dev/ttyUSB0."""
        from brain.mission_sm import SystemLauncher

        launcher = SystemLauncher()

        # 1. Попытка локального запуска на ноутбуке без mock_hardware и без SSH -> блокировка
        safe, reason = launcher.check_safe_to_launch(mock_hardware=False, use_ssh=False)
        self.assertFalse(safe)
        self.assertIn("/dev/ttyUSB0", reason)
        self.assertIn("SSH", reason)

        # Вызов start с небезопасными параметрами не должен порождать процесс
        ok, msg = launcher.start(mock_hardware=False, use_ssh=False)
        self.assertFalse(ok)
        self.assertIn("/dev/ttyUSB0", msg)
        self.assertFalse(launcher.is_alive())
        self.assertTrue(any("[WARN]" in line and "/dev/ttyUSB0" in line for line in launcher.log_lines))

        # 2. Режим симуляции (mock_hardware=True) разрешён
        safe_mock, _ = launcher.check_safe_to_launch(mock_hardware=True, use_ssh=False)
        self.assertTrue(safe_mock)

        # 3. Режим SSH (use_ssh=True) разрешён
        safe_ssh, _ = launcher.check_safe_to_launch(mock_hardware=False, use_ssh=True)
        self.assertTrue(safe_ssh)

        # 4. Проверка интеграции со State Machine при mock_mode=False
        sm_real = MissionStateMachine(mock_mode=False)
        self.assertFalse(sm_real.mock_mode)
        safe_sm, reason_sm = sm_real.system_launcher.check_safe_to_launch(
            mock_hardware=sm_real.mock_mode,
            use_ssh=False
        )
        self.assertFalse(safe_sm)
        self.assertIn("/dev/ttyUSB0", reason_sm)

    def test_approach_waypoints_exclude_start_coordinates_d18(self):
        """Проверка D18: отсутствие паразитных координат старта [0.4, 0.4] в точках поиска."""
        from brain.llm_client import (
            LANDMARK_CANDIDATE_WAYPOINTS,
            LandmarkID,
            get_target_waypoints,
            load_arena
        )

        arena = load_arena()

        # 1. Объект parking в конфигурации арены не должен вести в стартовую ячейку [0.4, 0.4]
        parking_goals = arena.get("objects", {}).get("parking", {}).get("goals", [])
        for g in parking_goals:
            self.assertFalse(
                abs(g[0] - 0.4) < 1e-3 and abs(g[1] - 0.4) < 1e-3,
                f"Объект parking содержит координаты старта [0.4, 0.4]: {g}"
            )

        # 2. Все ориентиры в LANDMARK_CANDIDATE_WAYPOINTS не должны содержать [0.4, 0.4]
        for landmark, candidates in LANDMARK_CANDIDATE_WAYPOINTS.items():
            for pt in candidates:
                self.assertFalse(
                    abs(pt[0] - 0.4) < 1e-3 and abs(pt[1] - 0.4) < 1e-3,
                    f"Ориентир {landmark} содержит паразитные координаты старта [0.4, 0.4]: {pt}"
                )

        # 3. get_target_waypoints для всех ориентиров не возвращает [0.4, 0.4]
        for lid in LandmarkID:
            wps = get_target_waypoints(lid.value, arena)
            for wp in wps:
                self.assertFalse(
                    abs(wp["x"] - 0.4) < 1e-3 and abs(wp["y"] - 0.4) < 1e-3,
                    f"get_target_waypoints({lid.value}) вернул точку старта: {wp}"
                )

    def test_polygon_map_raster_and_thresholds_d15(self):
        """Проверка D15: разделение зон в растре карты polygon_empty_4x4 и пороги Nav2."""
        import yaml

        repo_root = Path(__file__).resolve().parent.parent
        yaml_path = repo_root / "nav2" / "maps" / "polygon_empty_4x4.yaml"
        pgm_path = repo_root / "nav2" / "maps" / "polygon_empty_4x4.pgm"

        self.assertTrue(yaml_path.exists(), f"Файл {yaml_path} не найден")
        self.assertTrue(pgm_path.exists(), f"Файл {pgm_path} не найден")

        with open(yaml_path) as f:
            cfg = yaml.safe_load(f)

        free_thresh = cfg.get("free_thresh")
        occ_thresh = cfg.get("occupied_thresh")

        self.assertAlmostEqual(free_thresh, 0.15, places=3, msg="free_thresh должен быть 0.15")
        self.assertAlmostEqual(occ_thresh, 0.65, places=3, msg="occupied_thresh должен быть 0.65")

        with open(pgm_path) as f:
            lines = [line.strip() for line in f if line.strip() and not line.startswith("#")]

        tokens = [int(t) for line in lines[3:] for t in line.split()]
        self.assertEqual(len(tokens), 10000)
        grid = [tokens[i * 100:(i + 1) * 100] for i in range(100)]

        def get_prob(v: int) -> float:
            return (255.0 - v) / 255.0

        # Внутреннее пространство полигона (rows 10..89, cols 10..89, кроме препятствий) должно быть 254 (p < 0.15)
        for r in range(10, 90):
            for c in range(10, 90):
                val = grid[r][c]
                if val != 0:
                    self.assertEqual(val, 254, f"Пиксель ({r},{c}) внутри полигона должен быть 254 (free), получен {val}")
                    self.assertLess(get_prob(val), free_thresh)

        # Стены периметра (rows 9, 90 и cols 9, 90) должны быть 0 (p > 0.65)
        for c in range(9, 91):
            self.assertEqual(grid[9][c], 0)
            self.assertEqual(grid[90][c], 0)
            self.assertGreater(get_prob(0), occ_thresh)
        for r in range(9, 91):
            self.assertEqual(grid[r][9], 0)
            self.assertEqual(grid[r][90], 0)
            self.assertGreater(get_prob(0), occ_thresh)

        # Внешняя область за стенами должна быть 205 (free_thresh <= p <= occupied_thresh -> unknown)
        p_205 = get_prob(205)
        self.assertGreaterEqual(p_205, free_thresh)
        self.assertLessEqual(p_205, occ_thresh)
        for r in range(100):
            for c in range(100):
                if r < 9 or r > 90 or c < 9 or c > 90:
                    self.assertEqual(grid[r][c], 205)

    def test_cleanup_parasitic_python_files_d16(self):
        """Проверка D16: очистка паразитных файлов и симлинков mission_sm.python."""
        brain_dir = Path(__file__).resolve().parent
        bad_file = brain_dir / "mission_sm.python"
        bad_symlink = brain_dir / "brain" / "mission_sm.python"

        self.assertFalse(bad_file.exists() or bad_file.is_symlink(), f"Файл {bad_file} не должен существовать")
        self.assertFalse(bad_symlink.exists() or bad_symlink.is_symlink(), f"Симлинк {bad_symlink} не должен существовать")

        # Никаких файлов с расширением .python не должно быть во всем пакете
        stray_python_files = list(brain_dir.glob("**/*.python"))
        self.assertEqual(stray_python_files, [], f"Найдены паразитные .python файлы: {stray_python_files}")

        # Все существующие симлинки в подпакете brain должны указывать на существующие файлы
        subpkg_symlinks = [p for p in (brain_dir / "brain").iterdir() if p.is_symlink()]
        self.assertGreater(len(subpkg_symlinks), 0, "Подпакет brain должен содержать рабочие симлинки")
        for sym in subpkg_symlinks:
            self.assertTrue(sym.resolve().exists(), f"Битая символическая ссылка: {sym} -> {sym.resolve()}")


if __name__ == "__main__":
    unittest.main()

