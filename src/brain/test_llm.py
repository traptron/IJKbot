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
import json
from unittest.mock import patch
from typing import List, Tuple
from brain.llm_client import (
    LandmarkID,
    LANDMARK_DETAILS,
    MAP_OBJECT_DETAILS,
    CommandInterpretation,
    LLMClient,
    load_arena,
    validate_nav2_goal,
    default_nav2_goals,
    STATIC_TARGET_IDS,
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
            "start", "parking", "yellow_building_debris", "yellow_building", "blue_building", "river"
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
            target_landmark_id="river",
            search_strategy="inspect_perimeter",
            reasoning="Обнаружен дым.",
            confidence=0.98,
            source="llm",
            latency_sec=1.23
        )
        self.assertTrue(cmd.is_valid())
        d = cmd.to_dict()
        self.assertEqual(d["target_landmark_id"], "river")
        self.assertEqual(d["confidence"], 0.98)

        json_str = cmd.to_json()
        self.assertIn('"target_landmark_id": "river"', json_str)

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
            ("Бензовоз опрокинулся около реки. Искать рядом с ним.", "river"),
            ("Дерево свалилось на голубой дом. Искать рядом с деревом.", "blue_building"),
            ("Бензовоз рядом с жёлтым зданием", "yellow_building"),
            ("Дерево лежит у остановки", "parking"),
            ("Человек у бензовоза возле мостов", "bridges"),
            ("На парковке синие машины", "parking"),
            ("У синего здания упала берёза", "blue_building"),
            ("Бензовоз на берегу реки", "river"),
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

    def test_fallback_requires_llm_for_yellow_building_debris(self):
        with self.assertRaisesRegex(ValueError, "требует распознавания локальной LLM"):
            self.client.fallback_heuristic_parse("Пострадавший у обломков жёлтого здания")

    def test_llm_selects_yellow_building_debris_and_uses_cell_1_1_route(self):
        answer = json.dumps(dict(
            target_landmark_id="yellow_building_debris",
            search_strategy="inspect",
            reasoning="Обломки жёлтого здания указаны как отдельный ориентир.",
            local_object_id=None,
        ), ensure_ascii=False)
        with patch.object(self.client, "_query_ollama", return_value=answer):
            result = self.client.interpret("Найти пострадавшего у обломков жёлтого здания", use_fallback=False)

        self.assertEqual(result.target_landmark_id, "yellow_building_debris")
        self.assertEqual(self.client.arena["objects"]["yellow_building_debris"]["cells"], [[1, 1]])
        self.assertEqual(result.nav2_goals, default_nav2_goals("yellow_building_debris", self.client.arena))
        self.assertIn("yellow_building_debris", self.client.navigation_prompt())
        self.assertIn("выбирай yellow_building_debris", self.client.navigation_prompt())


class TestStaticTargetRegression(unittest.TestCase):
    TASK = ("Пострадавший находится рядом с бензовозом, который опрокинулся набок около реки. "
            "Поиск необходимо продолжить в непосредственной близости от этого объекта")

    def test_timeout_returns_river_and_river_points(self):
        client = LLMClient()
        with patch.object(client, '_query_ollama', side_effect=TimeoutError('test timeout')):
            result = client.interpret(self.TASK)
        self.assertEqual(result.target_landmark_id, 'river')
        self.assertEqual(result.source, 'heuristic_fallback')
        self.assertEqual(result.nav2_goals, default_nav2_goals('river', client.arena))
        self.assertIn('test timeout', json.loads(result.raw_text)['reasoning'])

    def test_dynamic_llm_target_cannot_produce_dynamic_route(self):
        client = LLMClient()
        answer = json.dumps(dict(target_landmark_id='tanker_truck', reasoning='бензовоз',
                                 search_strategy='inspect', nav2_goal=None))
        with patch.object(client, '_query_ollama', return_value=answer):
            result = client.interpret(self.TASK)
        self.assertEqual(result.target_landmark_id, 'river')
        self.assertEqual(result.nav2_goals, default_nav2_goals('river', client.arena))

    def test_llm_coordinates_are_not_used(self):
        client = LLMClient()
        answer = json.dumps(dict(target_landmark_id='river', reasoning='Река',
            search_strategy='inspect', local_object_id='tanker_truck',
            nav2_goals=[dict(frame_id='map', x=2, y=1.2, yaw=0)]))
        with patch.object(client, '_query_ollama', return_value=answer):
            result = client.interpret(self.TASK, use_fallback=False)
        self.assertEqual(result.nav2_goals, default_nav2_goals('river', client.arena))
        self.assertEqual(result.local_object_id, 'tanker_truck')

    def test_no_arbitrary_fallback_without_unique_static_target(self):
        for text in ('Человек у бензовоза', 'Человек у реки или моста',
                     'Не у реки', 'Синяя машина', '', 'Человек у дерева'):
            with self.subTest(text=text):
                client = LLMClient()
                with patch.object(client, '_query_ollama', side_effect=TimeoutError()):
                    with self.assertRaises(ValueError):
                        client.interpret(text)

    def test_wrong_object_pose_rejected(self):
        client = LLMClient()
        with self.assertRaises(ValueError):
            validate_nav2_goal(dict(frame_id='map', x=2.8, y=3.6, yaw=0), 'river', client.arena)


class TestOllamaLiveIntegration(unittest.TestCase):
    """Real inference: fallback must not conceal a model failure."""

    @classmethod
    def setUpClass(cls):
        cls.client = LLMClient()
        if not cls.client.is_available():
            raise unittest.SkipTest('Ollama недоступна')

    def test_static_landmarks_live(self):
        cases = [
            (TestStaticTargetRegression.TASK, 'river', 'tanker_truck'),
            ('Пострадавший находится рядом с деревом,свалившимся на голубой дом.'
             'Продолжайте поиск пострадавшего рядом с упавшим деревом.', 'blue_building', 'fallen_tree'),
            ('Бензовоз возле жёлтого здания. Ищите человека рядом с ним.', 'yellow_building', 'tanker_truck'),
            ('Пострадавший находится у обломков жёлтого здания.', 'yellow_building_debris', None),
            ('Пострадавший у дерева возле остановки.', 'parking', 'fallen_tree'),
            ('Пострадавший у бензовоза возле моста.', 'bridges', 'tanker_truck'),
            ('Не у реки, а у синего здания находится бензовоз с пострадавшим.', 'blue_building', 'tanker_truck'),
        ]
        for text, target, local in cases:
            with self.subTest(text=text):
                result = self.client.interpret(text, use_fallback=False)
                self.assertEqual(result.source, 'llm')
                self.assertEqual(result.target_landmark_id, target)
                self.assertEqual(result.local_object_id, local)
                self.assertEqual(result.nav2_goals, default_nav2_goals(target, self.client.arena))
                self.assertIn(result.target_landmark_id, STATIC_TARGET_IDS)


if __name__ == '__main__':
    unittest.main(verbosity=2)
