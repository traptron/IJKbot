#!/usr/bin/env python3
"""
llm_client.py — Модуль взаимодействия с локальной LLM (Qwen 2.5 7B через Ollama)
для мобильного робота IJKbot (Хакатон «Эвакуация», Кубок РТК Высшая Лига).

Реализует:
1. Строгую типизацию ориентиров полигона (7 допустимых ID)
2. Запросы к Ollama API в режиме Structured Outputs (JSON Schema)
3. Парсинг, валидацию ответа и расчёт задержки инференса (<2 сек на RTX 5060)
4. Детерминированный fallback-парсер по семантическим ключевым словам на случай сбоя сети/LLM
5. ROS 2 ноду для интеграции в общую шину робота
"""

import os
import sys
import json
import time
import re
import math
from pathlib import Path
from enum import Enum
from typing import Dict, Any, Optional, List, Callable, Tuple
from dataclasses import dataclass, asdict

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    import urllib.request
    import urllib.error
    HAS_REQUESTS = False


class LandmarkID(str, Enum):
    """Строго определенные ориентиры и препятствия полигона регламента."""
    SMOKE_TOWER = "smoke_tower"      # Здание «Стакан» с динамической имитацией задымления/огня
    PANEL_HOUSE = "panel_house"      # Разрушенный двухсекционный панельный дом
    BRIDGES = "bridges"              # Мостовые переходы (2 моста с бортиками)
    TANKER_TRUCK = "tanker_truck"    # Аварийный опрокинутый бензовоз / разлив топлива
    FALLEN_TREE = "fallen_tree"      # Упавшее дерево (макет искусственной берёзы 450 мм)
    CAR_JAM = "car_jam"              # Транспортный затор из легковых машин 1:32
    DEBRIS_PVC = "debris_pvc"        # Завал из фрагментов ПВХ (строительные обломки)


# Описание ориентиров для формирования промпта и судейских отчетов
LANDMARK_DETAILS: Dict[LandmarkID, Dict[str, Any]] = {
    LandmarkID.SMOKE_TOWER: {
        "name_ru": "Макет здания типа «Стакан»",
        "description": "Цилиндрическое строение диаметром 660 мм и высотой 800 мм с ультразвуковым задымлением и светодиодной подсветкой очага пожара.",
        "default_strategy": "inspect_perimeter",
        "aliases": ["стакан", "башня", "дым", "задымление", "пожар", "возгорание", "пар", "очаг", "круглое здание", "цилиндр"]
    },
    LandmarkID.PANEL_HOUSE: {
        "name_ru": "Макет разрушенного панельного дома",
        "description": "Разрушенный панельный дом габаритами 1400х500х720 мм, занимающий две ячейки полигона.",
        "default_strategy": "approach_and_scan_facade",
        "aliases": ["панельный дом", "панелька", "разрушенный дом", "обрушившееся здание", "плиты", "руины", "многоэтажка"]
    },
    LandmarkID.BRIDGES: {
        "name_ru": "Мостовые переходы",
        "description": "Два мостовых перехода с высотой проезжей части 55 мм и боковыми защитными ограждениями.",
        "default_strategy": "cross_and_inspect_underpass",
        "aliases": ["мост", "мостовой переход", "мосты", "эстакада", "путепровод", "пандус", "ограждения"]
    },
    LandmarkID.TANKER_TRUCK: {
        "name_ru": "Макет аварийного бензовоза",
        "description": "Аварийный бензовоз, опрокинутый на бок, с имитацией разлива топлива.",
        "default_strategy": "approach_cautiously_check_leak",
        "aliases": ["бензовоз", "автоцистерна", "цистерна", "разлив топлива", "разлив бензина", "перевернутый грузовик", "горючее"]
    },
    LandmarkID.FALLEN_TREE: {
        "name_ru": "Упавшее дерево",
        "description": "Макет искусственной берёзы высотой 450 мм, перекрывающий проезд.",
        "default_strategy": "inspect_around_branches",
        "aliases": ["упавшее дерево", "поваленная береза", "березка", "ствол", "бревно", "ветки", "дерево на дороге"]
    },
    LandmarkID.CAR_JAM: {
        "name_ru": "Транспортный затор",
        "description": "Затор на дороге, сформированный из моделей легковых автомобилей масштаба 1:32.",
        "default_strategy": "scan_adjacent_cells",
        "aliases": ["затор", "пробка", "скопление автомобилей", "скопление машин", "брошенные машины", "легковые авто"]
    },
    LandmarkID.DEBRIS_PVC: {
        "name_ru": "Завал из фрагментов ПВХ",
        "description": "Завал из фрагментов поливинилхлорида, имитирующий строительные обломки.",
        "default_strategy": "inspect_debris_perimeter",
        "aliases": ["завал", "пвх", "поливинилхлорид", "строительные обломки", "обломки конструкций", "строительный мусор", "пластиковые трубы"]
    }
}


MAP_OBJECT_DETAILS: Dict[str, Dict[str, Any]] = {
    "start": {"name_ru": "Старт / пункт сбора", "aliases": ["старт", "пункт сбора"]},
    "parking": {"name_ru": "Парковка / остановка", "aliases": ["парковк", "остановк"]},
    "yellow_building": {"name_ru": "Жёлтое здание", "aliases": ["жёлт", "желт"]},
    "blue_building": {"name_ru": "Синее здание", "aliases": ["синее", "синего", "синему"]},
    "river": {"name_ru": "Река", "aliases": ["река", "реке", "реку", "берег"]},
}

def target_details(target_id: str) -> Dict[str, Any]:
    """Return a description for either a regulation landmark or a map object."""
    try:
        return LANDMARK_DETAILS[LandmarkID(target_id)]
    except (ValueError, KeyError):
        return MAP_OBJECT_DETAILS.get(target_id, {})


def load_arena(path: Optional[str] = None) -> Dict[str, Any]:
    """Load the same editable semantic map in source and installed workspaces."""
    if path is None:
        path = os.environ.get('IJKBOT_ARENA_FILE')
    if path is None:
        source = Path(__file__).resolve().parent / 'config' / 'arena.json'
        if source.is_file():
            path = str(source)
        else:
            from ament_index_python.packages import get_package_share_directory
            path = str(Path(get_package_share_directory('ijkbot_brain')) / 'config/arena.json')
    with open(path, encoding='utf-8') as stream:
        return json.load(stream)


def validate_nav2_goal(goal: Any, _landmark_id: str, arena: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Accept only one of the configured approach poses on the semantic map."""
    if goal is None:
        return None
    if not isinstance(goal, dict) or set(goal) != {'frame_id', 'x', 'y', 'yaw'}:
        raise ValueError('nav2_goal must contain frame_id, x, y, yaw')
    if goal['frame_id'] != 'map':
        raise ValueError('nav2_goal must be in map')
    values = [goal[k] for k in ('x', 'y', 'yaw')]
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in values):
        raise ValueError('nav2_goal coordinates must be finite numbers')
    candidates = []
    for object_data in arena['objects'].values():
        candidates.extend(object_data.get('goals', []))
    match = next((p for p in candidates if all(abs(a-b) < 1e-5 for a, b in zip(values, p))), None)
    if match is None:
        raise ValueError('nav2_goal is not an allowed approach pose on the map')
    x, y, yaw = match
    if not (0 < x < arena['size_m'][0] and 0 < y < arena['size_m'][1]):
        raise ValueError('Goal outside the arena')
    cell = [int(x / arena['cell_size_m']), int(y / arena['cell_size_m'])]
    if cell in arena['blocked_cells']:
        raise ValueError('Goal inside a blocked cell')
    return dict(frame_id='map', x=x, y=y, yaw=yaw)


def default_nav2_goal(target_id: str, arena: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return the first configured approach pose, or no pose for an unmapped target."""
    goals = arena.get('objects', {}).get(target_id, {}).get('goals', [])
    if not goals:
        return None
    x, y, yaw = goals[0]
    return validate_nav2_goal({'frame_id': 'map', 'x': x, 'y': y, 'yaw': yaw}, target_id, arena)


@dataclass
class CommandInterpretation:
    """Структурированная команда и семантический результат работы LLM."""
    target_landmark_id: str
    search_strategy: str
    reasoning: str
    confidence: float = 1.0
    source: str = "llm"               # "llm" или "heuristic_fallback"
    latency_sec: float = 0.0
    raw_response: Optional[Dict[str, Any]] = None
    nav2_goal: Optional[Dict[str, Any]] = None
    raw_text: str = ""
    token_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Конвертация в словарь."""
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        """Сериализация в форматированный JSON."""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    def is_valid(self) -> bool:
        """Проверка валидности регламентного ориентира."""
        return self.target_landmark_id in {landmark.value for landmark in LandmarkID}


# Системный промпт с описанием правил и ориентиров полигона
SYSTEM_PROMPT = """Ты — бортовой аналитический модуль мобильного робота IJKbot на полигоне хакатона «Эвакуация» (Кубок РТК Высшая Лига).
Твоя цель: проанализировать судейское задание на русском языке и точно определить целевой ориентир полигона, рядом с которым находится пострадавший человек.

НА ПОЛИГОНЕ СУЩЕСТВУЮТ РОВНО 7 ДОПУСТИМЫХ ОРИЕНТИРОВ (target_landmark_id):
1. "smoke_tower" — Макет здания типа «Стакан» (цилиндрическая башня D=660 мм, H=800 мм). Задымление, пар, очаг возгорания, светодиодная подсветка огня, круглое здание.
2. "panel_house" — Макет разрушенного панельного дома (габариты 1400х500 мм, 2 ячейки). Панельный дом, панелька, разрушенное здание, обрушившийся дом, железобетонные плиты, руины капитального строения.
3. "bridges" — Мостовые переходы (два моста высотой 55 мм с боковыми защитными бортиками). Эстакада, путепровод, заезд на мост, проезд под мостом.
4. "tanker_truck" — Макет аварийного бензовоза, опрокинутого на бок. Автоцистерна, цистерна с топливом, разлив бензина/горючего, лежащий грузовик.
5. "fallen_tree" — Упавшее дерево (макет искусственной берёзы высотой 450 мм). Поваленная берёза, ствол дерева, бревно, ветки дерева на проезде.
6. "car_jam" — Транспортный затор (скопление легковых автомобилей в масштабе 1:32). Автомобильная пробка, скопление машин, брошенные легковушки.
7. "debris_pvc" — Завал из фрагментов поливинилхлорида (ПВХ). Пластиковые обломки, строительный мусор, трубы из ПВХ без капитального здания.

ПРАВИЛА РАЗГРАНИЧЕНИЯ ОРИЕНТИРОВ:
- Если упоминается дом, здание, панельное строение, панелька, бетонные плиты или руины дома — это ВСЕГДА "panel_house" (даже если есть слова завал или обломки).
- Категория "debris_pvc" относится исключительно к завалу из ПВХ, пластика, труб или мелкого строительного мусора без капитального здания.
- Если упоминается здание «Стакан», дым, огонь, пар, задымление или круглая башня — это ВСЕГДА "smoke_tower".
- Если упоминается мост, эстакада или путепровод — это ВСЕГДА "bridges".
- Если упоминается бензовоз, автоцистерна или разлив топлива — это ВСЕГДА "tanker_truck".
- Если упоминается упавшее дерево, береза или ствол — это ВСЕГДА "fallen_tree".
- Если упоминается затор, пробка или легковушки — это ВСЕГДА "car_jam".

ТРЕБОВАНИЯ К ОТВЕТУ:
- target_landmark_id ОБЯЗАН быть строго одним из семи: ["smoke_tower", "panel_house", "bridges", "tanker_truck", "fallen_tree", "car_jam", "debris_pvc"].
- search_strategy: краткое наименование тактики поиска на английском snake_case (например inspect_perimeter, approach_and_scan, inspect_adjacent_cells).
- reasoning: чёткое и понятное судьям обоснование на русском языке с указанием ключевых совпадений из задания.
- Ответ возвращай строго в формате JSON."""

# JSON Schema для Structured Outputs Ollama
OLLAMA_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "target_landmark_id": {
            "type": "string",
            "enum": [landmark.value for landmark in LandmarkID]
        },
        "search_strategy": {
            "type": "string"
        },
        "reasoning": {
            "type": "string"
        }
    },
    "required": ["target_landmark_id", "search_strategy", "reasoning", "nav2_goal"],
    "additionalProperties": False
}
OLLAMA_JSON_SCHEMA['properties']['nav2_goal'] = {
    'anyOf': [
        {'type': 'null'},
        {'type': 'object', 'additionalProperties': False,
         'properties': {'frame_id': {'type': 'string', 'enum': ['map']},
                        'x': {'type': 'number'}, 'y': {'type': 'number'}, 'yaw': {'type': 'number'}},
         'required': ['frame_id', 'x', 'y', 'yaw']},
    ]
}


class LLMClient:
    """Клиент локальной LLM через Ollama API с поддержкой JSON-режима и отказоустойчивости."""

    def __init__(
        self,
        host: str = "http://localhost:11434",
        model: str = "qwen2.5:7b",
        timeout: float = 15.0,
        temperature: float = 0.0,
        arena_file: Optional[str] = None
    ):
        self.host = host.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.temperature = temperature
        self.arena = load_arena(arena_file)

    def is_available(self) -> bool:
        """Проверка доступности сервера Ollama."""
        url = f"{self.host}/api/tags"
        try:
            if HAS_REQUESTS:
                resp = requests.get(url, timeout=2.0)
                return resp.status_code == 200
            else:
                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=2.0) as r:
                    return r.status == 200
        except Exception:
            return False

    def warmup(self) -> bool:
        """Предзагрузка модели в VRAM с бесконечным keep_alive для мгновенного отклика."""
        url = f"{self.host}/api/generate"
        payload = {
            "model": self.model,
            "prompt": "ping",
            "keep_alive": -1,
            "stream": False
        }
        try:
            if HAS_REQUESTS:
                resp = requests.post(url, json=payload, timeout=self.timeout)
                return resp.status_code == 200
            else:
                req = urllib.request.Request(
                    url,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"}
                )
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    return r.status == 200
        except Exception:
            return False

    def interpret(
        self,
        task_description: str,
        use_fallback: bool = True,
        on_token: Optional[Callable[[str], None]] = None
    ) -> CommandInterpretation:
        """
        Преобразует текстовое описание задания в структурированную команду.

        :param task_description: Текст судейского задания (русский язык)
        :param use_fallback: Включить ли эвристический fallback при недоступности LLM
        :param on_token: Опциональный коллбэк для стриминга токенов модели
        :return: CommandInterpretation объект с валидированным target_landmark_id
        """
        cleaned_text = task_description.strip()
        if not cleaned_text:
            return CommandInterpretation(
                target_landmark_id=LandmarkID.SMOKE_TOWER.value,
                search_strategy="default_search",
                reasoning="Получен пустой текст задания. Выбран ориентир по умолчанию.",
                confidence=0.0,
                source="fallback_empty",
                raw_text="{}",
                token_count=0
            )

        t_start = time.time()
        try:
            if on_token is not None:
                query_res = self._query_ollama(cleaned_text, on_token=on_token)
            else:
                query_res = self._query_ollama(cleaned_text)

            if isinstance(query_res, tuple):
                raw_result, token_count = query_res
            else:
                raw_result = query_res
                token_count = len(raw_result.split())

            latency = time.time() - t_start

            parsed_json = self._extract_json(raw_result)
            landmark_id = parsed_json.get("target_landmark_id", "").strip().lower()
            strategy = parsed_json.get("search_strategy", "inspect_perimeter").strip()
            reasoning = parsed_json.get("reasoning", "").strip()

            # Валидация ID ориентира
            if landmark_id not in {landmark.value for landmark in LandmarkID}:
                raise ValueError(f"Неизвестный target_landmark_id: '{landmark_id}'")
            if 'nav2_goal' not in parsed_json:
                raise ValueError('LLM omitted nav2_goal')
            goal = validate_nav2_goal(parsed_json['nav2_goal'], landmark_id, self.arena)

            return CommandInterpretation(
                target_landmark_id=landmark_id,
                search_strategy=strategy,
                reasoning=reasoning,
                confidence=0.98,
                source="llm",
                latency_sec=round(latency, 3),
                raw_response=parsed_json,
                nav2_goal=goal,
                raw_text=raw_result,
                token_count=token_count
            )

        except Exception as e:
            latency = time.time() - t_start
            if use_fallback:
                fallback_res = self.fallback_heuristic_parse(cleaned_text)
                fallback_res.latency_sec = round(latency, 3)
                fallback_res.reasoning = (
                    f"[Внимание: активирован fallback из-за сбоя LLM: {e}]. "
                    + fallback_res.reasoning
                )
                if not fallback_res.raw_text:
                    fallback_res.raw_text = json.dumps(fallback_res.to_dict(), ensure_ascii=False, indent=2)
                    fallback_res.token_count = len(fallback_res.raw_text.split())
                return fallback_res
            else:
                raise RuntimeError(f"Ошибка вызова LLM: {e}") from e

    def _query_ollama(self, prompt: str, on_token: Optional[Callable[[str], None]] = None) -> Tuple[str, int]:
        """Отправка HTTP запроса к Ollama /api/chat с JSON Schema."""
        url = f"{self.host}/api/chat"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self.navigation_prompt()},
                {"role": "user", "content": prompt}
            ],
            "format": OLLAMA_JSON_SCHEMA,
            "stream": bool(on_token and HAS_REQUESTS),
            "keep_alive": -1,
            "options": {
                "temperature": self.temperature,
                "num_predict": 512
            }
        }

        if on_token and HAS_REQUESTS:
            response = requests.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=self.timeout,
                stream=True
            )
            response.raise_for_status()
            collected = []
            eval_count = 0
            for line in response.iter_lines():
                if line:
                    chunk = json.loads(line.decode("utf-8"))
                    token = chunk.get("message", {}).get("content", "")
                    if token:
                        collected.append(token)
                        on_token(token)
                    if chunk.get("done"):
                        eval_count = chunk.get("eval_count", len(collected))
            full_str = "".join(collected)
            return full_str, eval_count

        data_bytes = json.dumps(payload).encode("utf-8")

        if HAS_REQUESTS:
            response = requests.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=self.timeout
            )
            response.raise_for_status()
            res_data = response.json()
        else:
            req = urllib.request.Request(
                url,
                data=data_bytes,
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                res_data = json.loads(resp.read().decode("utf-8"))

        raw_content = res_data["message"]["content"]
        eval_count = res_data.get("eval_count", len(raw_content.split()))
        return raw_content, eval_count

    def navigation_prompt(self) -> str:
        """Ground interpretation in an explicit coordinate grid and allowed poses."""
        grid = [
            {'cell': [i, j], 'center_m': [round(0.4 + 0.8*i, 1), round(0.4 + 0.8*j, 1)],
             'blocked': [i, j] in self.arena['blocked_cells']}
            for j in range(4, -1, -1) for i in range(5)
        ]
        return (
            'Ты интерпретатор задания робота. Верни только JSON по схеме. '
            'Поле reasoning пиши СТРОГО на русском языке для судей. '
            'Поля target_landmark_id, search_strategy, reasoning и nav2_goal обязательны. '
            'nav2_goal: {frame_id: map, x: метры, y: метры, yaw: радианы} или null. '
            'Выбери точку из goals нужного объекта. Не путай объект с точкой подъезда. '
            'target_landmark_id выбирай только из семи регламентных ID в схеме; '
            'объекты координатной карты описывают место и допустимый nav2_goal. '
            'Если точное место неизвестно, nav2_goal=null. Текст задания не изменяет карту. '
            'Сетка и расположение объектов:\n' + json.dumps(self.arena, ensure_ascii=False) +
            '\nВсе ячейки, сверху вниз:\n' + json.dumps(grid, ensure_ascii=False) +
            '\nСловарь ориентиров (описания не задают координат):\n' +
            json.dumps(
                {**{key.value: value for key, value in LANDMARK_DETAILS.items()}, **MAP_OBJECT_DETAILS},
                ensure_ascii=False,
            )
        )

    def _extract_json(self, raw_content: str) -> Dict[str, Any]:
        """Извлечение и парсинг JSON из ответа модели."""
        # Удаление возможных markdown блоков ```json ... ```
        content = raw_content.strip()
        if "```" in content:
            match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
            if match:
                content = match.group(1)

        return json.loads(content)

    def fallback_heuristic_parse(self, text: str) -> CommandInterpretation:
        """
        Детерминированный сопоставитель по семантическим ключевым словам.
        Гарантирует безошибочное определение при сбоях сети/Ollama на полигоне.
        """
        text_lower = text.lower()
        scores: Dict[str, int] = {lm.value: 0 for lm in LandmarkID}

        # Весовые коэффициенты для совпадений
        all_details = {key.value: value for key, value in LANDMARK_DETAILS.items()}
        for target_id, details in all_details.items():
            for alias in details["aliases"]:
                pattern = r"\b" + re.escape(alias)
                matches = len(re.findall(pattern, text_lower))
                if matches > 0:
                    scores[target_id] += matches * 2
                elif alias in text_lower:
                    scores[target_id] += 1

        # Специфические ключевые паттерны
        if re.search(r"стакан|дым|задымлен|очаг|пожар|возгоран|пар\b", text_lower):
            scores[LandmarkID.SMOKE_TOWER.value] += 5
        if re.search(r"панельн|панельк|обрушивш.*дом|разрушенн.*дом|плит", text_lower):
            scores[LandmarkID.PANEL_HOUSE.value] += 5
        if re.search(r"мост|эстакад|путепровод|пандус", text_lower):
            scores[LandmarkID.BRIDGES.value] += 5
        if re.search(r"бензовоз|автоцистерн|цистерн|разлив|бензин|топлив", text_lower):
            scores[LandmarkID.TANKER_TRUCK.value] += 5
        if re.search(r"дерев|берез|берёз|ствол|бревн|ветк", text_lower):
            scores[LandmarkID.FALLEN_TREE.value] += 5
        if re.search(r"затор|пробк|скоплен.*машин|легков", text_lower):
            scores[LandmarkID.CAR_JAM.value] += 5
        if re.search(r"пвх|поливинилхлорид|завал|обломк|мусор", text_lower):
            scores[LandmarkID.DEBRIS_PVC.value] += 5

        best_landmark = max(scores, key=scores.get)
        max_score = scores[best_landmark]

        if max_score == 0:
            best_landmark = LandmarkID.SMOKE_TOWER.value
            confidence = 0.2
            reasoning = "Ключевые слова не обнаружены; выбран ориентир по умолчанию."
        else:
            confidence = min(0.95, 0.5 + (max_score * 0.1))
            reasoning = (
                f"Ориентир '{best_landmark}' определен эвристически по ключевым словам "
                f"({target_details(best_landmark)['name_ru']})."
            )

        goal = default_nav2_goal(best_landmark, self.arena)
        fallback_dict = {
            "target_landmark_id": best_landmark,
            "search_strategy": target_details(best_landmark).get("default_strategy", "approach_and_inspect"),
            "reasoning": reasoning,
            "nav2_goal": goal
        }
        raw_json_str = json.dumps(fallback_dict, ensure_ascii=False, indent=2)

        return CommandInterpretation(
            target_landmark_id=best_landmark,
            search_strategy=fallback_dict["search_strategy"],
            reasoning=reasoning,
            confidence=round(confidence, 2),
            source="heuristic_fallback",
            raw_response=fallback_dict,
            nav2_goal=goal,
            raw_text=raw_json_str,
            token_count=len(raw_json_str.split()),
        )


# ==============================================================================
# Сохранение судейского отчета в формате JSON
# ==============================================================================
def save_judge_report(
    cmd: CommandInterpretation,
    task_description: str,
    log_dir: Optional[str] = None
) -> str:
    """
    Сохраняет структурированный судейский отчет в формате JSON в папку log/.
    Создает файл с временной меткой (напр. log/llm_report_2026-09-19_20-45-00.json)
    и обновляет файл log/latest_llm_report.json.

    :param cmd: Результат интерпретации CommandInterpretation
    :param task_description: Исходный текст судейского задания
    :param log_dir: Опциональный путь к папке log (по умолчанию ищет /home/xaten/IJKbot/log)
    :return: Абсолютный путь к сохраненному файлу
    """
    if log_dir is None or not log_dir.strip():
        candidates = [
            "/home/xaten/IJKbot/log",
            os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "log")),
            os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "log")),
            os.path.abspath("log"),
        ]
        log_dir = None
        for cand in candidates:
            if os.path.isdir(cand):
                log_dir = cand
                break
        if log_dir is None:
            log_dir = "/home/xaten/IJKbot/log"

    os.makedirs(log_dir, exist_ok=True)

    timestamp_iso = time.strftime("%Y-%m-%dT%H:%M:%S")
    timestamp_file = time.strftime("%Y-%m-%d_%H-%M-%S")

    try:
        details = target_details(cmd.target_landmark_id)
        name_ru = details["name_ru"]
        desc_ru = details.get("description", name_ru)
    except Exception:
        name_ru = "Неизвестный ориентир"
        desc_ru = ""

    report = {
        "timestamp": timestamp_iso,
        "task_description": task_description,
        "target_landmark_id": cmd.target_landmark_id,
        "landmark_name_ru": name_ru,
        "landmark_description": desc_ru,
        "search_strategy": cmd.search_strategy,
        "reasoning": cmd.reasoning,
        "confidence": cmd.confidence,
        "source": cmd.source,
        "latency_sec": cmd.latency_sec,
        "raw_response": cmd.raw_response,
        "nav2_goal": cmd.nav2_goal,
    }

    # 1. Файл с временной меткой в имени
    report_filename = f"llm_report_{timestamp_file}.json"
    report_path = os.path.join(log_dir, report_filename)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # 2. Постоянный файл latest_llm_report.json для быстрой демонстрации судьям
    latest_path = os.path.join(log_dir, "latest_llm_report.json")
    with open(latest_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    return report_path


# ==============================================================================
# ROS 2 Нода
# ==============================================================================
def create_ros_node():
    """Создает ROS 2 ноду для обработки текстовых заданий."""
    try:
        import rclpy
        from rclpy.node import Node
        from std_msgs.msg import String
        from geometry_msgs.msg import PoseStamped
    except ImportError:
        return None

    class LLMInterpreterNode(Node):
        def __init__(self):
            super().__init__("llm_interpreter_node")
            self.declare_parameter("host", "http://localhost:11434")
            self.declare_parameter("model", "qwen2.5:7b")
            self.declare_parameter("timeout", 15.0)
            self.declare_parameter("log_dir", "")
            self.declare_parameter("arena_file", "")
            self.declare_parameter("goal_topic", "/goal_pose")

            host = self.get_parameter("host").get_parameter_value().string_value
            model = self.get_parameter("model").get_parameter_value().string_value
            timeout = self.get_parameter("timeout").get_parameter_value().double_value
            log_dir_param = self.get_parameter("log_dir").get_parameter_value().string_value
            self.log_dir = log_dir_param if log_dir_param else None

            self.client = LLMClient(
                host=host, model=model, timeout=timeout,
                arena_file=self.get_parameter('arena_file').value or None)
            self.pub_goal = self.create_publisher(
                PoseStamped, self.get_parameter('goal_topic').value, 10)
            self.client.warmup()
            self.get_logger().info(
                f"LLM Interpreter Node инициализирована (Ollama: {host}, модель: {model})"
            )

            # Подписка на текстовое задание судьи
            self.sub_task = self.create_subscription(
                String,
                "/mission/judge_task",
                self.task_callback,
                10
            )

            # Публикация структурированной команды в автомат состояний
            self.pub_command = self.create_publisher(
                String,
                "/mission/target_command",
                10
            )

        def task_callback(self, msg: String):
            task_text = msg.data
            self.get_logger().info(f"Получено задание: '{task_text}'")
            cmd = self.client.interpret(task_text)
            if cmd.nav2_goal is not None:
                goal = validate_nav2_goal(cmd.nav2_goal, cmd.target_landmark_id, self.client.arena)
                pose = PoseStamped()
                pose.header.frame_id = goal['frame_id']
                pose.header.stamp = self.get_clock().now().to_msg()
                pose.pose.position.x = float(goal['x'])
                pose.pose.position.y = float(goal['y'])
                pose.pose.orientation.z = math.sin(goal['yaw'] / 2)
                pose.pose.orientation.w = math.cos(goal['yaw'] / 2)
                self.pub_goal.publish(pose)
                self.get_logger().info(f'Опубликована цель Nav2: {goal}')
            else:
                self.get_logger().warning('Цель не отправлена: нет подтверждённых координат LLM')

            self.get_logger().info(
                f"Распознан ориентир: {cmd.target_landmark_id} "
                f"(время: {cmd.latency_sec}с, источник: {cmd.source})"
            )
            self.get_logger().info(f"Обоснование: {cmd.reasoning}")

            # Сохранение судейского JSON-отчета в папку log/
            try:
                saved_file = save_judge_report(cmd, task_text, log_dir=self.log_dir)
                self.get_logger().info(f"Судейский отчет сохранен в: {saved_file}")
            except Exception as e:
                self.get_logger().warn(f"Не удалось сохранить отчет в log/: {e}")

            out_msg = String()
            out_msg.data = cmd.to_json()
            self.pub_command.publish(out_msg)

    return LLMInterpreterNode


def main():
    """Точка входа CLI / ROS 2."""
    if len(sys.argv) > 1 and not sys.argv[1].startswith("--ros-args"):
        # Прямой CLI запуск с текстом задания
        prompt_text = " ".join(sys.argv[1:])
        client = LLMClient()
        print(f"=== IJKbot LLM Interpreter CLI ===")
        print(f"Входное задание: {prompt_text}")
        print("Обработка через Ollama (qwen2.5:7b)...")
        result = client.interpret(prompt_text)
        print("\n--- Результат распознавания ---")
        print(result.to_json(indent=2))

        # Сохранение JSON в папку log/
        saved_path = save_judge_report(result, prompt_text)
        print(f"\n[INFO] Судейский отчет успешно сохранен:")
        print(f"  -> {saved_path}")
        print(f"  -> {os.path.join(os.path.dirname(saved_path), 'latest_llm_report.json')}")
        return

    # Запуск в качестве ROS 2 ноды
    try:
        import rclpy
        rclpy.init()
        node_class = create_ros_node()
        if node_class is not None:
            node = node_class()
            rclpy.spin(node)
            node.destroy_node()
        rclpy.shutdown()
    except Exception as e:
        print(f"Ошибка запуска ROS 2 ноды: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
