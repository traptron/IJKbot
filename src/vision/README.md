# CSI-камера Raspberry Pi и QR

`rpi_camera_node` получает кадры CSI-камеры через GStreamer `libcamerasrc`
(libcamera), публикует только JPEG 640×480, по умолчанию 10 кадров/с.
Нода `qr_reader_node` декодирует текст QR и подтверждает его в трёх кадрах.
Захват выполняется в отдельном потоке; при зависании или отключении камеры
процесс захвата перезапускается. В очереди хранится только последний кадр.

Маркировка платы камеры не используется для угадывания сенсора: камера должна
определяться libcamera. На Ubuntu 24.04 установите системные компоненты:

```bash
sudo apt install libcamera-tools gstreamer1.0-tools gstreamer1.0-libcamera \
  gstreamer1.0-plugins-base gstreamer1.0-plugins-good python3-opencv python3-numpy
cam -l
```

Если `cam -l` не показывает камеру, сначала проверьте CSI-шлейф и поддержку
сенсора в конфигурации загрузки ОС. Нода не меняет настройки загрузчика.

Сборка и запуск на Pi:

```bash
cd ~/IJKbot
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install --packages-select vision
source install/setup.bash
export ROS_DOMAIN_ID=42
ros2 launch vision rpi_qr.launch.py
```

Этот запуск не требует состояния миссии, не сохраняет фотографии на диск
и не запускает моторы. Параллельный запуск RealSense с тем же топиком камеры
или второго QR-декодера необходимо исключить.

Топики:

- `/camera/color/image_raw/compressed` — JPEG `sensor_msgs/CompressedImage`.
- `/victim_status` — подтверждённый исходный текст QR (`std_msgs/String`).
- `/vision/qr/detected` — найден ли QR в обрабатываемом кадре.
- `/vision/qr/image/compressed` — подтверждённый кадр с рамкой QR.

```bash
ros2 topic echo /victim_status
```

Для нескольких камер передайте `camera_name:=...`, соответствующий имени
libcamera. `confirm_frames:=3` задаёт число подтверждений. Параметр
`enable_reader:=false` запускает только захват: существующий декодер на
ноутбуке может получать этот же сжатый топик.

Проверка без камеры:

```bash
ros2 launch vision rpi_qr.launch.py mock_hardware:=true
```

Тестовый источник публикует цветную таблицу, а не QR. Для проверки
распознавания покажите реальный QR либо запустите тесты `test_csi_capture.py`.

Параметры отдельной ноды: `fps` (1–15), `jpeg_quality` (1–100), `camera_name`,
`image_topic`, `frame_id`, `mock_hardware`. Кадры помечаются временем получения
JPEG на Pi, не аппаратным временем экспозиции. `camera_optical_frame` описывает
оптическую систему камеры; внешнее TF-крепление CSI-камеры эта нода не задаёт.
Для чтения текста QR калибровка и глубина не нужны.

Документация источника: https://libcamera.org/getting-started.html
