# CSI-камера Raspberry Pi и QR

Launch-файлы по умолчанию запускают C++17-ноды пакета `vision_cpp`.
`rpi_camera_node` получает кадры CSI-камеры OV5647 через прямой захват
V4L2 mmap и публикует только JPEG 640×480, по умолчанию 10 кадров/с (качество 85).
Нода `qr_reader_node` декодирует текст QR и подтверждает его в трёх кадрах.
Захват выполняется в отдельном потоке; при зависании или отключении камеры
захват перезапускается. В очереди хранится только последний кадр.
Такой захват выбран для текущей Ubuntu на Pi: установленный `libcamera`
падает при первом кадре. Packed Bayer RAW10 преобразуется в JPEG с балансом
цвета, умеренным усилением насыщенности и адаптивным подъёмом тёмных кадров.
Ограничение FPS выполняется до преобразования RAW и JPEG-кодирования.
Цветокоррекция использует LUT вместо полноразмерных массивов float32.
Оптимизированные таблицы Хаффмана уменьшают размер JPEG без изменения
декодированных пикселей. Разрешение, качество JPEG и алгоритмы QR сохранены.
QR работает в отдельном потоке: WeChatQRCode, затем QRCodeDetector, включая
увеличение мелких кодов в 2 и 4 раза. Аннотированный JPEG создаётся только
после подтверждения и из уже декодированного изображения.

Маркировка платы камеры не используется для угадывания сенсора: камера должна
определяться `libcamera`. На Ubuntu 24.04 установите системные компоненты:

```bash
sudo apt install libcamera-tools gstreamer1.0-tools gstreamer1.0-libcamera \
  gstreamer1.0-plugins-base gstreamer1.0-plugins-good v4l-utils \
  libopencv-dev python3-opencv python3-numpy
sudo usermod -aG video "$USER"
cam -l
```

После добавления в группу `video` войдите в систему заново. Если `cam -l`
не показывает камеру, сначала проверьте CSI-шлейф и поддержку
сенсора в конфигурации загрузки ОС. Нода не меняет настройки загрузчика.

Сборка и запуск на Pi:

```bash
cd ~/IJKbot
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install --packages-select vision_cpp vision --cmake-args -DCMAKE_BUILD_TYPE=Release
source install/setup.bash
export ROS_DOMAIN_ID=42
ros2 launch vision rpi_qr.launch.py
```

Пакет C++ можно запускать без Python-пакета `vision`:
`ros2 launch vision_cpp rpi_qr.launch.py`. Старые Python-ноды сохранены для
сравнения и отката: `ros2 launch vision rpi_qr.launch.py implementation:=vision`.
По умолчанию C++ захватывает 1920×1080 (1080p), JPEG Q95, до 6 кадров/с.
Аргументы `width`, `height`, `fps` и `jpeg_quality` позволяют изменить режим.
Сенсор должен поддерживать запрошенное разрешение; увеличения VGA программно нет.

Этот запуск не требует состояния миссии, не сохраняет фотографии на диск
и не запускает моторы. Параллельный запуск RealSense с тем же топиком камеры
или второго QR-декодера необходимо исключить.

Топики:

- `/camera/qr/image/compressed` — полный JPEG 1920×1080 для распознавания на Pi.
- `/camera/color/image_raw/compressed` — JPEG-превью 640×480 для Wi-Fi.
- `/victim_status` — подтверждённый исходный текст QR (`std_msgs/String`).
- `/vision/qr/detected` — найден ли QR в обрабатываемом кадре.
- `/vision/qr/image/compressed` — подтверждённый кадр с рамкой QR.

```bash
ros2 topic echo /victim_status
```

Для нескольких камер передайте `camera_name:=...`, соответствующий имени
libcamera. `confirm_frames:=3` задаёт число подтверждений. Параметр
`enable_reader:=false` запускает только захват: существующий декодер на
ноутбуке может получать сжатое VGA-превью. Для распознавания в 1080p
декодер запускается на Pi и подписывается на `/camera/qr/image/compressed`.

Проверка без камеры:

```bash
ros2 launch vision rpi_qr.launch.py mock_hardware:=true
```

Тестовый источник публикует цветную таблицу, а не QR. Для проверки
распознавания покажите реальный QR либо запустите тесты `test_csi_capture.py`.

Параметры отдельной ноды: `fps` (1–15), `jpeg_quality` (1–100), `camera_name`,
`image_topic`, `frame_id`, `mock_hardware`, `backend` (`v4l2_raw` по умолчанию
или `libcamera`), `exposure`, `analogue_gain`. Прямой захват ожидает OV5647
на `/dev/video0` и субустройство
`/dev/v4l-subdev0`; выдержка и усиление
задаются до старта видеопотока. Кадры помечаются временем получения
JPEG на Pi, не аппаратным временем экспозиции. `camera_optical_frame` описывает
оптическую систему камеры; внешнее TF-крепление CSI-камеры эта нода не задаёт.
Для чтения текста QR калибровка и глубина не нужны.

Документация источника: https://libcamera.org/getting-started.html

# QR в судейском веб-интерфейсе через SSH-поток

Если DDS-видеопоток с Raspberry Pi недоступен, соберите `vision_cpp` на Pi и
ноутбуке. Камеру должен захватывать только один процесс: перед SSH-запуском
остановите отдельный `rpi_qr.launch.py` на Pi, оставив моторы и лидар запущенными.
Откройте управляющее SSH-соединение в отдельном терминале:

```bash
ssh -M -N -S /tmp/ijkbot-camera-new.sock otmorozki@10.18.233.154
```

Запустите веб-интерфейс `brain.dashboard_app --no-mock`, а на ноутбуке —
`./scripts/start_qr_stream.sh otmorozki@10.18.233.154` после `source` ROS 2 и
`install/setup.bash`. Адрес замените на текущий IP Pi; пароль в скриптах не хранится.
Мост и декодер должны использовать `ROS_DOMAIN_ID=42`. При таком запуске не
включайте второй QR-reader в дашборде: скрипт уже запускает один C++-декодер.
SSH-поток несёт только сжатые JPEG-кадры. Мост публикует распознанный текст в
`/victim_status` и снимок с рамкой QR в `/vision/qr/image/compressed`;
они появляются в карточке «Данные QR-кода пострадавшего» по адресу
`http://<IP-ноутбука>:8080/`. Цель возврата в стартовую ячейку выдаётся только
после пяти секунд остановки с момента получения QR во время миссии.

Захват, кодирование, SSH-мост и распознавание выполняются на C++; Python-скрипты
`csi_jpeg_stream.py` и `qr_ssh_preview.py` оставлены только как прежняя реализация.
Мост передаёт исходные JPEG без декодирования/повторного кодирования и не
блокируется на окне предпросмотра. Видео доступно по тому же ROS-топику.

Проверка и измерения:

```bash
colcon test --packages-select vision_cpp
colcon test-result --test-result-base build/vision_cpp
PYTHONPATH=src/vision:$PYTHONPATH python3 src/vision_cpp/test/compare_encoder.py \
  install/vision_cpp/lib/vision_cpp/csi_jpeg_stream
python3 scripts/measure_video.py --seconds 10
```

Сравнение проверяет RAW10, тёмные/мелкие QR, побитовое равенство декодированных
пикселей, размер потока и повреждённый ввод. ROS-тест проверяет фильтр состояния
миссии, подтверждение по разным кадрам, снимок по триггеру и мок камеры.
Результат синтетических тестов не заменяет проверку реального QR на нужной
дистанции и при освещении полигона. Полоса в `measure_video.py` учитывает только
полезные JPEG-байты, без накладных расходов DDS/SSH/Wi-Fi.
Прямой захват использует [V4L2 mmap API](https://docs.kernel.org/userspace-api/media/v4l/mmap.html).
