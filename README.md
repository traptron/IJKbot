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
в `/nav2_goal`, а Nav2 принимает этот топик как цель. Координаты вне списка в
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
`/nav2_goal`. Для объектов без внесённой точки подъезда LLM должна вернуть
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
