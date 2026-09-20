# IJKbot
Актуальное состояние этапов: [PLAN.md](PLAN.md). Результаты проверки и
ограничения автономного запуска: [REVIEW.md](REVIEW.md).
Репозиторий двуколёсной мобильной платформы, созданной специально под Кубок РТК в Ижевске.
Хар-ки робота
Бортовой компьютер: Raspberry Pi 4b
Приводы: Сервомоторы ST3215
Камера: Realsense D435
Аккумулятор: 14.8В 5000mAh

Текущий этап — драйвер дифференциального привода: [инструкция и проверки](sts3215_driver/README.md).
QR-код состояния пострадавшего считывается отдельной нодой на ноутбуке:
[инструкция QR Reader](ijkbot_vision/README.md).
LLM получает сетку и разрешённые точки подъезда из
[arena.json](ijkbot_brain/config/arena.json), публикует `geometry_msgs/PoseStamped`
в `/goal_pose`, а Nav2 принимает этот топик как цель. Координаты вне списка в
`arena.json` не публикуются.

Для проверки цепочки на ноутбуке запусти Nav2 и один интерпретатор команд:

```bash
source /opt/ros/jazzy/setup.bash
source install/setup.bash
export ROS_DOMAIN_ID=42
ros2 launch ijkbot_nav2 navigation.launch.py
# в другом терминале
ros2 run ijkbot_brain llm_client
```

Текст подаётся в `/mission/judge_task`; результатом будет `PoseStamped` в
`/goal_pose`. Для объектов без внесённой точки подъезда LLM должна вернуть
`nav2_goal: null`, и робот останется на месте.
Геометрия ведущей пары: диаметр шин 75 мм, ширина 25 мм, колея по центрам 225 мм.
ID левого/правого привода — 1/2. Расстояние между передней и задней осью — 140 мм.

```bash
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install --packages-select sts3215_driver
source install/setup.bash
ros2 launch sts3215_driver driver.launch.py
```

По умолчанию запускается mock: UART не открывается, моторы не включаются.

## Испытание: цель → 5 секунд → старт

Планер `trial_planner` принимает `PoseStamped` в `/goal_pose` от LLM или RViz.
Он отправляет цель через action `/navigate_to_pose`, ждёт успешный результат,
держит нулевую скорость минимум 5 секунд и возвращается в центр стартовой
ячейки: `map (0.4, 0.4)`, yaw=0. Завершение возврата также подтверждает Nav2.
QR и детектор человека для этой последовательности не требуются.

При уже запущенных драйвере, TF и датчиках запускайте **вместо обычного
navigation.launch.py**:

```bash
source /opt/ros/jazzy/setup.bash
source install/setup.bash
export ROS_DOMAIN_ID=42
ros2 launch ijkbot_nav2 trial.launch.py
```

В этом запуске `/goal_pose` принимает только планер, а прямой вход Nav2
перенесён на `/nav2/manual_goal_pose`. Не запускайте одновременно старый
`mission_sm` или второй экземпляр Nav2: они могут отправлять конкурирующие цели.
LLM запускается обычной командой `ros2 run ijkbot_brain llm_client`;
публикация цели запускает испытание сразу. Для ручной проверки:

```bash
ros2 topic pub --once /goal_pose geometry_msgs/msg/PoseStamped \
  '{header: {frame_id: map}, pose: {position: {x: 2.0, y: 0.4}, orientation: {w: 1.0}}}'
ros2 topic echo /trial/state
```

Состояния: `IDLE → OUTBOUND → HOLDING → RETURNING → COMPLETE`.
Удержание подтверждается свежей `/odom`: линейная скорость <0.01 м/с,
угловая <0.02 рад/с. Движение или пауза одометрии >0.5 с сбрасывает отсчёт.
При отказе Nav2 или превышении 300 с планер переходит в `FAILED`, отменяет
цель и публикует нулевую скорость. Новые цели во время миссии отклоняются.
`/emergency_stop` (`std_msgs/msg/Bool`, `true`) отменяет цель и останавливает
миссию; после `false` нужна новая цель, автоматического продолжения нет.
Статусы и переходы пишутся в `/trial/state` и ROS-лог.

Это реализация указанного сценария испытания; полный эвакуационный сценарий
с обнаружением человека и QR остаётся отдельной задачей. Приёмка на роботе
ещё требуется.
