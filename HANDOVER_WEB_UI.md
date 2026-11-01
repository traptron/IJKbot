# HANDOVER_WEB_UI.md — Инструкция для AI-агента по разработке Web Control Center (`./ijk ui`)

> Актуальное состояние реализации на 01.11.2026:
> [HANDOVER_DIAGNOSTICS.md](HANDOVER_DIAGNOSTICS.md).
> Приведённый ниже первоначальный план уже реализован и расширен.

Этот документ описывает текущее состояние разработки веб-интерфейса управления мобильной платформой IJKbot, архитектурные решения, уже готовые компоненты и пошаговый план завершения работы для следующего агента.

---

## 1. Контекст задачи и текущий статус

- **Цель**: Реализовать графический пульт управления роботом в браузере (поддержка ноутбука и смартфона по Wi-Fi) поверх существующего консольного инструмента [`./ijk`](tools/ijk/cli.py).
- **Выбранный стек**: **Вариант 1 (aiohttp + HTML5 / CSS3 / Vanilla JS + WebSockets + ROS 2 publisher)**.
  - Никаких внешних CDN (Google Fonts, unpkg, cdnjs) — интерфейс должен работать на 100% автономно на изолированном соревновательном Wi-Fi роутере без доступа в интернет.
  - В Pixi-окружении (`/home/lev/.pixi/bin/pixi run -m /home/lev/ros2_jazzy/pixi.toml ...`) проверены и работают `aiohttp`, `rclpy`, `geometry_msgs`.
- **Созданная структура каталогов**:
  - `tools/ijk/web/`
    - `__init__.py` — экспортирует `start_web_server` (создан).
    - `server.py` — **в разработке** (aiohttp сервер, API, WebSockets, ROS 2 bridge).
    - `static/` — создана папка для статических файлов (`index.html`, `style.css`, `app.js`).

---

## 2. Архитектура Web Control Center

```text
[Смартфон / Ноутбук]
   │  ▲
   │  ├── HTTP GET / (index.html, CSS, JS)
   │  ├── WS /ws/teleop (джойстик: v, w каждые 50 мс, аварийный E-STOP)
   │  ├── WS /ws/logs (стриминг терминального вывода в реальном времени)
   │  └── REST API (/api/status, /api/profile/start, /api/profile/stop, /api/estop)
   ▼  │
[aiohttp сервер: tools/ijk/web/server.py]
   │
   ├── [ROS 2 Bridge Node: ijk_web_bridge]
   │     ├── Publisher /cmd_vel_joy (geometry_msgs/Twist) — ручное управление со стика
   │     ├── Publisher /cmd_vel_emergency (geometry_msgs/Twist) — мгновенный E-STOP (v=0, w=0)
   │     └── Watchdog таймер (350 мс таймаут: при обрыве Wi-Fi связь стопит робота)
   │
   └── [Profile Process Manager]
         ├── Запуск профилей (showcase, competition, teleop, mapping, bench и др.) как подпроцессов CLI
         └── Захват stdout/stderr и трансляция в кольцевой буфер и в WebSocket /ws/logs
```

---

## 3. Детальный план реализации файлов

### 3.1. `tools/ijk/web/server.py`
Файл должен содержать класс `ControlCenterServer` и функцию `start_web_server`:
1. **Инициализация ROS 2**:
   - `rclpy.init()` (если `not rclpy.ok()`).
   - Нода `ijk_web_bridge` с паблишерами:
     - `/cmd_vel_joy` (`geometry_msgs.msg.Twist`, QoS 10)
     - `/cmd_vel_emergency` (`geometry_msgs.msg.Twist`, QoS 10)
   - Watchdog: асинхронный таск в `asyncio`, проверяющий `time.time() - last_cmd_time > 0.35`. Если превышен и робот двигался — отправка нулевой скорости.
2. **Менеджер подпроцессов профилей**:
   - Атрибуты: `self.active_profile: Optional[str]`, `self.active_proc: Optional[subprocess.Popen]`, `self.log_history = deque(maxlen=300)`.
   - Запуск профиля: `python3 tools/ijk/cli.py <profile_name> [--mock] [--host ...]`.
   - Фоновое асинхронное чтение строк вывода и отправка подключенным клиентам через `_broadcast_log(line)`.
3. **Эндпоинты**:
   - `GET /` — отдает `static/index.html`.
   - `GET /static/{filename}` — раздача статики (`web.static('/static', STATIC_DIR)`).
   - `GET /api/status` — возвращает JSON:
     ```json
     {
       "robot_ip": "10.197.37.154",
       "ssh_online": true,
       "tmux_running": false,
       "active_profile": null,
       "domain_id": 42,
       "mock": false
     }
     ```
   - `POST /api/profile/start` — запуск профиля (`{"profile": "showcase" | "teleop" | "mapping" | ...}`).
   - `POST /api/profile/stop` — остановка текущего процесса профиля.
   - `POST /api/estop` — немедленная отправка Twist(0,0) в `/cmd_vel_emergency` и `/cmd_vel_joy`, завершение активного процесса и вызов `runner.emergency_stop()`.
   - `POST /api/discovery` — перезапуск автопоиска робота по сети.
   - `POST /api/ops/{action}` — выполнение команд обслуживания (`timesync`, `save-map`, `wifi`).
   - `GET /ws/teleop` — WebSocket для тач-джойстика:
     - Клиент шлет: `{"type": "twist", "v": 0.15, "w": -0.3}` или `{"type": "estop"}`.
     - Публикация в ROS 2 и обновление watchdog.
   - `GET /ws/logs` — WebSocket для трансляции логов:
     - При подключении отдает клиенту накопленный `log_history`.
     - Далее шлет новые сообщения по мере поступления.

### 3.2. `tools/ijk/web/static/index.html`
- Мета-тег viewport: `<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">` (чтобы предотвратить случайный зум при работе с джойстиком на смартфонах).
- **Header**:
  - Логотип `IJKbot Mission Control`.
  - Индикаторы статуса (Robot IP, DDS Domain: 42, Tmux/ROS, Active Profile).
  - Большая кнопка `🛑 E-STOP` (видна всегда).
- **Навигация по табам**:
  1. `🕹️ Teleop & Profiles` (Джойстик + быстрый запуск профилей)
  2. `🧪 Hardware Bench` (Тесты моторов, лидара, камеры, QR, одометрии)
  3. `⚙️ Ops & Config` (Синхронизация времени Chrony, Wi-Fi, карты)
  4. `📜 Logs` (Окно живых логов терминала)
- **Таб Teleop & Profiles**:
  - Карточки запуска: Showcase, Competition, Teleop, Mapping, Navigate с кнопками Start/Stop.
  - Виртуальный тач-джойстик (круг-основа и бегунок-стик).
  - Индикаторы текущих скоростей: `V: 0.00 m/s`, `W: 0.00 rad/s`.
  - Слайдер настройки лимита скорости ($V_{max}$ от 0.05 до 0.35 м/с).
  - Кнопки дискретного управления (Вперед, Назад, Влево, Вправо, Стоп).

### 3.3. `tools/ijk/web/static/style.css`
- Dark High-Contrast Cyber / Tactical тема (`#0d1117`, `#161b22`, акценты `#58a6ff`, `#3fb950`, `#da3633`).
- Оптимизация под тач-устройства (`touch-action: none` на джойстике, `user-select: none`).
- Адаптивная сетка (CSS Grid / Flexbox) для удобного отображения как на мониторе 1920×1080, так и на мобильных дисплеях 390×844.

### 3.4. `tools/ijk/web/static/app.js`
- **Virtual Joystick**:
  - Обработка `pointerdown`, `pointermove`, `pointerup` (или `touchstart`, `touchmove`, `touchend`).
  - Расчет нормализованных смещений $\Delta x, \Delta y$ с ограничением максимального радиуса $R$.
  - Отправка твиста через WebSocket `/ws/teleop` с частотой ~20 Гц (троттлинг 50 мс).
  - При отпускании пальца возврат стика в центр $(0, 0)$ и отправка нулевого твиста.
- **WebSocket Logs**:
  - Подключение к `/ws/logs`, автоскролл вниз, кнопка паузы и очистки.
- **Управление состоянием**:
  - Периодический опрос `/api/status` каждые 2 секунды (или уведомления по сокету) для обновления плашек статуса.

### 3.5. Интеграция в CLI (`tools/ijk/cli.py`)
1. Добавить подкоманду `ui` в `argparse`:
   ```python
   p_ui = subparsers.add_parser("ui", help="Запустить Web Control Center (пульт в браузере)")
   p_ui.add_argument("--port", type=int, default=8080, help="Порт веб-сервера (по умолчанию 8080)")
   p_ui.add_argument("--host", type=str, default="0.0.0.0", help="Хост (по умолчанию 0.0.0.0)")
   p_ui.add_argument("--no-browser", action="store_true", help="Не открывать вкладку браузера автоматически")
   ```
2. Добавить пункт в `show_interactive_menu()`:
   ```text
   13) ui           — Web Control Center (пульт в браузере/со смартфона)
   ```
3. Обработчик вызова:
   ```python
   elif command == "ui":
       from tools.ijk.web.server import start_web_server
       start_web_server(
           config,
           host=getattr(args, "host", "0.0.0.0"),
           port=getattr(args, "port", 8080),
           no_browser=getattr(args, "no_browser", False),
           robot_ip=robot_ip,
           mock=args.mock,
           local=args.local,
       )
   ```

---

## 4. Критические правила и ограничения

1. **Не изменять 18 файлов с пользовательскими IP**:
   - `scripts/*.sh` и исходники `src/` с фиксированными IP не трогать.
2. **Безопасность приводов STS3215**:
   - Кнопка **E-STOP** должна отправлять аварийный нулевой твист в `/cmd_vel_emergency` (наивысший приоритет в `twist_mux.yaml`).
   - На сервере должен работать watchdog: при потере пакетов от веб-клиента моторы обязаны остановиться через 350 мс.
3. **Автономность**:
   - Никаких внешних ссылок `<script src="https://...">` или CDN шрифтов. Всё должно быть встроено в `tools/ijk/web/static/`.

---

## 5. Команды для верификации

После создания файлов следующий агент должен проверить:
1. Запуск синтаксической проверки и тестов:
   ```bash
   /home/lev/.pixi/bin/pixi run -m /home/lev/ros2_jazzy/pixi.toml python3 -m py_compile tools/ijk/web/server.py
   /home/lev/.pixi/bin/pixi run -m /home/lev/ros2_jazzy/pixi.toml pytest tests/test_ijk_cli.py
   ```
2. Написание теста `tests/test_ijk_ui.py`:
   - Проверка инициализации aiohttp приложения и доступности эндпоинтов `/api/status`, `/static/...`.
3. Тестовый запуск `./ijk ui --mock --no-browser`:
   - Убедиться, что сервер стартует на `0.0.0.0:8080`, отдает HTML и корректно завершается по Ctrl+C.
