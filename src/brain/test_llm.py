#!/usr/bin/env python3
"""
test_llm.py — Набор модульных и интеграционных тестов для brain.llm_client.

Проверяет:
1. Корректность перечисления и метаданных ориентиров (7 допустимых ID).
2. Валидацию Pydantic/dataclass структуры CommandInterpretation.
3. 100% точность детерминированного эвристического fallback-парсера по ключевым словам.
4. Интеграцию с локальной Ollama (Qwen 3.5 9B) на реальных судейских формулировках.
5. Соблюдение ограничения по формату вывода (Strict JSON Mode).
"""

import unittest
from typing import List, Tuple
from brain.llm_client import (
    LandmarkID,
    LANDMARK_DETAILS,
    MAP_OBJECT_DETAILS,
    CommandInterpretation,
    LLMClient,
    load_arena,
    validate_nav2_goal,
)


class TestLandmarkDefinitions(unittest.TestCase):
    """Проверка определений и метаданных ориентиров."""

    def test_landmark_count(self):
        """Регламент задаёт ровно семь ID; карта хранится отдельно."""
        self.assertEqual(len(LandmarkID), 7)

    def test_landmark_values(self):
        """Значения ориентиров должны строго совпадать со спецификацией."""
        expected_ids = {
            "smoke_tower",
            "panel_house",
            "bridges",
            "tanker_truck",
            "fallen_tree",
            "car_jam",
            "debris_pvc"
        }
        actual_ids = {lm.value for lm in LandmarkID}
        self.assertEqual(actual_ids, expected_ids)

    def test_map_objects_are_not_regulation_landmarks(self):
        self.assertEqual(set(MAP_OBJECT_DETAILS), {
            "start", "parking", "yellow_building", "blue_building", "river"
        })

    def test_landmark_details_coverage(self):
        """Для каждого ориентира должны быть заполнены метаданные и алиасы."""
        for lm in LandmarkID:
            self.assertIn(lm, LANDMARK_DETAILS)
            details = LANDMARK_DETAILS[lm]
            self.assertTrue(len(details["name_ru"]) > 0)
            self.assertTrue(len(details["default_strategy"]) > 0)
            self.assertTrue(len(details["aliases"]) >= 1)


class TestCommandInterpretationModel(unittest.TestCase):
    """Тестирование структуры CommandInterpretation."""

    def test_valid_interpretation(self):
        cmd = CommandInterpretation(
            target_landmark_id="smoke_tower",
            search_strategy="inspect_perimeter",
            reasoning="Обнаружен дым.",
            confidence=0.98,
            source="llm",
            latency_sec=1.23
        )
        self.assertTrue(cmd.is_valid())
        d = cmd.to_dict()
        self.assertEqual(d["target_landmark_id"], "smoke_tower")
        self.assertEqual(d["confidence"], 0.98)

        json_str = cmd.to_json()
        self.assertIn('"target_landmark_id": "smoke_tower"', json_str)

    def test_invalid_interpretation(self):
        cmd = CommandInterpretation(
            target_landmark_id="unknown_building",
            search_strategy="random_search",
            reasoning="Неизвестный объект"
        )
        self.assertFalse(cmd.is_valid())


class TestNavigationGoals(unittest.TestCase):
    def setUp(self):
        self.arena = load_arena()

    def test_accepts_configured_approach_pose(self):
        goal = validate_nav2_goal(
            {"frame_id": "map", "x": 2.8, "y": 3.6, "yaw": 0.0},
            "bridges", self.arena,
        )
        self.assertEqual(goal, {"frame_id": "map", "x": 2.8, "y": 3.6, "yaw": 0.0})

    def test_rejects_invented_or_blocked_pose(self):
        with self.assertRaises(ValueError):
            validate_nav2_goal(
                {"frame_id": "map", "x": 1.2, "y": 1.2, "yaw": 0.0},
                "bridges", self.arena,
            )

    def test_interpret_keeps_only_whitelisted_pose(self):
        client = LLMClient()
        client._query_ollama = lambda _: (
            '{"target_landmark_id":"bridges","search_strategy":"inspect",'
            '"reasoning":"Мост указан в задании.",'
            '"nav2_goal":{"frame_id":"map","x":2.8,"y":3.6,"yaw":0.0}}'
        )
        result = client.interpret("Проверить мост", use_fallback=False)
        self.assertEqual(result.nav2_goal, {
            "frame_id": "map", "x": 2.8, "y": 3.6, "yaw": 0.0
        })


class TestHeuristicFallback(unittest.TestCase):
    """Тестирование детерминированного эвристического fallback-парсера."""

    def setUp(self):
        self.client = LLMClient()

    def test_fallback_accuracy_on_standard_cases(self):
        """Проверка точности fallback-парсера на различных формулировках."""
        cases: List[Tuple[str, str]] = [
            ("Человек лежит возле горящего здания Стакан, валит густой дым", "smoke_tower"),
            ("Около круглой башни с динамической имитацией очага возгорания", "smoke_tower"),
            ("В руинах двухсекционного панельного дома замечен пострадавший", "panel_house"),
            ("Обрушившийся многоквартирный панельный дом, под плитами человек", "panel_house"),
            ("Пострадавший находится прямо под мостовым переходом", "bridges"),
            ("Въезд на эстакаду с защитными бортиками заблокирован человеком", "bridges"),
            ("Возле опрокинутого бензовоза разлив топлива, требуется помощь", "tanker_truck"),
            ("Аварийная автоцистерна на боку, рядом лежит пострадавший", "tanker_truck"),
            ("Проезд заблокирован поваленной березой, под ветками силуэт", "fallen_tree"),
            ("Упавшее дерево перекрыло дорогу к пострадавшему", "fallen_tree"),
            ("Затор из легковых машин в масштабе 1:32 блокирует проезд", "car_jam"),
            ("В автомобильной пробке обнаружен человек", "car_jam"),
            ("Завал из фрагментов поливинилхлорида (ПВХ)", "debris_pvc"),
            ("Строительный мусор и обломки пластиковых конструкций", "debris_pvc"),
        ]

        for prompt, expected_id in cases:
            with self.subTest(prompt=prompt):
                result = self.client.fallback_heuristic_parse(prompt)
                self.assertEqual(
                    result.target_landmark_id,
                    expected_id,
                    f"Fallback ошибся: для '{prompt}' ожидали {expected_id}, получили {result.target_landmark_id}"
                )
                self.assertTrue(result.is_valid())
                self.assertGreater(result.confidence, 0.5)


class TestOllamaLiveIntegration(unittest.TestCase):
    """Интеграционные тесты с реальной моделью Ollama Qwen 3.5 9B."""

    @classmethod
    def setUpClass(cls):
        cls.client = LLMClient()
        cls.ollama_available = cls.client.is_available()
        if cls.ollama_available:
            cls.client.warmup()

    def test_ollama_server_reachable(self):
        """Проверка доступности локального сервера Ollama."""
        if not self.ollama_available:
            self.skipTest("Сервер Ollama недоступен на localhost:11434. Проверьте запуск 'ollama serve'.")
        self.assertTrue(self.ollama_available)

    def test_llm_interpretation_smoke_tower(self):
        """Проверка распознавания здания «Стакан»."""
        if not self.ollama_available:
            self.skipTest("Ollama недоступна")

        prompt = "Пострадавший находится рядом со зданием Стакан, из которого валит густой дым."
        res = self.client.interpret(prompt)
        self.assertEqual(res.target_landmark_id, LandmarkID.SMOKE_TOWER.value)
        self.assertTrue(res.is_valid())
        self.assertIn("smoke", res.target_landmark_id)
        self.assertTrue(len(res.reasoning) > 0)

    def test_llm_interpretation_panel_house(self):
        """Проверка распознавания разрушенного панельного дома."""
        if not self.ollama_available:
            self.skipTest("Ollama недоступна")

        prompt = "Человек обнаружен под завалами плит разрушенного панельного дома."
        res = self.client.interpret(prompt)
        self.assertEqual(res.target_landmark_id, LandmarkID.PANEL_HOUSE.value)
        self.assertTrue(res.is_valid())

    def test_llm_interpretation_tanker_truck(self):
        """Проверка распознавания аварийного бензовоза."""
        if not self.ollama_available:
            self.skipTest("Ollama недоступна")

        prompt = "Около перевернутой автоцистерны с бензином лежит человек."
        res = self.client.interpret(prompt)
        self.assertEqual(res.target_landmark_id, LandmarkID.TANKER_TRUCK.value)
        self.assertTrue(res.is_valid())

    def test_llm_interpretation_bridges(self):
        """Проверка распознавания мостовых переходов."""
        if not self.ollama_available:
            self.skipTest("Ollama недоступна")

        prompt = "Пострадавший укрылся под одним из мостовых переходов."
        res = self.client.interpret(prompt)
        self.assertEqual(res.target_landmark_id, LandmarkID.BRIDGES.value)
        self.assertTrue(res.is_valid())

    def test_llm_interpretation_fallen_tree(self):
        """Проверка распознавания упавшего дерева."""
        if not self.ollama_available:
            self.skipTest("Ollama недоступна")

        prompt = "Пострадавший зажат ветками упавшей искусственной берёзы на проезжей части."
        res = self.client.interpret(prompt)
        self.assertEqual(res.target_landmark_id, LandmarkID.FALLEN_TREE.value)
        self.assertTrue(res.is_valid())

    def test_llm_interpretation_car_jam(self):
        """Проверка распознавания транспортного затора."""
        if not self.ollama_available:
            self.skipTest("Ollama недоступна")

        prompt = "В транспортном заторе из брошенных легковых автомобилей найден раненый человек."
        res = self.client.interpret(prompt)
        self.assertEqual(res.target_landmark_id, LandmarkID.CAR_JAM.value)
        self.assertTrue(res.is_valid())

    def test_llm_interpretation_debris_pvc(self):
        """Проверка распознавания завала из фрагментов ПВХ."""
        if not self.ollama_available:
            self.skipTest("Ollama недоступна")

        prompt = "Помощь требуется человеку, заблокированному завалом из фрагментов ПВХ труб."
        res = self.client.interpret(prompt)
        self.assertEqual(res.target_landmark_id, LandmarkID.DEBRIS_PVC.value)
        self.assertTrue(res.is_valid())


if __name__ == "__main__":
    unittest.main(verbosity=2)
