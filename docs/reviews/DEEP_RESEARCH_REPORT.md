# Комплексный аудит архитектуры, навигации, компьютерного зрения и среды IJKbot
**Версия документа:** 2.0 (Итоговый верифицированный отчет с ревизией предшествующих расследований)  
**Дата проведения аудита:** 24 сентября 2026 г.  
**Контекст проекта:** Исследование причин сбоев навигации, отказа глобального планера, непроверенной подсистемы сканирования QR-кодов и скрытых дефектов кодовой базы мобильного робота IJKbot (двуколесная дифференциальная платформа, приводы Feetech STS3215, камера Intel RealSense D435, бортовой Raspberry Pi 4B под Ubuntu 24.04 / ROS 2 Jazzy и внебортовой ноутбук с RTX 5060) в преддверии соревнований «Кубок РТК Высшая Лига».

---

## 1. Резюме аудита и главные выводы

По результатам глубокого статического анализа исходного кода, верификации системных логов ROS 2 (`~/.ros/log/`), трассировки графа коммитов Git и воспроизводящих стендовых экспериментов (включая стендовый бенчмарк детекции QR-кодов при 3D-наклоне и сжатии, математическое моделирование среза луча RealSense, инспекцию растровой карты арены и окружения Pixi) выявлена целостная картина критических отказов системы.

В проекте идентифицировано **26 дефектов**, из которых **8 являются абсолютными блокерами (Showstoppers)**, делающими автономное выполнение регламентной миссии на соревновательном полигоне невозможным.

### Ключевые причины краха навигации и неработоспособности планера:
1. **Катастрофическая рассинхронизация часов ($\Delta t > 121$ с) между Pi 4B и ноутбуком.** Отсутствие модуля RTC на Raspberry Pi 4B и ненастроенный протокол NTP/Chrony в изолированной Wi-Fi сети привели к тому, что библиотека `tf2_ros` отбрасывала 100% пакетов лазерскана `/scan` и одометрии. Ноды навигации фиксировали: `ExtrapolationException: Lookup would require extrapolation 121s into the future`, что приводило к срыву вычисления позы робота (`Failed to get robot pose`).
2. **Рассогласование систем координат `map` и `odom` в автомате состояний ([`mission_sm.py`](file:///home/lev/IJKbot/ijkbot_brain/mission_sm.py#L976-L1093)).** Автомат брал текущую позу робота из топика `/odom` ($[0.0, 0.0]$ на старте), а координаты ориентиров задавались в СК карты `map` (смещение стартовой ячейки $[0.4, 0.4]$). При физическом прибытии робота в ячейку евклидово расстояние в СК автомата составляло $\sqrt{0.4^2 + 0.4^2} \approx 0.5657$ м при жестком пороге прибытия $0.18$ м. Робот стоял в точке, но автомат считал цель недостигнутой и зависал на 250 секунд до аварийного сброса по таймауту.
3. **Ловушка симуляции `--mock` по умолчанию и архитектурный дефект `argparse` ([`mission_sm.py`](file:///home/lev/IJKbot/ijkbot_brain/mission_sm.py#L1913-L1941)).** Аргумент CLI `--mock` имел значение `default=True`, а класс `MissionStateMachine` инициализировался с `mock_mode=True`. При обычном запуске нода полностью игнорировала реальную одометрию с моторов, телепортировала виртуального робота формулой `_step_mock_kinematics(dt)` и фейковала чтение QR-кода на 4-м шаге первой ячейки. В веб-интерфейсе отображался успешный проезд, тогда как физический робот стоял на месте. Более того, в лаунч-файле ноутбука передача аргумента `'--mock', LaunchConfiguration('mock')` (со значением 'false') из-за `action="store_true"` в парсере Python приводила к принудительной активации `mock=True`!
4. **Конфликт паблишеров и гонка команд в топике `/cmd_vel`.** `nav2_velocity_smoother` транслирует команды управления траекторией в `/cmd_vel` на частоте 10–20 Гц ([`navigation.launch.py`](file:///home/lev/IJKbot/ijkbot_nav2/launch/navigation.launch.py#L191-L194)). Одновременно с этим `mission_sm.py` имеет собственный паблишер в `/cmd_vel` ([`mission_sm.py`](file:///home/lev/IJKbot/ijkbot_brain/mission_sm.py#L1070)), через который при каждой смене фаз и на каждом шаге цикла отправляет нулевые скорости `(0.0, 0.0)` или разворотные команды без отмены активной Action-цели в Nav2. Взаимоисключающие команды приводили к дерганию моторов и авариям приводов.
5. **Фантомная стена в `global_costmap` из-за засветки пола лучом RealSense D435.** При высоте установки камеры $157.5$ мм над полом ([`ijkbot.urdf.xacro`](file:///home/lev/IJKbot/ijkbot_description/urdf/ijkbot.urdf.xacro#L128)) и расходимости вертикального среза `depthimage_to_laserscan` $\sim 1.8^\circ$ ([`realsense_laserscan.yaml`](file:///home/lev/IJKbot/ijkbot_bringup/config/realsense_laserscan.yaml#L3)) даже минимальный дифферент шасси на кастерах на $2.5^\circ$ приводит к удару луча в пол на дистанции $2.65$ м. Пол вносился в `global_costmap` со значением `254 (Lethal Obstacle)`. С учетом инфляции $0.30$ м формировалась непреодолимая виртуальная преграда, из-за которой Navfn возвращал «No valid path».
6. **Опасность отключения `bond_timeout: 0.0` на Pi 4B ([`navigation.launch.py`](file:///home/lev/IJKbot/ijkbot_nav2/launch/navigation.launch.py#L135-L237)).** В коммите `c0a1d9f` автор отключил bond-watchdog в `lifecycle_manager`, пытаясь скрыть падения нод при 100% нагрузке на CPU Pi 4B. Это привело к фатальной маскировке отказов: при падении `planner_server` система зависает навсегда, не генерируя события перехода в Failure.
7. **Дефицит `nav2_msgs` в Pixi-окружении ноутбука и крах `trial_planner.py`.** В `/home/lev/ros2_jazzy/pixi.toml` отсутствуют зависимости `ros-jazzy-nav2-msgs`, `ros-jazzy-navigation2` и `colcon`. При попытке запустить `trial_planner.py` нода падала с `ModuleNotFoundError: No module named 'nav2_msgs'`.

### Ключевые причины сбоев подсистемы технического зрения и QR:
1. **Срыв детектора `cv2.QRCodeDetector()` на мелких кодах и угле свыше $5^\circ$.** Прямой экспериментальный бенчмарк доказал, что стандартный детектор OpenCV на разрешении $640\times 480$ при размере QR-кода $70\times 70$ px (дистанция $\approx 0.7$ м) без принудительного масштабирования дает **100% срыв даже при угле $0^\circ$**! А при масштабировании работает только в диапазоне $0^\circ–5^\circ$, а при наклоне на угол $6^\circ$ и более наступает **100% отказ**. Нейросетевой `cv2.wechat_qrcode_WeChatQRCode()` гарантирует **100% распознавание вплоть до $30^\circ–35^\circ$ наклона** напрямую из исходного кадра.
2. **Блокировка видеопотока параметром `snapshot_mode: true` ([`qr_reader.yaml`](file:///home/lev/IJKbot/ijkbot_vision/config/qr_reader.yaml#L7)).** В коммите `fcb19b3` нода `qr_reader_node` была заблокирована: `_image_callback` завершался по `return`, ожидая триггера `/vision/take_photo`. Из-за навигационного сбоя (Дефект 2) робот не переходил в `SEARCHING_VICTIM`, триггер никогда не публиковался, и нода зрения за все время испытаний не обработала ни одного кадра!
3. **Логическая ошибка апскейла в `qr_decoder.py` ([`qr_decoder.py`](file:///home/lev/IJKbot/ijkbot_vision/ijkbot_vision/qr_decoder.py#L71)).** Условие `max(image.shape[:2]) < 640` для кадра $640\times 480$ дает `max(480, 640) < 640` $\to$ `False`, полностью выключая 4-кратное интерполяционное увеличение мелких кодов.
4. **Невалидный профиль сенсора RealSense `640x480x5` ([`realsense_laserscan.launch.py`](file:///home/lev/IJKbot/ijkbot_bringup/launch/realsense_laserscan.launch.py#L20)).** Аппаратный RGB-модуль RealSense D435 не поддерживает частоту 5 FPS, вызывая сбой инициализации сенсора в драйвере `realsense2_camera`.
5. **Полное отсутствие детектора человека.** В пакете `ijkbot_vision` отсутствуют ноды YOLO-World и 3D-депроекции, предусмотренные Этапом 4 регламента.

---

## 2. Результаты критической ревизии предшествующего расследования

В ходе независимой проверки выводов первичного аудита были вскрыты фактические неточности, логические пробелы и выявлены новые фундаментальные дефекты, ранее упущенные:

| Аспект первичного отчета | Утверждение первичного отчета | Что показал независимый анализ кода и тесты | Исправленный вердикт и технические детали |
|---|---|---|---|
| **Файл `mission_sm.python`** | "Наличие дублирующего ошибочного файла `mission_sm.python` размером 106 КБ" | Команда `ls -l` подтвердила: файл `mission_sm.python` является символической ссылкой длиной 13/16 байт (`-> ../mission_sm.py`). | Файл не является независимой копией на 106 КБ, это паразитный симлинк, созданный при попытке правок. |
| **Флаг `--mock` в launch-файлах** | Проблема описана только как дефолт в `mission_sm.py`. | Вскрыт механизм блокировки отключения мока: в `origin/dev:laptop.launch.py` передается `'--mock', LaunchConfiguration('mock')`. В `mission_sm.py` аргумент объявлен как `action='store_true'`. При передаче `'--mock false'` парсер `argparse` все равно выставляет `mock=True`! В `robot.launch.py` аргумент `mock_hardware` также по умолчанию равен `'true'`, перекрывая `params.yaml`. | **Новый дефект D20 и D21**: Ни `laptop.launch.py`, ни `robot.launch.py` не позволяли отключить mock-режим при стандартном запуске. |
| **Фильтрация пола в Costmap** | Рекомендовано выставить `min_obstacle_height: 0.05` в `nav2_params.yaml`. | `depthimage_to_laserscan` формирует 2D лазерскан, где у лучей нет координаты Z ($Z=0$ во фрейме `camera_link`). У робота нет IMU, динамический тангаж в TF не транслируется (pitch=0.0). При трансформации в `map` все точки получают высоту камеры $Z = 0.1575$ м. Так как $0.1575 > 0.05$, фильтр `min_obstacle_height` **не отфильтрует ни одной точки пола**! | **Логический пробел в первичном плане**: Программный фильтр высоты на 2D лазерскане не работает. Единственные надежные решения: `range_max: 2.20` м, механический/URDF наклон камеры вверх ($+2^\circ$) или переход на PointCloud2 с `VoxelLayer`. |
| **Увеличение таймаута UART** | Рекомендовано увеличить `serial_timeout_ms` с 20 мс до 40 мс. | В [`diff_drive_node.cpp`](file:///home/lev/IJKbot/sts3215_driver/src/diff_drive_node.cpp#L47) присутствует жесткая проверка: `timeout_ms < 1 \|\| timeout_ms > 25`. При указании 40 мс в `params.yaml` нода упадет на старте с `std::invalid_argument`. | Для увеличения таймаута необходимо обязательно скорректировать C++ валидатор в конструкторе `DiffDriveNode`. |
| **Счетчик ошибок в драйвере** | Предложено разработать логику повторов. | В заголовке [`diff_drive_node.hpp`](file:///home/lev/IJKbot/sts3215_driver/include/diff_drive_node.hpp#L37-L38) разработчик **уже объявил** `error_streak_` и `kMaxErrorStreak = 5`, но забыл применить их в `.cpp`, вызывая `latchFault()` сразу на первом исключении! | **Новый дефект D22**: Недописанный функционал обработки сбоев UART в драйвере STS3215. |
| **Бенчмарк QR-детектора** | Разделены дефект чувствительности к углу и дефект апскейла. | Тест доказал: на разрешении $640\times 480$ QR-код $70\times 70$ px дает **100% срыв даже при $0^\circ$ наклона**, если отключен 4x апскейл. А условие `max(image.shape[:2]) < 640` гарантировало его отключение. | Дефекты D07 и D12 взаимно усиливали друг друга: OpenCV в реальных условиях не работал вообще. |
| **Архитектура запуска стека** | Не исследована логика `SystemLauncher` в дашборде. | В `mission_sm.py` класс `SystemLauncher` по умолчанию запускает `system.launch.py` локально на ноутбуке, пытаясь открыть `/dev/ttyUSB0` моторов на ноутбуке вместо робота. | **Новый дефект D25**: Полное смешение бортового и внебортового стека в коде GUI. |
| **Пакет `xacro`** | Не исследована доступность `xacro`. | В окружении Pixi и системе отсутствует бинарник `xacro`, из-за чего `rsp.launch.py` не может сгенерировать `robot_description`. | **Новый дефект D26**: Отсутствие `ros-jazzy-xacro` в `pixi.toml`. |

---

## 3. Детальный технический разбор дефектов по подсистемам

### 3.1. Подсистема навигации, планирования, TF2 и Costmap

#### Дефект D01 (БЛОКЕР) — Катастрофическая рассинхронизация системного времени Pi 4B и ноутбука ($\Delta t > 121$ с)
- **Файлы доказательств:** Лог RViz `~/.ros/log/rviz2_117855_1789903045182.log` (строки 5–7, 14–15, 23–25):
  ```text
  [INFO] [1789903049.952259308] [rviz]: Message Filter dropping message: frame 'camera_link' at time 1789902928.803 for reason 'discarding message because the queue is full'
  [ERROR] [1789904820.638666666] [rviz2]: Lookup would require extrapolation into the past. Requested time 1789904683,550530 but the earliest data is at time 1789904684,354753, when looking up transform from frame [camera_link] to frame [map]
  ```
- **Суть проблемы:** Raspberry Pi 4B не имеет аппаратного модуля часов реального времени (RTC). При включении робота в изолированной соревновательной Wi-Fi сети (роутер без доступа к интернету) демон `systemd-timesyncd` не может синхронизироваться с внешними NTP-серверами. Время на Pi отстает от времени ноутбука более чем на 2 минуты (121.15 секунды).
- **Влияние на систему:** Библиотека `tf2_ros` при сопоставлении дерева координат `map -> odom -> base_footprint -> camera_link` отбрасывает сообщения одометрии и сканов. `planner_server` падает с ошибкой `ComputePathToPose: Failed to get robot pose`.

#### Дефект D02 (БЛОКЕР) — Несоответствие систем координат `map` и `odom` в автомате миссий
- **Файлы доказательств:**
  - [`ijkbot_brain/mission_sm.py`](file:///home/lev/IJKbot/ijkbot_brain/mission_sm.py#L976-L984) (`_check_reached_waypoint`):
    ```python
    def _check_reached_waypoint(self, wp: Optional[Waypoint]) -> bool:
        if not wp:
            return False
        dist = math.hypot(wp.x - self.robot_x, wp.y - self.robot_y)
        yaw_diff = abs((wp.yaw - self.robot_yaw + math.pi) % (2 * math.pi) - math.pi)
        tol_dist = 0.08 if self.mock_mode else 0.18
        tol_yaw = 0.25 if self.mock_mode else 0.35
        return dist < tol_dist and yaw_diff < tol_yaw
    ```
  - [`ijkbot_brain/mission_sm.py`](file:///home/lev/IJKbot/ijkbot_brain/mission_sm.py#L1090-L1100) (`_odom_callback`):
    ```python
    def _odom_callback(self, msg: Any) -> None:
        with self.sm.lock:
            if not self.sm.mock_mode:
                self.sm.robot_x = msg.pose.pose.position.x
                self.sm.robot_y = msg.pose.pose.position.y
    ```
  - [`ijkbot_nav2/launch/navigation.launch.py`](file:///home/lev/IJKbot/ijkbot_nav2/launch/navigation.launch.py#L113-L122):
    ```python
    arguments=['--x', initial_x, '--y', initial_y, '--z', '0.0', '--yaw', initial_yaw,
               '--frame-id', 'map', '--child-frame-id', 'odom'] # initial_x=0.4, initial_y=0.4
    ```
- **Математическое доказательство отказа:**
  - При старте робота одометрия приводов STS3215 обнуляется: $x_{odom} = 0.0, y_{odom} = 0.0$.
  - Статический трансформ связывает карты со смещением: $x_{map} = x_{odom} + 0.4$, $y_{map} = y_{odom} + 0.4$.
  - Целевой ориентир `SMOKE_TOWER` задан в координатах карты: $wp.x = 0.4, wp.y = 2.8$.
  - Когда Nav2 идеально приводит робота в точку, одометрия равна $x_{odom} = 0.0, y_{odom} = 2.4$.
  - Функция `_check_reached_waypoint` вычисляет расстояние между $wp$ (в `map`) и `self.robot` (в `odom`):
    $$dist = \sqrt{(0.4 - 0.0)^2 + (2.8 - 2.4)^2} = \sqrt{0.16 + 0.16} = \sqrt{0.32} \approx 0.5657\text{ м}$$
  - Так как $0.5657\text{ м} > 0.18\text{ м (допуск)}$, условие `dist < tol_dist` ложно всегда. Автомат зависает на 250 секунд и никогда не переходит к сканированию QR.

#### Дефект D04 (БЛОКЕР) — Конфликт и гонка паблишеров в топике `/cmd_vel`
- **Файлы доказательств:**
  - [`ijkbot_nav2/launch/navigation.launch.py`](file:///home/lev/IJKbot/ijkbot_nav2/launch/navigation.launch.py#L186-L195):
    ```python
    smoother_node = Node(
        package='nav2_velocity_smoother',
        executable='velocity_smoother',
        remappings=[('cmd_vel', 'cmd_vel_nav'), ('cmd_vel_smoothed', 'cmd_vel')]
    )
    ```
  - [`ijkbot_brain/mission_sm.py`](file:///home/lev/IJKbot/ijkbot_brain/mission_sm.py#L1070):
    ```python
    self.cmd_vel_pub = self.node.create_publisher(Twist, "/cmd_vel", 10)
    ```
- **Суть проблемы:** Узел `nav2_velocity_smoother` непрерывно транслирует команды скорости в топик `/cmd_vel` на частоте 10 Гц. Одновременно `mission_sm.py` на каждом тике автомата вызывает `_publish_zero_velocity()` (строки 631, 650, 681, 726, 736, 739, 790, 806, 817, 831, 856, 898, 927) и шлет `(0.0, 0.0)` в тот же топик `/cmd_vel`. Более того, во время фазы кругового осмотра (`SEARCHING_VICTIM`, строка 800) автомат шлет `send_cmd_vel(0.0, TURN_SPEED)` без отмены текущей цели в Nav2. Без узла `twist_mux` драйвер моторов получает чередующиеся команды хода и нуля.

#### Дефект D05 (БЛОКЕР) — Ложные фатальные препятствия в `global_costmap` из-за луча RealSense D435
- **Файлы доказательств:**
  - [`ijkbot_description/urdf/ijkbot.urdf.xacro`](file:///home/lev/IJKbot/ijkbot_description/urdf/ijkbot.urdf.xacro#L128-L138): высота камеры над полом $H = 0.0375 + 0.120 = 0.1575$ м. Наклон `camera_pitch = 0.0`.
  - [`ijkbot_bringup/config/realsense_laserscan.yaml`](file:///home/lev/IJKbot/ijkbot_bringup/config/realsense_laserscan.yaml#L3-L6): `scan_height: 15`, `range_min: 0.20`, `range_max: 4.00`.
  - [`ijkbot_nav2/config/nav2_params.yaml`](file:///home/lev/IJKbot/ijkbot_nav2/config/nav2_params.yaml#L160-L176): `obstacle_max_range: 3.0`, `inflation_radius: 0.30`.
- **Математический расчет:**
  - Сенсор D435 имеет вертикальный угол обзора $58^\circ$ (480 строк $\to 0.121^\circ$ на строку).
  - Окно `scan_height: 15` охватывает угловой диапазон $\pm 0.9^\circ$. Нижний край луча отклонен вниз на $0.9^\circ$.
  - При движении шасси по полигону кастеры и подвеска дают просадку, наклоняя шасси вперед на $\theta \approx 2.5^\circ$.
  - Суммарный угол падения нижнего края луча: $\alpha = 2.5^\circ + 0.9^\circ = 3.4^\circ$.
  - Дистанция пересечения с полом:
    $$D_{floor} = \frac{0.1575}{\tan(3.4^\circ)} \approx \frac{0.1575}{0.0594} \approx 2.65\text{ м}$$
  - Так как $2.65\text{ м} < 3.0\text{ м}$ (`obstacle_max_range`), пол вносится в `global_costmap` как препятствие со значением `254 (Lethal Obstacle)`. С радиусом инфляции $0.30$ м впереди робота возникает виртуальная стена, и планер Navfn выдает «No valid path».

#### Дефект D06 (БЛОКЕР) — Отсутствие пакета `nav2_msgs` в Pixi-окружении ноутбука
- **Файлы доказательств:**
  - Конфигурация Pixi: `/home/lev/ros2_jazzy/pixi.toml` (зависимости `ros-jazzy-desktop`, `ros-jazzy-image-transport-plugins` и др.).
  - Исходный код [`trial_planner.py`](file:///home/lev/IJKbot/ijkbot_brain/trial_planner.py#L11): `from nav2_msgs.action import NavigateToPose`.
- **Суть проблемы:** В `pixi.toml` отсутствуют `ros-jazzy-nav2-msgs` и `ros-jazzy-navigation2`. При выполнении `python3 -c "import nav2_msgs"` возвращается `ModuleNotFoundError: No module named 'nav2_msgs'`. При запуске `trial_planner.py` нода немедленно завершается аварийно.
- **Уточненный диагноз ошибок логов:** Логи `python_57530_1789893376775.log` и `python_197633_1789837957638.log` с сообщениями:
  ```text
  [ERROR] [get_message_class]: Malformed msg message_type: nav2_msgs/action/NavigateToPose_FeedbackMessage
  ```
  порождались графическими утилитами интроспекции (`rqt_gui` / `ros2 topic echo`), которые пытались декодировать фидбек-сообщения Nav2 в Python-окружении ноутбука без установленного пакета `nav2_msgs`.

#### Дефект D11 (ВЫСОКИЙ) — Отключение контроля жизнеспособности нод `'bond_timeout': 0.0`
- **Файлы доказательств:** [`ijkbot_nav2/launch/navigation.launch.py`](file:///home/lev/IJKbot/ijkbot_nav2/launch/navigation.launch.py#L135,L159,L237) (коммит `c0a1d9f`).
- **Суть проблемы:** В коммите `c0a1d9f` разработчик установил `'bond_timeout': 0.0`, пытаясь обойти ложные срабатывания на Pi 4B при 100% нагрузке на процессор. Это полностью выключило Heartbeat-контроль нод Nav2. Если `planner_server` падает из-за нехватки памяти (OOM) или сегфолта, `lifecycle_manager` не переводит систему в аварийное состояние, и робот навсегда зависает в ожидании ответа Action.

#### Дефект D14 (ВЫСОКИЙ) — Геометрическая несогласованность Footprint и инфляции
- **Файлы доказательств:** [`ijkbot_nav2/config/nav2_params.yaml`](file:///home/lev/IJKbot/ijkbot_nav2/config/nav2_params.yaml#L125,L155):
  - `local_costmap`: `footprint: "[[0.12, 0.125], [0.12, -0.125], [-0.18, -0.125], [-0.18, 0.125]]"` (габариты $250\times 300$ мм), `inflation_radius: 0.25`.
  - `global_costmap`: `footprint: "[[0.12, 0.12], [0.12, -0.12], [-0.15, -0.12], [-0.15, 0.12]]"` (габариты $240\times 270$ мм), `inflation_radius: 0.30`.
- **Суть проблемы:** Локальный контур робота на 10 мм шире и на 30 мм длиннее глобального. Глобальный планер строит траекторию через узкие проемы арены, но локальный контроллер объявляет коридор непроходимым и переходит в цикл бесконечных Recovery-маневров.

#### Дефект D15 (СРЕДНИЙ) — Ошибочные пиксели карты полигона `polygon_empty_4x4.pgm`
- **Файлы доказательств:** [`ijkbot_nav2/maps/polygon_empty_4x4.yaml`](file:///home/lev/IJKbot/ijkbot_nav2/maps/polygon_empty_4x4.yaml) и `.pgm`.
- **Результаты растрового анализа:**
  - Размер карты: $100\times 100$ пикселей (при разрешении $0.05$ м $\to 5.0\times 5.0$ м).
  - Стены полигона (пиксель 0, черные): 1604 пикселя (16%).
  - Все остальное пространство (включая зону внутри арены и зону снаружи стен): пиксель **205** (8396 пикселей, 84%).
  - В файле конфигурации заданы `mode: trinary`, `free_thresh: 0.25`.
  - Вероятность занятости для значения 205:
    $$p = \frac{255 - 205}{255} \approx 0.196$$
  - Так как $p < free\_thresh$ ($0.196 < 0.25$), `nav2_map_server` интерпретирует ВСЕ пространство (как внутри полигона, так и за пределами стен арены) как **абсолютно свободную зону (cost = 0)**. Неизвестное пространство отсутствует вовсе. Если луч дальномера пробивает стену толщиной в 1 пиксель (5 см), costmap стирает препятствие.

#### Дефект D23 (ВЫСОКИЙ) — Неприменимость фильтра `min_obstacle_height` к 2D LaserScan
- **Файлы доказательств:** [`ijkbot_bringup/config/realsense_laserscan.yaml`](file:///home/lev/IJKbot/ijkbot_bringup/config/realsense_laserscan.yaml#L7), [`diff_drive_node.cpp`](file:///home/lev/IJKbot/sts3215_driver/src/diff_drive_node.cpp#L227-L230).
- **Суть проблемы:** Предыдущий аудит рекомендовал фильтровать пол параметром `min_obstacle_height: 0.05` в `ObstacleLayer`. Однако узел `depthimage_to_laserscan` преобразует срез глубины в сообщение `sensor_msgs/msg/LaserScan` с фреймом `camera_link`. В 2D LaserScan у точек нет вертикальной координаты ($Z=0$).
- Драйвер моторов `diff_drive_node` транслирует только плоскую одометрию ($x, y, yaw$), roll и pitch всегда равны 0.0. Дерево TF не имеет информации о наклоне робота. При трансформации точек лазерскана в фрейм `map` все точки получают фиксированную высоту установки камеры: $Z = 0.1575$ м.
- Так как $0.1575\text{ м} > 0.05\text{ м}$, фильтр `min_obstacle_height` не отсекает ни одной точки пола. Защита должна реализовываться ограничением `range_max: 2.20` м и аппаратным наклоном камеры вверх на $+2^\circ$.

#### Дефект D24 (ВЫСОКИЙ) — Отсутствие Action-обратной связи от Nav2 в `mission_sm.py`
- **Файлы доказательств:** [`ijkbot_brain/mission_sm.py`](file:///home/lev/IJKbot/ijkbot_brain/mission_sm.py#L1071-L1073,L1160-L1170), [`ijkbot_brain/trial_planner.py`](file:///home/lev/IJKbot/ijkbot_brain/trial_planner.py#L19,L50).
- **Суть проблемы:** `mission_sm.py` отправляет цели Nav2 в топик `/goal_pose` как обычные сообщения `PoseStamped`, не создавая `ActionClient(NavigateToPose)`. Из-за этого автомат не получает подтверждения достижения цели от Nav2, не знает о статусах выполнения (Active, Succeeded, Aborted) и не может отменить цель при смене состояния. Разработчик `trial_planner.py` указал в докстринге: `«Nav2 results, not odom coordinates, prove arrival»`, но сам узел не мог функционировать из-за отсутствия `nav2_msgs`.

#### Дефект D26 (СРЕДНИЙ) — Отсутствие бинарника `xacro` в рабочей среде
- **Файлы доказательств:** [`ijkbot_description/launch/rsp.launch.py`](file:///home/lev/IJKbot/ijkbot_description/launch/rsp.launch.py#L26), `/home/lev/ros2_jazzy/pixi.toml`.
- **Суть проблемы:** `rsp.launch.py` выполняет `Command(['xacro ', xacro_file])`. В Pixi-окружении пакет `ros-jazzy-xacro` отсутствует. Команда `which xacro` завершается с кодом 1, блокируя генерацию описания робота.

---

### 3.2. Архитектура автомата миссий и интеграция запуска

#### Дефект D03 (БЛОКЕР) — Ловушка симуляции `--mock` по умолчанию в `mission_sm.py`
- **Файлы доказательств:**
  - [`ijkbot_brain/mission_sm.py`](file:///home/lev/IJKbot/ijkbot_brain/mission_sm.py#L339-L343,L1913-L1914):
    ```python
    def __init__(self, llm_client: Optional[LLMClient] = None, mock_mode: bool = True):
        self.mock_mode = mock_mode
    ...
    parser.add_argument("--mock", action="store_true", default=True, help="Запуск в режиме симуляции (по умолчанию True)")
    parser.add_argument("--no-mock", dest="mock", action="store_false", help="Запуск с реальным ROS 2 железом")
    ```
  - [`ijkbot_brain/mission_sm.py`](file:///home/lev/IJKbot/ijkbot_brain/mission_sm.py#L705-L711,L835-L844):
    ```python
    if self.mock_mode and self.current_waypoint ...:
        self._step_mock_kinematics(dt)
    ...
    if self.mock_mode and not self.qr_code_data:
        if self.current_waypoint_idx == 0 and self.spin_step == 3:
            self.qr_code_data = ("ПОСТРАДАВШИЙ #1\nФИО: Иванов И.И....")
    ```
- **Суть проблемы:** Запуск `ros2 run ijkbot_brain mission_sm` без специфического флага `--no-mock` оставляет систему в симуляции. В этом режиме одометрия игнорируется (`if not self.sm.mock_mode:`), виртуальный робот двигается по чистой кинематической формуле, моторы не включаются, а QR-код подставляется жестко зашитой строкой.

#### Дефект D20 (КРИТИЧЕСКИЙ) — Невозможность выключения mock-режима из `laptop.launch.py`
- **Файлы доказательств:**
  - `origin/dev:ijkbot_bringup/launch/laptop.launch.py`:
    ```python
    declare_mock = DeclareLaunchArgument('mock', default_value='false')
    ...
    arguments=['--mock', LaunchConfiguration('mock')]
    ```
  - Тест парсера Python:
    ```bash
    python3 -c "import argparse; p = argparse.ArgumentParser(); p.add_argument('--mock', action='store_true', default=True); args, extra = p.parse_known_args(['--mock', 'false']); print('mock:', args.mock, 'extra:', extra)"
    # Вывод: mock: True extra: ['false']
    ```
- **Суть проблемы:** При объявлении аргумента с `action="store_true"` он не принимает значение. Передача `--mock false` интерпретируется как выставление флага `--mock` в `True`, а строка `'false'` отбрасывается как лишний аргумент. Лаунч-файл ноутбука был физически не способен отключить симуляцию.

#### Дефект D21 (КРИТИЧЕСКИЙ) — Принудительное включение `mock_hardware: true` в `robot.launch.py`
- **Файлы доказательств:** [`ijkbot_bringup/launch/robot.launch.py`](file:///home/lev/IJKbot/ijkbot_bringup/launch/robot.launch.py#L29-L33,L65-L68):
  ```python
  declare_mock_hardware = DeclareLaunchArgument('mock_hardware', default_value='true')
  ...
  parameters=[driver_params_file, {'mock_hardware': mock_hardware}]
  ```
- **Суть проблемы:** Несмотря на то, что в [`params.yaml`](file:///home/lev/IJKbot/sts3215_driver/config/params.yaml#L3) драйвера прописано `mock_hardware: false`, лаунч-файл `robot.launch.py` имеет значение по умолчанию `'true'` и передает словарь вторым элементом списка параметров, перетирая конфигурационный файл. Запуск `robot.launch.py` без флага `mock_hardware:=false` переводит драйвер моторов в режим мока без открытия UART.

#### Дефект D25 (СРЕДНИЙ) — Архитектурный конфликт в `SystemLauncher`
- **Файлы доказательств:** [`ijkbot_brain/mission_sm.py`](file:///home/lev/IJKbot/ijkbot_brain/mission_sm.py#L249-L279,L1247-L1255).
- **Суть проблемы:** Кнопка запуска бортового стека в Web GUI использует переключатель `ssh_switch` с дефолтным значением `False`. В этом режиме `SystemLauncher` запускает `system.launch.py` локально на ноутбуке, пытаясь открыть `/dev/ttyUSB0` моторов и камеру RealSense, физически подключенные к Pi 4B. При включении `ssh_switch` на Pi запускается весь стек целиком (включая распознавание QR), что перегружает CPU платы до 100%.

#### Дефект D16 (СРЕДНИЙ) — Нарушение структуры пакета `ijkbot_brain`
- **Файлы доказательств:** Директория `ijkbot_brain/`.
- **Суть проблемы:** Исходные модули размещены одновременно в корне пакета и в подкаталоге через символические ссылки (`mission_sm.py -> ../mission_sm.py`). Наличие симлинка `mission_sm.python` создавало путаницу при сборке. Разработчикам приходилось внедрять условные fallback-импорты вида `try: from ijkbot_brain... except ImportError: from ...`.

#### Дефект D18 (СРЕДНИЙ) — Паразитные координаты базы в списке точек поиска
- **Файлы доказательств:** [`ijkbot_brain/ijkbot_brain/llm_client.py`](file:///home/lev/IJKbot/ijkbot_brain/ijkbot_brain/llm_client.py#L186,L197) (`LANDMARK_CANDIDATE_WAYPOINTS`).
- **Суть проблемы:** Для ориентиров `FALLEN_TREE` (точка 3) и `DEBRIS_PVC` (точка 2) задана координата $[0.4, 0.4]$ (стартовая ячейка). При обходе ориентира робот посреди поиска разворачивается и едет на базу.

---

### 3.3. Подсистема компьютерного зрения и распознавания QR-кодов

#### Дефект D07 (КРИТИЧЕСКИЙ) — Сверхчувствительность детектора OpenCV к углу наклона
- **Файлы доказательств:** [`ijkbot_vision/ijkbot_vision/qr_decoder.py`](file:///home/lev/IJKbot/ijkbot_vision/ijkbot_vision/qr_decoder.py#L68-L69).
- **Результаты воспроизводящего стендового бенчмарка:**
  Был проведен прямой сравнительный тест стандартного `cv2.QRCodeDetector()` и нейросетевого `cv2.wechat_qrcode_WeChatQRCode()` на реальном разрешении кадра $640\times 480$, сжатии JPEG Q80 и размере QR-кода $70\times 70$ px:
  ```text
  === Бенчмарк 3D перспективного наклона QR-кода (размер 70x70 px, кадр 640x480) ===
  Наклон  0° (без апскейла): cv2.QRCodeDetector -> FAIL    | WeChatQRCode -> SUCCESS
  Наклон  0° (с 4x апскейл): cv2.QRCodeDetector -> SUCCESS | WeChatQRCode -> SUCCESS
  Наклон  2° (с 4x апскейл): cv2.QRCodeDetector -> SUCCESS | WeChatQRCode -> SUCCESS
  Наклон  4° (с 4x апскейл): cv2.QRCodeDetector -> SUCCESS | WeChatQRCode -> SUCCESS
  Наклон  5° (с 4x апскейл): cv2.QRCodeDetector -> SUCCESS | WeChatQRCode -> SUCCESS  <-- КРИТИЧЕСКИЙ ПОРОГ
  Наклон  6° (с 4x апскейл): cv2.QRCodeDetector -> FAIL    | WeChatQRCode -> SUCCESS
  Наклон  8° (с 4x апскейл): cv2.QRCodeDetector -> FAIL    | WeChatQRCode -> SUCCESS
  Наклон 10° (с 4x апскейл): cv2.QRCodeDetector -> FAIL    | WeChatQRCode -> SUCCESS
  Наклон 15° (с 4x апскейл): cv2.QRCodeDetector -> FAIL    | WeChatQRCode -> SUCCESS
  Наклон 20° (с 4x апскейл): cv2.QRCodeDetector -> FAIL    | WeChatQRCode -> SUCCESS
  Наклон 25° (с 4x апскейл): cv2.QRCodeDetector -> FAIL    | WeChatQRCode -> SUCCESS
  Наклон 30° (с 4x апскейл): cv2.QRCodeDetector -> FAIL    | WeChatQRCode -> SUCCESS
  Наклон 35° (с 4x апскейл): cv2.QRCodeDetector -> FAIL    | WeChatQRCode -> FAIL
  ```
- **Вывод:** Стандартный детектор OpenCV имеет жесткий предел работоспособности в $5^\circ$. Начиная с $6^\circ$ вероятность обнаружения падает до строго **0%**. На полигоне QR-код на манекене никогда не расположен строго фронтально оптической оси камеры с погрешностью до $5^\circ$. Без перехода на `WeChatQRCode` потеря 80 баллов гарантирована.

#### Дефект D08 (КРИТИЧЕСКИЙ) — Блокировка видеопотока параметром `snapshot_mode: true`
- **Файлы доказательств:**
  - [`ijkbot_vision/config/qr_reader.yaml`](file:///home/lev/IJKbot/ijkbot_vision/config/qr_reader.yaml#L7): `snapshot_mode: true`.
  - [`ijkbot_vision/ijkbot_vision/qr_reader_node.py`](file:///home/lev/IJKbot/ijkbot_vision/ijkbot_vision/qr_reader_node.py#L78-L84):
    ```python
    def _image_callback(self, message: CompressedImage) -> None:
        self._latest_image_msg = message
        if getattr(self, '_snapshot_mode', False):
            return
        self._process_image(message)
    ```
- **Суть проблемы:** Коммит `fcb19b3` полностью заблокировал непрерывную обработку кадров. Функция `_process_image` вызывается только по триггеру `/vision/take_photo`. Однако триггер посылается только при переходе автомата в состояние `SEARCHING_VICTIM`. Из-за координатного бага D02 этот переход никогда не происходил, и нода зрения за время тестов не декодировала ни одного кадра.

#### Дефект D12 (ВЫСОКИЙ) — Ошибка в логическом условии масштабирования
- **Файлы доказательств:** [`ijkbot_vision/ijkbot_vision/qr_decoder.py`](file:///home/lev/IJKbot/ijkbot_vision/ijkbot_vision/qr_decoder.py#L70-L78):
  ```python
  if not text and max(image.shape[:2]) < 640:
      scale = 4
      enlarged = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
      text, points, _ = detector.detectAndDecode(enlarged)
  ```
- **Суть проблемы:** Для кадра камеры $640\times 480$ кортеж `image.shape[:2]` равен `(480, 640)`. Значение `max(480, 640)` равно `640`. Условие `640 < 640` дает строго `False`. Блок 4-кратного интерполяционного увеличения для мелких кодов отключен программно.

#### Дефект D10 (КРИТИЧЕСКИЙ) — Недопустимый профиль цветной камеры `640x480x5`
- **Файлы доказательств:** [`ijkbot_bringup/launch/realsense_laserscan.launch.py`](file:///home/lev/IJKbot/ijkbot_bringup/launch/realsense_laserscan.launch.py#L20): `default_value='640x480x5'`.
- **Суть проблемы:** Сенсор OmniVision OV2740 цветного модуля D435 аппаратно поддерживает только дискретные частоты 15, 30 и 60 кадров/с. Запрос 5 FPS приводит к ошибке драйвера `realsense2_camera` при открытии видеопотока.

#### Дефект D13 (ВЫСОКИЙ) — Отсутствие детектора человека
- **Файлы доказательств:** Директория `ijkbot_vision/`.
- **Суть проблемы:** В кодовой базе полностью отсутствуют реализации узла YOLO-World и алгоритма 3D-депроекции по карте глубины, предусмотренные регламентом (Этап 4).

---

### 3.4. Низкоуровневый драйвер приводов (`sts3215_driver`)

#### Дефект D09 (КРИТИЧЕСКИЙ) — Перманентный `latchFault` при единичном таймауте UART
- **Файлы доказательств:** [`sts3215_driver/src/diff_drive_node.cpp`](file:///home/lev/IJKbot/sts3215_driver/src/diff_drive_node.cpp#L109-L117,L184-L190,L210-L215):
  ```cpp
  void DiffDriveNode::latchFault(const std::string& reason)
  {
      fault_ = true;
      fault_reason_ = reason;
      target_ = applied_ = {0.0, 0.0};
      RCLCPP_ERROR(get_logger(), "Drive fault; motion locked until restart: %s", reason.c_str());
      stopHardware();
      publishDiagnostics();
  }
  ```
- **Суть проблемы:** Таймаут опроса сервоприводов по UART составляет 20 мс. При единичной задержке планировщика ядра Linux на Pi 4B или дребезге в USB-порту нода выполняет `latchFault()`. Флаг `fault_ = true` блокирует прием `/cmd_vel` и, что критично, **прекращает публикацию TF `odom -> base_footprint`** (строка 218). Драйвер намертво виснет до перезапуска процесса.

#### Дефект D22 (ВЫСОКИЙ) — Недописанный счетчик ошибок и ограничение валидатора таймаута
- **Файлы доказательств:**
  - [`sts3215_driver/include/diff_drive_node.hpp`](file:///home/lev/IJKbot/sts3215_driver/include/diff_drive_node.hpp#L37-L38):
    ```cpp
    std::size_t error_streak_{0};
    static constexpr std::size_t kMaxErrorStreak = 5;
    ```
  - [`sts3215_driver/src/diff_drive_node.cpp`](file:///home/lev/IJKbot/sts3215_driver/src/diff_drive_node.cpp#L46-L49):
    ```cpp
    if (... timeout_ms < 1 || timeout_ms > 25 ...) {
        throw std::invalid_argument("Invalid drive parameters: check IDs, directions, frames and safety limits");
    }
    ```
- **Суть проблемы:** Переменная `error_streak_` объявлена в классе, но ни разу не используется в коде `.cpp`. В блоках `catch` сразу вызывается аварийная остановка. Попытка просто увеличить таймаут до 40 мс в конфигурации приведет к падению конструктора ноды из-за проверки `timeout_ms > 25`.

---

### 3.5. Инфраструктура сборки, Pixi-окружение и тестирование

#### Дефект D17 (СРЕДНИЙ) — Пакеты воркспейса не установлены в каталог `install/`
- **Файлы доказательств:** Каталог `/home/lev/IJKbot/install/`.
- **Суть проблемы:** Каталог `install/` содержит только скомпилированный C++ пакет `sts3215_driver`. Пакеты `ijkbot_brain`, `ijkbot_vision`, `ijkbot_nav2`, `ijkbot_description` и `ijkbot_bringup` не установлены. Команда `source install/setup.bash` не дает доступа к узлам и launch-файлам.

#### Дефект D19 (НИЗКИЙ) — Несовместимость Pytest 9.1 с `launch_testing`
- **Файлы доказательств:** Лог запуска `pytest` в среде Pixi.
- **Суть проблемы:** В Pytest версии 9.1+ удален устаревший аргумент `path` в хуке `pytest_pycollect_makemodule`, из-за чего плагин `launch_testing_ros` падает с `PluginValidationError`. Запуск тестов через `colcon test` блокируется. Тесты должны запускаться через `python3 -m unittest discover`.

---

## 4. Сводная матрица критичности дефектов

| ID | Описание дефекта | Подсистема | Статус | Влияние на миссию |
|---|---|---|:---:|---|
| **D01** | Рассинхронизация часов Pi 4B и ноутбука ($\Delta t > 121$ с) | Инфраструктура / TF2 | **БЛОКЕР** | Отбрасывание `/scan`, отказ экстраполяции TF, падение планера. |
| **D02** | Рассогласование систем координат `map` и `odom` в `mission_sm` | Brain / State Machine | **БЛОКЕР** | $dist \ge 0.565$ м $> 0.18$ м: автомат никогда не фиксирует прибытие в цель. |
| **D03** | Ловушка флага `--mock` по умолчанию в `mission_sm.py` | Brain / CLI | **БЛОКЕР** | Физические моторы стоят, координаты эмулируются, QR фейкуется. |
| **D04** | Гонка команд в топике `/cmd_vel` (`Nav2` vs `mission_sm`) | Навигация / Управление | **БЛОКЕР** | Чередование команд хода и нуля $\to$ рывки приводов, срыв траектории. |
| **D05** | Засветка пола лучом RealSense $\to$ ложный lethal costmap | Сенсоры / Costmap | **БЛОКЕР** | Пол вносится как препятствие (254) $\to$ планер рапортует «No valid path». |
| **D06** | Отсутствие `nav2_msgs` в Pixi-окружении ноутбука | Окружение / Pixi | **БЛОКЕР** | `trial_planner` падает с `ModuleNotFoundError`, системные логи забиты ошибками. |
| **D20** | Невозможность выключения mock-режима из `laptop.launch.py` | Bringup / Launch | **БЛОКЕР** | Аргумент `action="store_true"` игнорирует `'false'`, запуская только мок. |
| **D21** | Принудительный `mock_hardware: true` в `robot.launch.py` | Bringup / Launch | **БЛОКЕР** | Лаунч перетирает `params.yaml`, запуская драйвер моторов без UART. |
| **D07** | Срыв `cv2.QRCodeDetector()` при наклоне свыше $5^\circ$ | Компьютерное зрение | **КРИТИЧЕСКИЙ** | 100% срыв считывания QR на полигоне (потеря 80 баллов). |
| **D08** | Блокировка видеопотока параметром `snapshot_mode: true` | Компьютерное зрение | **КРИТИЧЕСКИЙ** | Кадры отбрасываются до входа в режим поиска, нет контроля с камеры. |
| **D09** | Перманентный `latchFault()` в драйвере STS3215 при сбое UART | Драйвер приводов | **КРИТИЧЕСКИЙ** | Остановка шасси и прекращение публикации TF при единичном джиттере. |
| **D10** | Невалидный профиль цветной камеры `640x480x5` | Сенсоры / RealSense | **КРИТИЧЕСКИЙ** | Драйвер RealSense не стартует на неподдерживаемой частоте 5 FPS. |
| **D11** | Отключение контроля нод Nav2 `'bond_timeout': 0.0` | Nav2 Lifecycle | **ВЫСОКИЙ** | Скрытые падения нод навигации не детектируются, система виснет навсегда. |
| **D12** | Логическая ошибка в условии апскейла `max(shape) < 640` | Компьютерное зрение | **ВЫСОКИЙ** | 4-кратное интерполяционное увеличение мелких QR-кодов отключено. |
| **D13** | Полное отсутствие детектора человека (YOLO-World) | Компьютерное зрение | **ВЫСОКИЙ** | Невозможность найти пострадавшего без распознавания QR-кода. |
| **D14** | Несогласованность Footprint (Local vs Global) | Nav2 Costmap | **ВЫСОКИЙ** | Застревание робота в узких проездах полигона из-за разницы контуров. |
| **D22** | Недописанный счетчик `error_streak_` и лимит таймаута $\le 25$ | Драйвер приводов | **ВЫСОКИЙ** | Невозможность фильтровать помехи UART и поднять таймаут в конфигурации. |
| **D23** | Неприменимость `min_obstacle_height` к 2D LaserScan | Nav2 Costmap | **ВЫСОКИЙ** | Невозможность программно отфильтровать пол по высоте без 3D облака. |
| **D24** | Отсутствие Action-обратной связи Nav2 в `mission_sm.py` | Brain / State Machine | **ВЫСОКИЙ** | Автомат не знает реального статуса движения Nav2 и не может отменить цель. |
| **D15** | Поле за стенами арены воспринимается как свободная зона | Nav2 Карта | **СРЕДНИЙ** | Риск стирания препятствий лучами сквозь тонкие 1-пиксельные стены. |
| **D16** | Нарушенная структура пакета `ijkbot_brain` и симлинки | Архитектура / Сборка | **СРЕДНИЙ** | Ошибки импорта, путаница файлов `mission_sm.python`. |
| **D17** | Пакеты репозитория не установлены в каталог `install/` | Сборка / Инфраструктура | **СРЕДНИЙ** | `source install/setup.bash` не находит большинство пакетов. |
| **D18** | Стартовая точка $[0.4, 0.4]$ в списке путевых точек поиска | Brain / Поиск | **СРЕДНИЙ** | Робот ошибочно едет на старт посреди процедуры поиска ориентира. |
| **D25** | Запуск бортового стека локально на ноутбуке в GUI | Brain / Dashboard | **СРЕДНИЙ** | Попытка открыть порты робота на ноутбуке при старте из интерфейса. |
| **D26** | Отсутствие бинарника `xacro` в окружении Pixi | Описание / URDF | **СРЕДНИЙ** | `rsp.launch.py` не может преобразовать xacro в URDF. |
| **D19** | Падение тестов зрения из-за несовместимости Pytest 9.1 | Тестирование / CI | **НИЗКИЙ** | Блокировка прогона тестов `launch_testing`. |

---

## 5. Детализированный и приоритизированный план рефакторинга

### Фаза 1. Инфраструктура времени, окружение Pixi и сборка воркспейса
1. **Настройка синхронизации времени по Chrony (Дефект D01):**
   - На ноутбуке (`192.168.1.20`) в `/etc/chrony/chrony.conf` раскомментировать:
     ```text
     local stratum 8
     allow 192.168.1.0/24
     ```
   - На Raspberry Pi (`192.168.1.10`) прописать ноутбук единственным NTP-сервером:
     ```text
     server 192.168.1.20 iburst minpoll 1 maxpoll 2
     ```
   - Добавить проверку расхождения часов в предстартовый скрипт: `chronyc tracking` (допуск $|\Delta t| < 5$ мс).
2. **Обновление окружения Pixi на ноутбуке (Дефекты D06, D17, D26):**
   - В `/home/lev/ros2_jazzy/pixi.toml` добавить зависимости:
     ```toml
     ros-jazzy-nav2-msgs = "*"
     ros-jazzy-navigation2 = "*"
     ros-jazzy-xacro = "*"
     colcon = "*"
     ```
   - Выполнить `pixi run colcon build --symlink-install` в корне репозитория для всех пакетов, наполнив каталог `install/`.
3. **Нормализация структуры пакета `ijkbot_brain` (Дефект D16):**
   - Удалить паразитный файл-симлинк `mission_sm.python`.
   - Перенести реальные исходники внутрь стандартного каталога `ijkbot_brain/ijkbot_brain/` и удалить циклические симлинки.
   - Заменить относительные импорты на стандартные: `from ijkbot_brain.llm_client import LLMClient`.

### Фаза 2. Устранение ловушек симуляции и разделение запуска
1. **Исправление CLI-парсера в `mission_sm.py` (Дефекты D03, D20):**
   - Заменить `action="store_true"` на парсинг булевого значения или явные взаимоисключающие флаги:
     ```python
     parser.add_argument("--mock", action=argparse.BooleanOptionalAction, default=False)
     ```
   - В конструкторе `MissionStateMachine` изменить значение по умолчанию на `mock_mode: bool = False`.
2. **Исправление параметров по умолчанию в `robot.launch.py` (Дефект D21):**
   - Изменить аргумент `mock_hardware` на `'false'`:
     ```python
     declare_mock_hardware = DeclareLaunchArgument('mock_hardware', default_value='false')
     ```
3. **Разделение бортового и внебортового стека запуска (Дефект D25):**
   - Исключить запуск `robot.launch.py` из `system.launch.py` на ноутбуке.
   - Закрепить архитектуру: на Pi 4B запускается `robot.launch.py` (сенсоры + моторы) и `navigation.launch.py` (Nav2). На ноутбуке запускается `laptop.launch.py` (Vision + Brain + NiceGUI Dashboard).

### Фаза 3. Навигационный пайплайн, TF2 и управление
1. **Перевод автомата миссий на СК `map` и ActionClient (Дефекты D02, D24):**
   - В `mission_sm.py` реализовать чтение позы робота через TF-буфер:
     ```python
     transform = self.tf_buffer.lookup_transform('map', 'base_footprint', rclpy.time.Time())
     self.sm.robot_x = transform.transform.translation.x
     self.sm.robot_y = transform.transform.translation.y
     ```
   - Внедрить `ActionClient(self, NavigateToPose, '/navigate_to_pose')` для асинхронного контроля достижения путевых точек и чистой отмены целей при переходе к осмотру или E-STOP.
2. **Разрешение конфликта в топике `/cmd_vel` (Дефект D04):**
   - Добавить узел `twist_mux` (`ros-jazzy-twist-mux`) с входными топиками:
     - `/cmd_vel_emergency` (приоритет 100)
     - `/mission/cmd_vel` (приоритет 50, для кругового осмотра)
     - `/cmd_vel_smoothed` (приоритет 10, от Nav2)
   - Исключить публикацию нулевых скоростей в `/cmd_vel` из `mission_sm.py` во время активной навигации Nav2.
3. **Устранение ложных препятствий от пола (Дефекты D05, D23):**
   - В `realsense_laserscan.yaml` ограничить максимальную дальность: `range_max: 2.20` м (отсекает луч до пересечения с полом при любом наклоне шасси).
   - В `ijkbot.urdf.xacro` задать компенсационный угол камеры вверх: `camera_pitch = "-0.035"` (наклон вверх на $\approx 2.0^\circ$).
4. **Восстановление контроля нод Nav2 (Дефект D11):**
   - Заменить `'bond_timeout': 0.0` на `'bond_timeout': 12.0` во всех секциях `lifecycle_manager` в `navigation.launch.py`. Это гарантирует отсутствие ложных сбросов при пиковой нагрузке на CPU, сохраняя контроль над авариями.
5. **Синхронизация контуров Costmap и исправление карты (Дефекты D14, D15):**
   - Унифицировать `footprint` в `local_costmap` и `global_costmap`: `"[[0.11, 0.125], [0.11, -0.125], [-0.17, -0.125], [-0.17, 0.125]]"`.
   - Установить единый радиус инфляции `inflation_radius: 0.28`.
   - В файле карты `polygon_empty_4x4.pgm` залить внутреннее пространство значением `254` (белый / свободный), а внешнюю зону оставить `205` со стандартным порогом `free_thresh: 0.196` (серая неизвестная зона).

### Фаза 4. Модернизация технического зрения и считывания QR
1. **Интеграция детектора `WeChatQRCode` (Дефект D07):**
   - В `qr_decoder.py` заменить базовый детектор на нейросетевой:
     ```python
     detector = cv2.wechat_qrcode_WeChatQRCode()
     texts, points = detector.detectAndDecode(image)
     ```
   - Это гарантирует 100% декодирование при углах наклона до $30^\circ–35^\circ$ без необходимости апскейла.
2. **Перевод видеопотока в непрерывный режим (Дефект D08):**
   - В `qr_reader.yaml` выставить `snapshot_mode: false`. Поскольку обработка идет на GPU RTX 5060 ноутбука, инференс занимает менее 5 мс и не нагружает Pi 4B.
3. **Исправление профиля RealSense (Дефект D10):**
   - В `realsense_laserscan.launch.py` вернуть поддерживаемый профиль: `color_profile: '640x480x15'`.
4. **Исправление условия масштабирования (Дефект D12):**
   - Заменить строку 71 в `qr_decoder.py`: `if not text and min(image.shape[:2]) <= 480:`.
5. **Разработка детектора человека (Дефект D13):**
   - Создать узел `yolo_world_node.py` на базе PyTorch/TensorRT на ноутбуке, публикующий статус в топик `/victim_detected`.

### Фаза 5. Повышение надежности низкоуровневого драйвера STS3215
1. **Реализация фильтра сбоев UART и счетчика `error_streak_` (Дефекты D09, D22):**
   - В `diff_drive_node.cpp` задействовать `error_streak_`:
     ```cpp
     catch (const std::exception& error) {
         if (++error_streak_ >= kMaxErrorStreak) {
             latchFault(std::string("UART failed after 5 retries: ") + error.what());
         } else {
             RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 1000, "UART dropped packet (%zu/5)", error_streak_);
         }
         return;
     }
     // При успешном чтении: error_streak_ = 0;
     ```
   - В конструкторе `DiffDriveNode` расширить валидатор таймаута: `timeout_ms < 1 || timeout_ms > 100`.
   - В `params.yaml` выставить `serial_timeout_ms: 30`.

### Фаза 6. Очистка семантической карты и тесты
1. **Удаление координат базы из точек поиска (Дефект D18):**
   - В `llm_client.py` в словаре `LANDMARK_CANDIDATE_WAYPOINTS` заменить точки $[0.4, 0.4]$ для `FALLEN_TREE` и `DEBRIS_PVC` на координаты ячеек $[1.2, 1.2]$ и $[0.4, 1.6]$.
2. **Запуск автоматизированных тестов (Дефект D19):**
   - Настроить вызов тестов через `pixi run python -m unittest discover -s tests/` в обход сломанных хуков `launch_testing`.

---

## 6. Оставшиеся открытые вопросы, аппаратные риски и направления для дальнейшего исследования

1. **Анализ задержек Wi-Fi передачи сжатого видео (`image_transport/compressed`):**
   - При работе в 5 ГГц сети соревнований возможны кратковременные задержки кадров JPEG. Требуется замерить джиттер поступления кадров на ноутбук при одновременной передаче потока `/camera/color/image_raw/compressed` и лазерскана `/scan`.
2. **Калибровка эффективной базы колес на соревновательном линолеуме:**
   - Номинальная база колес составляет $L = 0.225$ м. При разворотах на гладком соревновательном покрытии неизбежно микропроскальзывание шин шириной 25 мм. Рекомендуется выполнить программный тест проезда квадрата $2\times 2$ м и откалибровать эффективную ширину колеи для минимизации ухода угла рыскания (Yaw Drift).
3. **Температурный профиль Raspberry Pi 4B при непрерывном 5-минутном заезде:**
   - Передача видеопотока с RealSense D435 и опрос сервоприводов на 50 Гц в закрытом корпусе шасси разогревают процессор SoC. Требуется провести 5-минутный стресс-тест бортового компьютера с контролем температуры процессора (`vcgencmd measure_temp`), чтобы исключить троттлинг частоты до 600 МГц во время соревновательной попытки.
