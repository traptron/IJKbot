# QR Reader

`qr_reader_node` запускается на ноутбуке. Он принимает JPEG-кадры RealSense,
декодирует QR через OpenCV и публикует исходный текст только после одинакового
результата в нескольких последовательных кадрах.

## Топики

| Направление | Топик | Тип | Назначение |
|---|---|---|---|
| Вход | `/camera/color/image_raw/compressed` | `sensor_msgs/msg/CompressedImage` | Сжатый цветной поток с Raspberry Pi |
| Выход | `/victim_status` | `std_msgs/msg/String` | Подтверждённый текст QR-кода |
| Выход | `/vision/qr/detected` | `std_msgs/msg/Bool` | Наличие QR в последнем кадре |

Имя входного топика передаётся параметром `image_topic`: если драйвер камеры
публикует `/camera/camera/color/image_raw/compressed`, укажите его при запуске.

## Установка и запуск

На ноутбуке должны быть ROS 2 Jazzy, `python3-opencv` и `python3-numpy`:

```bash
sudo apt install python3-opencv python3-numpy
cd ~/IJKbot
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install --packages-select ijkbot_vision
source install/setup.bash
ros2 launch ijkbot_vision qr_reader.launch.py
```

Для другого имени цветного топика:

```bash
ros2 run ijkbot_vision qr_reader_node --ros-args \
  -p image_topic:=/camera/camera/color/image_raw/compressed
```

Проверка результата:

```bash
ros2 topic echo /victim_status --once
```

Нода использует Best Effort / Keep Last с очередью 1 кадр. Это ограничивает
очередь при медленном декодировании. Значение `confirm_frames` по умолчанию равно 3. Текст сохраняется и
передаётся как есть, без предположений о его медицинской структуре.

Пробелы и переводы строк сохраняются. Пустой или повреждённый кадр сбрасывает
подтверждение. Повтор кадра с той же ненулевой меткой времени не учитывается.
После паузы потока более секунды счётчик также сбрасывается, а
`/vision/qr/detected` становится false. Этот флаг означает успешное декодирование,
а не просто наличие похожего на QR квадрата.

Пока код виден, результат подтверждается заново и повторно публикуется примерно
раз в секунду: поздно запущенный brain и следующая миссия тоже получают данные.
Автомат принимает текст только в состоянии `READING_QR`. Если QR не прочитан,
он остаётся в ожидании, без автоматического объявления успеха.

## Вывод в существующий веб-интерфейс LLM

Карточка QR в веб-интерфейсе показывает последний подтверждённый текст
`/victim_status` во всех состояниях, включая ожидание и удержание планера.
Показывается время последнего получения; текст остаётся после исчезновения
QR из кадра. Сброс миссии очищает карточку. Пробелы и переводы строк в данных
сохраняются; текст выводится как текст, не как HTML. Получение QR для отображения
не запускает возврат робота и не начисляет баллы автоматически.

При работающей RealSense на роботе запустите на ноутбуке:

```bash
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install --packages-select ijkbot_vision ijkbot_brain
source install/setup.bash
export ROS_DOMAIN_ID=42
ros2 launch ijkbot_brain dashboard_qr.launch.py
```

Откройте `http://localhost:8080`, карточку «Данные QR-кода пострадавшего».
Другой топик камеры задаётся аргументом `image_topic:=/camera/camera/color/image_raw/compressed`.
Если веб-интерфейс уже запущен, перезапустите его после сборки и отдельно
запустите только `ros2 launch ijkbot_vision qr_reader.launch.py`.
Не запускайте второй экземпляр интерфейса на том же порту.

В двух компьютерах установите `ROS_DOMAIN_ID=42`. RealSense запускается на Pi
через `ros2 launch ijkbot_bringup realsense_laserscan.launch.py`.
Видеопоток и распознавание с реальной D435 ещё требуют аппаратной проверки.
Текущие тесты используют синтетический JPEG и ROS-сообщения.

Проверки после сборки и `source install/setup.bash`:
```bash
python3 -m pytest -q ijkbot_vision/test
```
