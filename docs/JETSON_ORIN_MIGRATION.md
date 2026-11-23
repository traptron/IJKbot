# IJKbot на Jetson Orin Nano 8GB

На проверенном Orin Nano Super установлены Ubuntu 24.04.5, Jetson Linux
39.2.2 и ROS 2 Jazzy. Jetson выполняет управление, одометрию, TF и Nav2.
LLM и интерфейс остаются на ноутбуке. D435 сначала проверяется на стенде
без приводов и с локальным ROS-графом. На борту сравниваются захват,
декодирование QR и нагрузка системы.

[Jetson Linux 39.2.2](https://docs.nvidia.com/jetson/archives/r39.2.2/DeveloperGuide/index.html)
и [ROS 2 Jazzy для Ubuntu 24.04](https://docs.ros.org/en/jazzy/Installation/Ubuntu-Install-Debs.html).

## Подготовка платы и сборка

Перед подключением приводов проверьте модель, ОС, USB и окружение.
Укажите путь рабочего каталога и фактические порты. Для лидара желательно
использовать путь `/dev/serial/by-id/…`, если он присутствует. Сопоставьте
его с устройством через `udevadm info --query=property --name=ПОРТ`.
Адаптер Waveshare должен иметь отдельный путь `/dev/ttySTS` по
[правилу udev](../src/driver/udev/99-waveshare.rules). Права применяйте
к фактическому пользователю Orin и проверяйте после нового входа.

```bash
lsusb
lsusb -t
bash scripts/jetson_preflight.sh --workspace "$PWD"
```

Скопируйте выбранную ревизию IJKbot в отдельный каталог Orin. Для ревизии
с незакоммиченными правками перенесите нужные файлы поверх чистой копии.
Собирайте `build/` и `install/` на arm64. Запишите SHA IJKbot, версию L4T
и версии ROS, OpenCV, librealsense и драйвера камеры.

На чистой Ubuntu установите Jazzy arm64 и инструменты из официального
репозитория ROS. Для проверенной платы `ros-jazzy-ros-base` и
`ros-dev-tools` уже были установлены. В корне новой копии:

```bash
git clone --no-checkout https://github.com/Slamtec/sllidar_ros2.git src/sllidar_ros2
git -C src/sllidar_ros2 checkout --detach 34300099fadfc772965962dec837bf436706188f
source /opt/ros/jazzy/setup.bash
# sudo rosdep init — только если rosdep ещё не настроен
rosdep update
rosdep install --simulate --from-paths src --ignore-src --rosdistro jazzy \
  --skip-keys=ament_python
```

Здесь `ament_python` указан как тип сборки ROS-пакета. Его выбирает
colcon с установленными `ros-dev-tools`. Отдельного ключа rosdep нет.
Просмотрите план apt перед установкой. На проверенной системе OpenCV
4.6 из Ubuntu уже содержал пакеты `libopencv-dev` и
`libopencv-contrib-dev`, тогда как репозиторий NVIDIA предлагал
`libopencv-dev` 4.8. Сохраняйте согласованный комплект OpenCV с
`wechat_qrcode`. Остановитесь, если apt предлагает удалить пакеты,
сменить OpenCV ABI или обновить Jetson Linux.

```bash
rosdep install --from-paths src --ignore-src --rosdistro jazzy \
  --skip-keys=ament_python
rosdep check --from-paths src --ignore-src --rosdistro jazzy \
  --skip-keys=ament_python
colcon build --symlink-install --packages-up-to bringup vision_cpp \
  --cmake-args -DCMAKE_BUILD_TYPE=Release -DBUILD_VIDEO_VIEWER=OFF
source install/setup.bash
colcon build --symlink-install --packages-select bringup
colcon test --packages-select driver vision_cpp
colcon test-result --verbose
ros2 pkg prefix bringup
ros2 launch bringup jetson_d435.launch.py --show-args
```

Проверьте зависимость `rmw_cyclonedds_cpp` в preflight и пакет
`realsense2_camera` через `ros2 pkg prefix`. При сбое штатного UVC
сверьте firmware D435 и SDK, а затем проверьте совместимую пару
librealsense и ROS wrapper с RSUSB в отдельном окружении.
[Документация RealSense для Jetson](https://github.com/realsenseai/librealsense/blob/master/doc/installation_jetson.md).

## Mock и связь с ноутбуком

На Orin запустите Jazzy с собранным overlay. Используйте свободный
стендовый домен 87 и держите приводы физически отключёнными:

```bash
env -u CYCLONEDDS_URI -u ROS_STATIC_PEERS -u ROS_LOCALHOST_ONLY \
  RMW_IMPLEMENTATION=rmw_cyclonedds_cpp ROS_DOMAIN_ID=87 \
  ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST \
  ros2 launch bringup system.launch.py enable_robot:=true enable_nav:=true \
    enable_camera:=false enable_lidar:=false enable_brain:=false \
    enable_qr:=false mock_hardware:=true
```

В отдельном терминале Orin с теми же параметрами DDS проверьте
`ros2 lifecycle get /controller_server`, сообщения `/odom`, `/diagnostics`
и преобразования `ros2 run tf2_ros tf2_echo map base_footprint` и
`ros2 run tf2_ros tf2_echo base_footprint camera_link`. Диагностика должна
показывать режим mock. Для проверки лидара после подключения USB запустите
`robot.launch.py enable_motors:=false enable_lidar:=true enable_camera:=false`
с подтверждённым портом. Проверьте `/scan_raw`, `/scan` и `lidar_link`.

Для проверки с ноутбука запустите отдельный mock-драйвер на Orin
в домене 42 с уникальными именами топиков. Используйте CycloneDDS
с сетевым обнаружением на обоих хостах либо укажите адреса peers.

```bash
ROS_DOMAIN_ID=42 RMW_IMPLEMENTATION=rmw_cyclonedds_cpp \
  ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET \
  ros2 run driver diff_drive_node --ros-args -p mock_hardware:=true \
    -r __ns:=/ijk_orin_mock -r /tf:=/ijk_orin_mock/tf
```

На ноутбуке подтвердите `/ijk_orin_mock/odom` и `/ijk_orin_mock/tf`
через `ros2 topic echo --once`. Запуском и остановкой mock убедитесь,
что источник появляется и исчезает. Уникальный префикс изолирует эту
телеметрию и `cmd_vel` от роботов в домене 42.

Для штатной диагностики на ноутбуке сохраните копию существующего
`config/ijk.local.yaml`. Добавьте следующие поля в существующий YAML
и замените путь каталогом, который собран на Orin:

```yaml
network:
  default_user: orin
  remote_ws: /home/orin/IJKbot
  known_hosts: ["10.124.170.245"]
hardware:
  camera:
    type: realsense
  motors:
    port: /dev/ttySTS
  lidar:
    port: /dev/ttyUSB0  # Замените подтверждённым путём, предпочтительно by-id.
```

Проверьте `ssh -o BatchMode=yes orin@10.124.170.245 true`, затем
`./ijk --host 10.124.170.245 doctor`. Парольный интерактивный вход подходит
для сборки. Для `ijk` настройте ключ или используйте уже
настроенный SSH ControlMaster. При возврате на Pi завершите процессы Orin,
восстановите сохранённый override, укажите хост Pi и повторите `doctor`.

## Камера D435 и QR

Подключите D435 по USB 3, проверьте скорость соединения через `lsusb -t`.
Если доступна утилита `rs-enumerate-devices`, запишите модель, firmware
и режимы кадра. Запустите стенд из собранного окружения Orin:

```bash
ros2 launch bringup jetson_d435.launch.py enable_qr:=true
```

Параметры `color_profile` и `depth_profile` по умолчанию запрашивают
640×480 при 15 кадрах/с. Если камера не выдаёт поток с этой парой, задайте
поддерживаемые профили из инвентаризации и проверьте фактический
размер и FPS. Стенд устанавливает домен 88 и привязывает CycloneDDS к
`lo` для всех дочерних узлов. Глубина и RGB доступны из второго
терминала на Orin. В нём укажите ту же конфигурацию:

```bash
unset ROS_STATIC_PEERS ROS_LOCALHOST_ONLY
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp ROS_DOMAIN_ID=88
export ROS_AUTOMATIC_DISCOVERY_RANGE=SYSTEM_DEFAULT
export CYCLONEDDS_URI='<CycloneDDS><Domain><General><Interfaces><NetworkInterface name="lo"/></Interfaces><AllowMulticast>false</AllowMulticast></General><Discovery><ParticipantIndex>auto</ParticipantIndex><Peers><Peer address="127.0.0.1"/></Peers></Discovery></Domain></CycloneDDS>'
ros2 topic list -t --no-daemon
timeout 10s ros2 topic echo --no-daemon --once --no-arr \
  --qos-profile sensor_data /camera/color/image_raw sensor_msgs/msg/Image
timeout 10s ros2 topic echo --no-daemon --once --no-arr \
  --qos-profile sensor_data /camera/depth/image_rect_raw sensor_msgs/msg/Image
timeout 10s ros2 topic echo --no-daemon --once --no-arr \
  --qos-profile sensor_data /camera/color/image_raw/compressed sensor_msgs/msg/CompressedImage
timeout 20s ros2 topic echo --no-daemon --once /victim_status std_msgs/msg/String
```

Подтвердите CameraInfo для RGB и глубины и ненулевые возрастающие
timestamps. Если wrapper публикует другие имена, сначала проверьте
их через `topic list -t` и `topic info --verbose`. Убедитесь, что
доступен плагин `compressed_image_transport`. Стенд использует обычный
`rs_launch.py` с отдельным процессом камеры, чтобы не отключать
`image_transport` выбором intra-process для RealSense.

Запустите две те же сырые подписки с ноутбука на доменах 42 и 88 без
loopback-настроек, пока локальные подписки подтверждают захват.
Обе удалённые подписки должны дать таймаут. Убедитесь, что локального
издателя PointCloud2 нет. При переподключении USB проверьте, что потеря
потока видна в логах или по таймауту подписки, а после перезапуска
камеры поступают новые кадры. Для диагностики запускайте
`jetson_d435.launch.py` без `enable_qr:=true`.

Используйте QR известного содержания. Запишите размер, дистанцию,
освещение и точный декодированный текст. При воспроизведении JPEG
подавайте кадры с интервалом больше периода декодирования и контролируйте
выдачу `/victim_status` и `/vision/qr/image/compressed`. Проверьте два
разных ненулевых timestamps, повтор последнего кадра и третий новый
кадр. Результат должен появиться после третьего успешного декодирования.
Для отрицательных кадров и теста отключения USB используйте свежий
сеанс. Принудительный снимок `/jetson_bench_qr/take_photo` для этого
сценария не используется.

При проверке принятия QR публикуйте записанный текст как
`std_msgs/msg/String` в `/victim_status` на отдельном mock-стенде
миссии. В `READING_QR` проверьте `qr_scanned` и переход в
`WAIT_5_SECONDS`. В `IDLE` проверьте, что флаг и состояние не меняются.
Запись о получении текста сама по себе не подтверждает принятие.

## Замеры и стендовая остановка

Проведите три одинаковых десятиминутных прогона без приводов:
mock/Nav2, mock/Nav2 с D435, mock/Nav2 с D435 и QR. Зафиксируйте
сцену, профили камеры, режим питания (`nvpmodel -q`), версии пакетов,
частоты и возраст кадров, вытеснение из очереди по `QR worker` в логах
и пропуски на захвате по интервалам timestamps. Используйте
`timeout 600s tegrastats --interval 1000` с перенаправлением в журнал
для каждого прогона. При наличии `trtexec` запишите версию и вывод
`--help`. Для задержки QR вычитайте acquisition stamp из времени
приёма соответствующего evidence на Orin. Нулевые или несопоставимые
метки не включайте. Сохраняйте отдельные замеры для p95/p99.
При сравнении будущего FP16 детектора используйте одинаковые записи,
модель и настройки обработки.

Физическая проверка начинается после успешных mock-прогонов, проверки
портов и вывешивания колёс. При 0,10 м/с синхронно запишите команды
и наблюдаемую скорость обоих колёс до и после потери команд.
В качестве контрольных порогов при этой скорости используйте начало
торможения в пределах 300 мс и оба остановленных колеса к 700 мс.
Это стендовые пороги наблюдения, соответствующие окну действующего
mock-теста. Параметр watchdog остаётся 200 мс. Отметьте разрешение
измерения, повторите под нагрузкой камеры и QR и считайте превышение
порога любым колесом провалом. Проверки на движение в поле требуют
отдельных измерений тормозного пути и покрытия сенсоров.
