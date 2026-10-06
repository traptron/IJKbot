# Комплексный критический аудит кодовой базы IJKbot (ROS 2 Jazzy)

**Дата проведения**: 26 сентября 2026 г.  
**Платформа**: ROS 2 Jazzy, Ubuntu 24.04 LTS, Python 3.12, C++17, Pixi  
**Объект аудита**: Полная кодовая база проекта IJKbot (`src/`, `scripts/`, `tests/`, документация)  
**Статус проверки тестов**: Все 6 пакетов (`brain`, `bringup`, `description`, `driver`, `nav2`, `vision`) собираются без ошибок; `colcon test` и `pytest tests/` (68 тестов) завершаются со статусом PASS.

---

## 1. Executive Summary & Audit Scorecard

Проект **IJKbot** представляет собой развитую робототехническую систему для соревнований «Эвакуация» (Кубок РТК Высшая Лига). Архитектура логично разделена на бортовую часть (Raspberry Pi 4B) и внебортовую станцию (ноутбук с GPU и LLM). Тестовое покрытие охватывает математику привода, протокол сервоприводов Feetech STS3215, одометрию, сценарии планирования и синхронизацию часов Chrony.

Тем не менее, в ходе глубокого статического и динамического анализа выявлены критические дефекты, способные привести к **полному срыву соревновательного заезда**, **штрафным баллам (-70 за столкновение)** или **падению процессов из-за ошибок доступа**:

### Сводная матрица дефектов

| Уровень важности | Количество | Ключевые области |
|---|:---:|---|
| **CRITICAL (P0)** | 6 | Запуск пустых подсистем в `mission_sm`, принудительный mock-режим в `system.launch.py`, привязка FSM к вкладке браузера, коллизия задней части шасси (-70 баллов), отсутствие сжатия видео по Wi-Fi, вечная блокировка UART при 100 мс помехе |
| **HIGH (P1)** | 7 | Блокировка потока ROS 2 при вызове `start_mission()`, дублирование дерева `src/brain/` с падением `arena.json`, чужие пути (`/home/xaten`, `/home/lev`), гонка потоков в NiceGUI UI, потеря флага `--model` в bash, конфликт топиков телеуправления `/cmd_vel_sm`, захардкоженные IP/SSH |
| **MEDIUM (P2)** | 7 | Преждевременный `kill -9` в `start_all_laptop2.sh`, отсечение QR-кодов в движении, нерабочие команды в `README.md`, рассинхронизация Mermaid диаграммы FSM, фантомные файлы моделей WeChat QR в README, нестыковка IP Chrony шлюза, запуск RViz без `start_marker` |
| **LOW (P3)** | 3 | Мертвый некомпилируемый код `node.cpp`, устаревшие пути `.vscode/settings.json`, нестыковка лимита угловой скорости $\omega_{max}$ (1.0 vs 2.0 рад/с) |
| **ИТОГО** | **23 дефекта** | **Полная ревизия бортового и внебортового стека** |

---

## 2. Критические дефекты (P0 — Critical / Run Killers)

### 2.1. `SystemLauncher.start()` запускает «призрачный» стек и дубликат дашборда вместо приводов и навигации
- **Файлы**:
  - [`src/brain/mission_sm.py`](file:///home/lev/IJKbot/src/brain/mission_sm.py#L320-L343)
  - [`src/bringup/launch/system.launch.py`](file:///home/lev/IJKbot/src/bringup/launch/system.launch.py#L110-L125)
- **Суть проблемы**:
  В `system.launch.py` аргументы `enable_robot` и `enable_nav` по умолчанию установлены в `'false'`, тогда как `enable_brain` по умолчанию равен `'true'`:
  ```python
  # src/bringup/launch/system.launch.py:110-125
  declare_enable_brain = DeclareLaunchArgument('enable_brain', default_value='true')
  declare_enable_nav = DeclareLaunchArgument('enable_nav', default_value='false')
  declare_enable_robot = DeclareLaunchArgument('enable_robot', default_value='false')
  ```
  В методе `SystemLauncher.start()` (вызываемом по кнопке «Запустить стек робота и Nav2» или «ВСЁ В 1 КЛИК» в веб-дашборде) формируется команда:
  ```python
  # src/brain/mission_sm.py:325-326 (SSH) и 336-341 (local)
  ros2 launch bringup system.launch.py mock_hardware:={mock_str} initial_x:={initial_x} ...
  ```
  Команда **не передает** `enable_robot:=true` и `enable_nav:=true`!
- **Последствия**:
  1. Базовый стек робота (`robot.launch.py` — драйвер STS3215, камера RealSense, лазерскан) **не запускается вовсе**.
  2. Навигация Nav2 (`navigation.launch.py`) **не запускается вовсе**.
  3. `system.launch.py` запускает `dashboard_app` (`mission_state_machine`), порождая **второй параллельный экземпляр веб-сервера** на порту 8080, что вызывает конфликт `Address already in use` и хаос в ROS 2 топиках.
- **Рекомендация**:
  В `mission_sm.py` явно передавать параметры:
  ```python
  "enable_robot:=true", "enable_nav:=true", "enable_brain:=false"
  ```
  Либо вызывать `robot.launch.py` и `navigation.launch.py` напрямую.

---

### 2.2. Такт конечного автомата (`sm.step`) привязан к жизненному циклу страницы веб-браузера
- **Файл**: [`src/brain/mission_sm.py`](file:///home/lev/IJKbot/src/brain/mission_sm.py#L2162-L2166,L2354,L2425-L2436)
- **Суть проблемы**:
  Вызов `sm.step(dt=0.1)` находится исключительно внутри функции `update_dashboard()`, которая зарегистрирована через `ui.timer(0.1, update_dashboard)`:
  ```python
  # src/brain/mission_sm.py:2162-2166
  def update_dashboard():
      sm.step(dt=0.1)
      ...
  ui.timer(0.1, update_dashboard) # L2354
  ```
  Этот таймер объявлен внутри функции `build_judge_dashboard(sm)`, которая вызывается в контексте страницы `@ui.page('/')`:
  ```python
  # src/brain/mission_sm.py:2425-2427
  @ui.page('/')
  def index():
      build_judge_dashboard(sm)
  ```
- **Последствия**:
  1. В NiceGUI функция под `@ui.page('/')` создается **на каждое подключение клиента**.
  2. **Если браузер не открыт**: страница не инстанциируется, таймер не создается, `sm.step(0.1)` **никогда не вызывается**. Робот не выполняет миссию.
  3. **Если открыто две вкладки браузера** (или оператор открыл дашборд с ноутбука, а судья со смартфона/планшета): создаются **два параллельных таймера**, каждый из которых вызывает `sm.step(0.1)` с частотой 10 Гц. Суммарная частота тиков автомата удваивается до 20 Гц, таймеры ожидания (например, `WAIT_5_SECONDS`) истекают в 2 раза быстрее реального времени, нарушая регламент соревнований!
- **Рекомендация**:
  Вынести шаг автомата `sm.step()` в независимый фоновый поток Python (`threading.Thread`) или фоновый `asyncio.Task` приложения (используя `app.on_startup`), независимый от количества подключенных веб-клиентов. Функция `update_dashboard` в UI должна только считывать текущее состояние `sm` и отрисовывать виджеты.

---

### 2.3. Геометрия Nav2 footprint оставляет 10 мм выступающего шасси сзади (Риск штрафа -70 баллов)
- **Файлы**:
  - [`src/nav2/config/nav2_params.yaml`](file:///home/lev/IJKbot/src/nav2/config/nav2_params.yaml#L125,L155)
  - [`src/description/urdf/ijkbot.urdf.xacro`](file:///home/lev/IJKbot/src/description/urdf/ijkbot.urdf.xacro#L10-L12,L28-L41)
  - [`src/description/urdf/ijkbot.urdf`](file:///home/lev/IJKbot/src/description/urdf/ijkbot.urdf#L17-L31)
- **Суть проблемы**:
  В `nav2_params.yaml` для локального и глобального costmap задан полигон footprint:
  ```yaml
  footprint: "[[0.11, 0.125], [0.11, -0.125], [-0.17, -0.125], [-0.17, 0.125]]"
  ```
  При этом физическая модель корпуса в `ijkbot.urdf.xacro` имеет следующие размеры и смещение:
  ```xml
  <xacro:property name="chassis_length" value="0.220"/>
  <!-- ... -->
  <link name="base_link">
    <origin xyz="-0.07 0 0.03" rpy="0 0 0"/>
    <box size="0.220 0.160 0.080"/>
  ```
  Задняя грань шасси робота находится в точке:
  $$X_{rear} = -0.07 - \frac{0.220}{2} = -0.07 - 0.110 = -0.180\text{ м}$$
  В конфигурации Nav2 граница footprint по оси $X$ сзади указана как **$-0.170$ м**.
- **Последствия**:
  Задняя часть корпуса робота **выступает на 10 мм за пределы зоны коллизий Nav2**. При вращении на месте или маневрировании задним ходом в узких лабиринтах полигона планировщик Nav2 допускает сближение с препятствием до границы $-0.17$ м, что приводит к физическому задеванию стены или объекта полигона задней частью шасси робота. В регламенте зафиксировано: **«Столкновение/касание с объектом полигона: -70 баллов (Критично: любое касание штрафуется жестко!)»**.
- **Рекомендация**:
  Увеличить габариты footprint в `nav2_params.yaml`:
  ```yaml
  footprint: "[[0.12, 0.13], [0.12, -0.13], [-0.19, -0.13], [-0.19, 0.13]]"
  ```
  Это обеспечит необходимый запас безопасности в 10 мм со всех сторон.

---

### 2.4. Отсутствие ноды компрессии видео (`image_transport`) на борту робота
- **Файлы**:
  - [`src/bringup/launch/realsense_laserscan.launch.py`](file:///home/lev/IJKbot/src/bringup/launch/realsense_laserscan.launch.py#L40-L56)
  - [`src/vision/config/qr_reader.yaml`](file:///home/lev/IJKbot/src/vision/config/qr_reader.yaml#L3)
  - [`AGENTS.md`](file:///home/lev/IJKbot/AGENTS.md#L66-L67)
- **Суть проблемы**:
  В `AGENTS.md` зафиксировано жесткое архитектурное требование:
  > *«Запрещено передавать сырые PointCloud2 или несжатое видео по Wi-Fi. Видео передается исключительно через image_transport/compressed (JPEG, 640×480)»*.
  
  Нода компьютерного зрения `qr_reader_node` слушает топик:
  ```yaml
  image_topic: "/camera/color/image_raw/compressed"
  ```
  Однако в `realsense_laserscan.launch.py` запускается только официальный `rs_launch.py` пакета `realsense2_camera`. Если на Raspberry Pi не установлен плагин `image_transport_plugins` или не запущена нода `image_transport republish`, топик `/camera/color/image_raw/compressed` **не публикуется**.
- **Последствия**:
  Нода зрения `qr_reader` на ноутбуке остается без видеопотока, не считывает QR-код пострадавшего (`+80` баллов теряются), а если передается сырой поток `/camera/color/image_raw` (27 МБ/с при 640×480×30fps), беспроводной канал Wi-Fi перегружается, вызывая лаги в управлении `/cmd_vel` и рассинхронизацию часов Chrony.
- **Рекомендация**:
  Добавить в `realsense_laserscan.launch.py` запуск ноды `republish`:
  ```python
  Node(
      package='image_transport',
      executable='republish',
      arguments=['raw', 'in:=/camera/color/image_raw', 'compressed', 'out:=/camera/color/image_raw'],
  )
  ```

---

### 2.5. Сверхчувствительный Watchdog драйвера моторов и вечный `latchFault`
- **Файл**: [`src/driver/src/diff_drive_node.cpp`](file:///home/lev/IJKbot/src/driver/src/diff_drive_node.cpp#L109-L117,L196-L201,L258-L263)
- **Суть проблемы**:
  В коде драйвера жестко константой задан лимит ошибок передачи данных по UART:
  ```cpp
  constexpr std::size_t kMaxErrorStreak = 5;
  ```
  Таймер опроса энкодеров и отправки скоростей работает с частотой **50 Гц** (период 20 мс). Если подряд происходят 5 ошибок чтения или записи (например, электромагнитная помеха от стартующего мотора или задержка в буфере USB-UART переходника), драйвер немедленно переходит в состояние ошибки:
  ```cpp
  // src/driver/src/diff_drive_node.cpp:197-200
  if (error_streak_ >= kMaxErrorStreak) {
      latchFault(std::string("UART feedback failed after ") +
                 std::to_string(error_streak_) + " retries: " + error.what());
      return;
  }
  ```
  А в методе `latchFault`:
  ```cpp
  fault_ = true;
  RCLCPP_ERROR(get_logger(), "Drive fault; motion locked until restart: %s", reason.c_str());
  ```
- **Последствия**:
  Пять потерянных пакетов при 50 Гц соответствуют временному сбою длительностью всего **100 миллисекунд (0.1 сек)**. После этого робот намертво блокирует движение («motion locked until restart»), и в коде **нет ни сервиса сброса ошибки (reset fault), ни попытки переподключения**. Миссия безвозвратно прерывается прямо на полигоне из-за кратковременной помехи.
- **Рекомендация**:
  1. Увеличить `kMaxErrorStreak` минимум до 15–20 (300–400 мс) либо сделать его настраиваемым через `params.yaml`.
  2. Добавить механизм автоматического восстановления (recovery): если связь восстановилась, сбрасывать `fault_ = false` и обнулять `error_streak_`.
  3. Добавить ROS 2 сервис `std_srvs/srv/Trigger` для удаленного программного сброса аварии оператором с дашборда.

---

### 2.6. `system.launch.py` запускает `dashboard_app` в принудительном режиме симуляции (Mock)
- **Файлы**:
  - [`src/bringup/launch/system.launch.py`](file:///home/lev/IJKbot/src/bringup/launch/system.launch.py#L159-L169)
  - [`src/brain/mission_sm.py`](file:///home/lev/IJKbot/src/brain/mission_sm.py#L2367-L2368,L2400)
- **Суть проблемы**:
  В `system.launch.py` объявлен аргумент `mock_hardware` (по умолчанию `'false'`). Однако при создании ноды `brain_node` (`dashboard_app`) передаются только аргументы:
  ```python
  arguments=['--host', '0.0.0.0', '--port', '8080', '--llm-host', LaunchConfiguration('llm_host')]
  ```
  Флаг `--mock` или `--no-mock` не передается вовсе. В функции `main()` файла `mission_sm.py` аргумент `--mock` имеет значение по умолчанию `True`:
  ```python
  parser.add_argument("--mock", action="store_true", default=True, help="Запуск в режиме симуляции")
  parser.add_argument("--no-mock", dest="mock", action="store_false", help="Запуск с реальным ROS 2 железом")
  ```
- **Последствия**:
  При запуске через `system.launch.py` (даже если пользователь явно передает `mock_hardware:=false`), нода `mission_state_machine` инициализируется с `self.mock_mode = True`:
  1. В `_odom_callback` (строки 1304–1305) нода **полностью игнорирует реальные сообщения `/odom`** от приводов.
  2. В фазе поиска пострадавшего `_handle_spin_and_scan` (строки 922–927) физический робот **не отправляет команды вращения на моторы**, а лишь вращает виртуальный угол в памяти.
- **Рекомендация**:
  В `system.launch.py` пробросить аргумент `--mock`:
  ```python
  arguments=[
      '--host', '0.0.0.0',
      '--port', '8080',
      '--llm-host', LaunchConfiguration('llm_host'),
      '--mock', LaunchConfiguration('mock_hardware'),
  ]
  ```

---

## 3. Дефекты высокой важности (P1 — High Severity)

### 3.1. Чужие жестко закодированные абсолютные пути пользователей (`xaten`, `lev`, `chumohod`)
- **Файлы**:
  - [`src/brain/llm_client.py`](file:///home/lev/IJKbot/src/brain/llm_client.py#L773,L784)
  - [`src/vision/vision/qr_reader_node.py`](file:///home/lev/IJKbot/src/vision/vision/qr_reader_node.py#L125)
  - [`.vscode/settings.json`](file:///home/lev/IJKbot/.vscode/settings.json#L2)
- **Суть проблемы**:
  В `llm_client.py` при сохранении судейского лога путь задан жестко с запасным fallback:
  ```python
  # src/brain/llm_client.py:772-785
  candidates = [
      "/home/xaten/IJKbot/log",
      os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "log")),
      # ...
  ]
  # ...
  if log_dir is None:
      log_dir = "/home/xaten/IJKbot/log"
  os.makedirs(log_dir, exist_ok=True)
  ```
  Если папка `log` не была предварительно создана, код пытается выполнить `os.makedirs("/home/xaten/IJKbot/log")`.
  Аналогично в `qr_reader_node.py:125`:
  ```python
  repo_log = '/home/lev/IJKbot/log'
  ```
  А в `.vscode/settings.json`:
  ```json
  "cmake.sourceDirectory": "/home/chumohod/IJKbot/sts3215_driver"
  ```
- **Последствия**:
  На любом компьютере или на Raspberry Pi (где пользователь `otmorozki` или `ubuntu`), вызов `save_run_log` падает с исключением:
  `PermissionError: [Errno 13] Permission denied: '/home/xaten'`.
- **Рекомендация**:
  Использовать относительные пути относительно расположения пакета или стандартную переменную окружения:
  ```python
  log_dir = os.environ.get("IJKBOT_LOG_DIR", os.path.abspath("log"))
  ```

---

### 3.2. Нарушение потоковой модели NiceGUI при обращении к UI из фонового треда
- **Файл**: [`src/brain/mission_sm.py`](file:///home/lev/IJKbot/src/brain/mission_sm.py#L1720-L1733)
- **Суть проблемы**:
  В обработчике `handle_llm_parse` для избежания блокировки веб-сервера запускается тред:
  ```python
  def _worker():
      try:
          interp = sm.parse_task_with_llm(on_token=on_token_cb)
          ui.notify(f"Задание успешно распознано...", type="positive")
      except Exception as ex:
          ui.notify(f"Ошибка LLM: {ex}", type="negative")
      finally:
          llm_parse_btn.props(remove="loading")

  threading.Thread(target=_worker, daemon=True).start()
  ```
  Методы `ui.notify(...)` и мутация свойств виджетов `llm_parse_btn.props(...)` вызываются **напрямую из параллельного потока ОС**, в обход asyncio event loop NiceGUI.
- **Последствия**:
  Периодически вызывает `RuntimeError: There is no current event loop in thread` или приводит к повреждению внутреннего состояния WebSocket-соединения NiceGUI, приводя к зависанию интерфейса на экране судей.
- **Рекомендация**:
  Использовать встроенный асинхронный механизм NiceGUI `run.io_bound`:
  ```python
  interp = await run.io_bound(sm.parse_task_with_llm, on_token=on_token_cb)
  ui.notify(...)
  llm_parse_btn.props(remove="loading")
  ```

---

### 3.3. Параметр `--model` в `start_all_laptop1.sh` парсится, но теряется при вызове `laptop.launch.py`
- **Файлы**:
  - [`scripts/start_all_laptop1.sh`](file:///home/lev/IJKbot/scripts/start_all_laptop1.sh#L87-L95,L259-L264)
  - [`src/bringup/launch/laptop.launch.py`](file:///home/lev/IJKbot/src/bringup/launch/laptop.launch.py#L29-L65,L77-L83)
- **Суть проблемы**:
  В `start_all_laptop1.sh` опция `--model <NAME>` корректно считывается (строка 93) и валидируется через Ollama API (строка 222), однако в строке 259 формируется команда:
  ```bash
  LAUNCH_CMD="source '${SETUP_BASH}' && ros2 launch bringup laptop.launch.py \
      llm_host:='${LLM_HOST}' \
      port:='${PORT}' \
      host:='${HOST}' \
      mock:='${MOCK}' \
      enable_vision:='${ENABLE_VISION}'"
  ```
  Аргумент `llm_model` вообще не передается! Более того, в самом файле `laptop.launch.py` запускной аргумент `llm_model` даже **не объявлен** (`DeclareLaunchArgument('llm_model')` отсутствует).
- **Последствия**:
  Если оператор запускает `./scripts/start_all_laptop1.sh --model qwen2.5:7b`, система полностью игнорирует указанную модель и молча запускает модель по умолчанию `qwen3.5:9b`. Если этой дефолтной модели нет в Ollama на соревновательном ноутбуке, инференс падает.
- **Рекомендация**:
  1. Добавить `declare_llm_model = DeclareLaunchArgument('llm_model', default_value='qwen3.5:9b')` в `laptop.launch.py`.
  2. Передавать `--llm-model LaunchConfiguration('llm_model')` в аргументы `dashboard_node`.
  3. Передавать `llm_model:='${LLM_MODEL}'` в `LAUNCH_CMD` скрипта `start_all_laptop1.sh`.

---

### 3.4. Захват топика автомата состояний скриптом телеуправления `teleop.sh`
- **Файлы**:
  - [`scripts/teleop.sh`](file:///home/lev/IJKbot/scripts/teleop.sh#L47)
  - [`src/nav2/config/twist_mux.yaml`](file:///home/lev/IJKbot/src/nav2/config/twist_mux.yaml#L5-L16)
- **Суть проблемы**:
  В `twist_mux.yaml` сконфигурированы следующие каналы приоритетов:
  ```yaml
  topics:
    emergency:  { topic: /cmd_vel_emergency, priority: 100 }
    sm:         { topic: /cmd_vel_sm,        priority: 50 }
    navigation: { topic: /cmd_vel_nav,       priority: 10 }
  ```
  В `scripts/teleop.sh` (строка 47) топиком по умолчанию назначен:
  ```bash
  TARGET_TOPIC="/cmd_vel_sm"
  ```
  При этом отдельного канала `teleop` в `twist_mux.yaml` вообще нет.
- **Последствия**:
  Скрипт ручного управления публикует команды прямо в топик автомата состояний `/cmd_vel_sm` на том же приоритете 50. Если во время выполнения миссии оператор запускает `teleop.sh`, команды оператора и команды автомата состояний начинают интерферировать, перебивая друг друга.
- **Рекомендация**:
  Добавить в `twist_mux.yaml` выделенный канал:
  ```yaml
  teleop:
    topic: /cmd_vel_teleop
    timeout: 0.5
    priority: 80
  ```
  И переключить дефолтный топик в `teleop.sh` на `/cmd_vel_teleop`.

---

### 3.5. Жестко заданные IP-адрес и логин Raspberry Pi в коде State Machine
- **Файл**: [`src/brain/mission_sm.py`](file:///home/lev/IJKbot/src/brain/mission_sm.py#L280-L281)
- **Суть проблемы**:
  В классе `SystemLauncher` параметры подключения захардкожены в полях класса без возможности переопределения:
  ```python
  self.ssh_host: str = "192.168.1.10"
  self.ssh_user: str = "otmorozki"
  ```
- **Последствия**:
  При переходе на соревновательный роутер с другой адресацией, точку доступа смартфона (`172.22.35.x`) или при смене пользователя на Pi запуск бортового стека из дашборда становится невозможен без ручной правки исходного кода `mission_sm.py`.
- **Рекомендация**:
  Считывать значения из переменных окружения с фоллбеком:
  ```python
  self.ssh_host = os.environ.get("ROBOT_IP", "192.168.1.10")
  self.ssh_user = os.environ.get("ROBOT_USER", "otmorozki")
  ```

---

### 3.6. Синхронная блокировка потока ROS 2 и UI при вызове `start_mission()`
- **Файл**: [`src/brain/mission_sm.py`](file:///home/lev/IJKbot/src/brain/mission_sm.py#L684-L697)
- **Суть проблемы**:
  В методе `start_mission()` (вызываемом по кнопке дашборда «2. СТАРТ МИССИИ»):
  ```python
  def start_mission(self) -> None:
      with self.lock:
          # ...
          if not self.command_interpretation:
              if self.current_task_text:
                  self.parse_task_with_llm()
              else:
                  self.set_task_description(DEFAULT_TASK_EXAMPLE)
                  self.parse_task_with_llm()
  ```
  Вызов `parse_task_with_llm()` выполняется **внутри критической секции `with self.lock:`**. Метод `client.interpret()` делает синхронный сетевой HTTP-запрос к Ollama, длящийся от 1.5 до 8 секунд.
- **Последствия**:
  Пока удерживается `self.lock`, полностью блокируются:
  1. Коллбэк одометрии `_odom_callback`, работающий на частоте 50 Гц в фоновом треде `rclpy.spin()`.
  2. Все сетевые коллбэки E-STOP (`_estop_callback`). Робот не может быть остановлен кнопкой аварийного останова до завершения ответа Ollama.
  3. Цикл обновления интерфейса NiceGUI.
- **Рекомендация**:
  Вынести парсинг LLM за пределы критической секции `with self.lock:`, выполняя его асинхронно в фоновом потоке, как это сделано для кнопки «1. Распознать задание».

---

### 3.7. Параллельное дублирование исходного кода `src/brain/*.py` и `src/brain/brain/*.py`
- **Файлы**:
  - `src/brain/mission_sm.py` и `src/brain/brain/mission_sm.py`
  - `src/brain/llm_client.py` и `src/brain/brain/llm_client.py`
  - [`src/brain/brain/llm_client.py`](file:///home/lev/IJKbot/src/brain/brain/llm_client.py#L130-L137)
- **Суть проблемы**:
  В пакете `brain` одновременно присутствуют файлы в корне пакета `src/brain/` и в подпапке `src/brain/brain/`. В файле `src/brain/brain/llm_client.py:131` прописан относительный поиск конфигурации арены:
  ```python
  source = Path(__file__).resolve().parent / 'config' / 'arena.json'
  ```
  Для файла в подпапке `src/brain/brain/` путь `parent` равен `src/brain/brain`, а папка `config` находится на уровень выше (`src/brain/config`). В результате проверка `source.is_file()` возвращает `False`. Код пытается вызвать `get_package_share_directory('brain')`, и при запуске скрипта напрямую из исходников без сборки через `colcon` падает с исключением `PackageNotFoundError`.
- **Рекомендация**:
  Устранить дубликаты файлов, оставив чистую структуру Python-пакета (`src/brain/brain/` с правильными относительными путями `parent.parent / 'config' / 'arena.json'`).

---

## 4. Дефекты средней важности (P2 — Medium Severity)

### 4.1. Нерабочие команды проверки и сборки в `README.md`
- **Файл**: [`README.md`](file:///home/lev/IJKbot/README.md#L230-L231)
- **Суть проблемы**:
  1. В строке 230 приведена команда:
     ```bash
     ./scripts/check_velocity.py --cmd-v 0.2 --meas-v 0.19
     ```
     В `check_velocity.py` парсер аргументов ожидает `--linear` и `--measured-linear`. Команда из документации завершается с ошибкой `unrecognized arguments: --cmd-v 0.2 --meas-v 0.19`.
  2. В строке 231 приведена команда:
     ```bash
     ./scripts/update_pi.sh --build
     ```
     В `update_pi.sh` флаг `--build` отсутствует (сборка включена по умолчанию, а отключается флагом `--no-build`). Команда из документации завершается с ошибкой `[ERROR] Неизвестный аргумент: --build`.
- **Рекомендация**:
  Обновить документацию до реальных флагов CLI:
  ```bash
  ./scripts/check_velocity.py --linear 0.2 --measured-linear 0.19
  ./scripts/update_pi.sh
  ```

---

### 4.2. Рассинхронизация состояний автомата в Mermaid-диаграмме `README.md`
- **Файлы**:
  - [`README.md`](file:///home/lev/IJKbot/README.md#L131-L146)
  - [`src/brain/mission_sm.py`](file:///home/lev/IJKbot/src/brain/mission_sm.py#L116-L130)
- **Суть проблемы**:
  В Mermaid диаграмме `README.md` указаны состояния:
  `IDLE`, `WAITING_TASK`, `INTERPRETING_COMMAND`, `NAVIGATING_TO_ZONE`, `SEARCHING_VICTIM`, `CONFIRMING_QR`, `EVACUATING_VICTIM`, `RETURNING_HOME`, `MISSION_ACCOMPLISHED`, `FAILED`, `EMERGENCY_STOP`.
  
  В реальном enum `MissionState` кодовой базы определены:
  `PREPARATION`, `LLM_PARSING`, `READY_TO_START`, `NAVIGATING_TO_LANDMARK`, `SEARCHING_VICTIM`, `APPROACHING_VICTIM`, `WAIT_5_SECONDS`, `READING_QR`, `RETURNING_HOME`, `MISSION_COMPLETE`, `EMERGENCY_STOP`, `PAUSED`.
- **Последствия**:
  Более половины состояний из документации отсутствуют в кодовой базе. Судьи или разработчики вводятся в заблуждение относительно реальной логики работы робота.
- **Рекомендация**:
  Синхронизировать Mermaid-граф в `README.md` с актуальным `MissionState` enum.

---

### 4.3. Фантомные файлы весов WeChat QR в документации (при работающем OpenCV fallback)
- **Файлы**:
  - [`README.md`](file:///home/lev/IJKbot/README.md#L120)
  - [`src/vision/vision/qr_decoder.py`](file:///home/lev/IJKbot/src/vision/vision/qr_decoder.py#L64-L75)
- **Суть проблемы**:
  `README.md` заявляет:
  > *«Использует две нейросетевые модели WeChat (detect.caffemodel, sr.caffemodel), обеспечивая угол считывания до 35°»*.
  
  В коде `qr_decoder.py` вызывается конструктор `cv2.wechat_qrcode_WeChatQRCode()` без параметров. Самих бинарных файлов весов (`detect.caffemodel`, `sr.caffemodel`) на диске в репозитории нет. Хотя сборка OpenCV 4.10 в Linux успешно инициализирует базовый детектор WeChat и без этих файлов, нейросетевая супер-резолюция (SR) без весов Caffe не задействована, что снижает качество распознавания мелких QR-кодов на предельных углах и дистанциях.
- **Рекомендация**:
  Либо добавить реальные файлы весов `detect.caffemodel` и `sr.caffemodel` в `src/vision/models/` и передать пути к ним в конструктор, либо скорректировать формулировку в документации.

---

### 4.4. Путаница с IP-адресом шлюза Chrony-сервера мобильной точки доступа
- **Файлы**:
  - [`scripts/chrony/chrony_client.conf`](file:///home/lev/IJKbot/scripts/chrony/chrony_client.conf#L12)
  - [`scripts/start_all_laptop2.sh`](file:///home/lev/IJKbot/scripts/start_all_laptop2.sh#L39)
  - [`scripts/check_clock_sync.py`](file:///home/lev/IJKbot/scripts/check_clock_sync.py#L225)
- **Суть проблемы**:
  В `chrony_client.conf` (разворачиваемом на роботе) сервер времени прописан как:
  ```conf
  server 172.22.35.254 iburst minpoll 1 maxpoll 2
  ```
  В скриптах запуска резервный адрес робота (Pi) задан как `BACKUP_HOST="172.22.35.154"`. Если точка доступа на смартфоне выделяет ноутбуку адрес `172.22.35.1` или `172.22.35.100`, а не `.254`, клиент Chrony на роботе не сможет достучаться до сервера времени.
- **Рекомендация**:
  Убедиться, что в `chrony_client.conf` прописан реальный адрес ноутбука-сервера NTP в мобильной сети hotspot, и предусмотреть параметризацию через `setup_chrony.sh`.

---

### 4.5. `start_rviz.sh` не запускает ноду `start_marker` и использует несогласованный конфиг
- **Файлы**:
  - [`scripts/start_rviz.sh`](file:///home/lev/IJKbot/scripts/start_rviz.sh#L33-L36,L126)
  - [`src/nav2/launch/rviz.launch.py`](file:///home/lev/IJKbot/src/nav2/launch/rviz.launch.py#L13,L39-L51)
- **Суть проблемы**:
  Официальный лаунч-файл `rviz.launch.py` запускает не только `rviz2` с конфигурацией `nav2_view.rviz`, но и ноду `start_marker`, которая публикует маркер стартовой зоны в `/start_marker`.
  Скрипт `start_rviz.sh` запускает бинарник `rviz2` напрямую с другим файлом `nav2_default_view.rviz` и **не поднимает ноду start_marker**.
- **Последствия**:
  В окне RViz оператор не видит подсвеченной стартовой зоны полигона, так как нода `start_marker` не запущена.
- **Рекомендация**:
  В `start_rviz.sh` запускать `ros2 launch nav2 rviz.launch.py` вместо прямого вызова `pixi run rviz2`.

---

### 4.6. Привязка манифеста Pixi к домашней папке `/home/lev/`
- **Файлы**: Все скрипты в папке `scripts/` (`start_all_laptop1.sh`, `start_all_laptop2.sh`, `start_rviz.sh`, `teleop.sh`, `stop_all.sh` и т.д.)
- **Суть проблемы**:
  Во всех скриптах содержится жесткая дефолтная строчка:
  ```bash
  PIXI_MANIFEST="${PIXI_PROJECT_MANIFEST:-/home/lev/ros2_jazzy/pixi.toml}"
  ```
- **Последствия**:
  При клонировании репозитория любым другим участником команды под своим пользователем скрипты не смогут найти `pixi.toml` без предварительного ручного экспорта `PIXI_PROJECT_MANIFEST`.
- **Рекомендация**:
  Использовать поиск `pixi.toml` в `~/ros2_jazzy/pixi.toml` или относительно домашней папки текущего пользователя:
  ```bash
  PIXI_MANIFEST="${PIXI_PROJECT_MANIFEST:-${HOME}/ros2_jazzy/pixi.toml}"
  ```

### 4.7. Преждевременный `kill -9` в `start_all_laptop2.sh` лишает дочерние скрипты шанса мягкой остановки робота
- **Файл**: [`scripts/start_all_laptop2.sh`](file:///home/lev/IJKbot/scripts/start_all_laptop2.sh#L252-L257)
- **Суть проблемы**:
  В функции `cleanup_all()` процессам `start_robot_pi.sh` и `start_nav2_pi.sh` сразу посылается сигнал `SIGKILL` (`kill -9`).
- **Последствия**:
  Trap-обработчики дочерних bash-скриптов не успевают выполниться и не посылают команды остановки моторов на Pi по SSH. Если перед этим вызов `stop_all.sh` споткнулся о сетевой таймаут, робот продолжает неконтролируемое движение на полигоне.
- **Рекомендация**:
  Сначала посылать `kill -INT` / `kill -TERM`, делать паузу 0.5–1.0 сек, и только затем применять `kill -9`.

---

### 4.8. Отсечение кадров QR-кода фильтром состояний при движении к ориентиру
- **Файл**: [`src/vision/vision/qr_reader_node.py`](file:///home/lev/IJKbot/src/vision/vision/qr_reader_node.py#L56,L112-L116)
- **Суть проблемы**:
  В ноде зрения задан фильтр `self._allowed_states = ('SEARCHING_VICTIM', 'READING_QR')`. В состояниях движения `NAVIGATING_TO_LANDMARK` или `APPROACHING_VICTIM` распознанные QR-коды игнорируются.
- **Последствия**:
  Если робот увидел пострадавшего по пути к ориентиру, он не может зафиксировать код на ходу и тратит лишние 30–60 секунд на обязательный доезд до центра ячейки и круговой разворот (лимит миссии всего 5 минут).
- **Рекомендация**:
  Разрешить распознавание во всех активных состояниях движения или при обнаружении валидного QR немедленно переходить в `READING_QR`.

---

## 5. Дефекты низкой важности (P3 — Low Severity / Hygiene)

### 5.1. Мертвый некомпилируемый исходный код в драйвере
- **Файлы**:
  - [`src/driver/src/node.cpp`](file:///home/lev/IJKbot/src/driver/src/node.cpp)
  - [`src/driver/include/node.hpp`](file:///home/lev/IJKbot/src/driver/include/node.hpp)
- **Суть**:
  Файлы представляют собой черновой консольный тест для одного сервопривода с жестко прописанным портом `/dev/ttyACM0`. Они не включены в `CMakeLists.txt` пакета `driver` и не используются.
- **Рекомендация**:
  Удалить неиспользуемые файлы или перенести их в каталог `scripts/` / `tests/`.

---

### 5.2. Устаревший путь в конфигурации VS Code
- **Файл**: [`.vscode/settings.json`](file:///home/lev/IJKbot/.vscode/settings.json#L2)
- **Суть**:
  Указан устаревший несуществующий путь:
  ```json
  { "cmake.sourceDirectory": "/home/chumohod/IJKbot/sts3215_driver" }
  ```
- **Рекомендация**:
  Исправить на `"${workspaceFolder}/src/driver"`.

---

### 5.3. Несоответствие приоритетов `twist_mux` и радиуса инфляции в описании
- **Файлы**:
  - [`README.md`](file:///home/lev/IJKbot/README.md#L248-L253)
  - [`src/nav2/config/twist_mux.yaml`](file:///home/lev/IJKbot/src/nav2/config/twist_mux.yaml#L5-L16)
  - [`src/nav2/config/nav2_params.yaml`](file:///home/lev/IJKbot/src/nav2/config/nav2_params.yaml#L142)
- **Суть**:
  В `README.md` заявлено:
  - Приоритеты twist_mux: 255 (emergency), 100 (teleop), 50 (nav2). Реально в конфиге: 100 (emergency), 50 (sm), 10 (nav2).
  - Параметр `inflation_radius`: 0.30 м. Реально в `nav2_params.yaml`: 0.28 м.
- **Рекомендация**:
  Синхронизировать числовые значения в `README.md` с фактическими YAML-конфигами.

---

### 5.4. Несогласованность лимитов угловой скорости $\omega_{max}$ (1.0 vs 2.0 рад/с)
- **Файлы**:
  - [`README.md`](file:///home/lev/IJKbot/README.md#L59)
  - [`src/driver/config/params.yaml`](file:///home/lev/IJKbot/src/driver/config/params.yaml#L19)
- **Суть**:
  В `README.md` зафиксировано: «Лимиты скорости: $\omega_{max} = 1.0\text{ рад/с}$ (программно зафиксированы в `nav2_params.yaml` и `params.yaml`)». В файле `params.yaml` низкоуровневого драйвера задано: `max_angular_velocity: 2.0`.
- **Рекомендация**:
  Синхронизировать лимит в `params.yaml` на `1.0`, чтобы предотвратить резкие угловые рывки приводов.

---

## 6. Каталог конкретных исправлений (Remediation Patches)

### Патч 1: Исправление `mission_sm.py` (SystemLauncher + Фоновый тик)
```python
# В SystemLauncher.start() (строки 325-341):
# Вместо вызова чистого system.launch.py передавать явные флаги запуска:
cmd = [
    "ros2", "launch", "bringup", "system.launch.py",
    f"mock_hardware:={mock_str}",
    f"initial_x:={initial_x}",
    f"initial_y:={initial_y}",
    f"initial_yaw:={initial_yaw}",
    "enable_robot:=true",
    "enable_nav:=true",
    "enable_brain:=false",
]

# Вынос sm.step(0.1) в независимый поток приложения:
from nicegui import app

def run_fsm_loop():
    stop_event = threading.Event()
    def _loop():
        while not stop_event.is_set():
            sm.step(0.1)
            time.sleep(0.1)
    t = threading.Thread(target=_loop, daemon=True)
    t.start()
    return stop_event

app.on_startup(run_fsm_loop)
```

### Патч 2: Увеличение Footprint в `nav2_params.yaml`
```yaml
# src/nav2/config/nav2_params.yaml (строки 125 и 155):
- footprint: "[[0.11, 0.125], [0.11, -0.125], [-0.17, -0.125], [-0.17, 0.125]]"
+ footprint: "[[0.12, 0.135], [0.12, -0.135], [-0.19, -0.135], [-0.19, 0.135]]"
```

### Патч 3: Потокобезопасность вызова LLM в `mission_sm.py`
```python
# src/brain/mission_sm.py (строка 1720):
from nicegui import run

async def handle_llm_parse():
    llm_parse_btn.props("loading")
    try:
        interp = await run.io_bound(sm.parse_task_with_llm, on_token=on_token_cb)
        ui.notify(f"Задание успешно распознано ({interp.source})!", type="positive")
    except Exception as ex:
        ui.notify(f"Ошибка LLM: {ex}", type="negative")
    finally:
        llm_parse_btn.props(remove="loading")
```

### Патч 4: Добавление републикации сжатого видео в `realsense_laserscan.launch.py` (ROS 2 Jazzy)
```python
# src/bringup/launch/realsense_laserscan.launch.py:
republish_node = Node(
    package='image_transport',
    executable='republish',
    name='image_compressor',
    parameters=[{'in_transport': 'raw', 'out_transport': 'compressed'}],
    remappings=[
        ('in', '/camera/color/image_raw'),
        ('out/compressed', '/camera/color/image_raw/compressed'),
    ],
    output='screen'
)
```

### Патч 5: Исправление проброса модели в `start_all_laptop1.sh` и `laptop.launch.py`
```bash
# scripts/start_all_laptop1.sh:
LAUNCH_CMD="source '${SETUP_BASH}' && ros2 launch bringup laptop.launch.py \
    llm_host:='${LLM_HOST}' \
    llm_model:='${LLM_MODEL}' \
    port:='${PORT}' \
    host:='${HOST}' \
    mock:='${MOCK}' \
    enable_vision:='${ENABLE_VISION}'"
```

### Патч 6: Проброс аргумента Mock в `system.launch.py`
```python
# src/bringup/launch/system.launch.py:
brain_node = Node(
    package='brain',
    executable='dashboard_app',
    name='mission_state_machine',
    output='screen',
    condition=IfCondition(LaunchConfiguration('enable_brain')),
    arguments=[
        '--host', '0.0.0.0',
        '--port', '8080',
        '--llm-host', LaunchConfiguration('llm_host'),
        '--mock', LaunchConfiguration('mock_hardware'),
    ],
    parameters=[{'use_sim_time': LaunchConfiguration('use_sim_time')}],
)
```

---

## 7. Заключение и приоритизация работ

Репозиторий обладает качественной инженерной основой и хорошим тестовым покрытием базовых компонентов. Однако выявленные критические архитектурные несоответствия (в первую очередь запуск дубликата brain вместо robot/nav2 в `SystemLauncher`, привязка цикла автомата к веб-браузеру и риск касания задней частью шасси) должны быть устранены в приоритетном порядке до выхода на физический полигон соревнований.
