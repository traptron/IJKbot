# Инструкция по запуску Intel RealSense D435 на Raspberry Pi 4B (ROS 2 Jazzy)

Данный документ описывает регламент подключения, настройки и запуска камеры **Intel RealSense D435** на бортовом компьютере **Raspberry Pi 4B** для мобильного робота **IJKbot**.

---

## 1. Назначение и профиль работы

Камера RealSense D435 решает две ключевые задачи:
1. **Сенсор препятствий для Nav2**: срез карты глубины (Depth) преобразуется нодой `depthimage_to_laserscan` в 2D лазерскан (`/scan`) непосредственно на Raspberry Pi для мгновенного обнаружения препятствий локальным costmap.
2. **Зрение для ноутбука**: цветной поток (RGB) передается по Wi-Fi на ноутбук в сжатом виде (`image_transport/compressed`) для поиска ориентиров через YOLO-World и считывания QR-кодов.

### Целевой профиль (оптимизирован под Raspberry Pi 4B):
- **Разрешение RGB и Depth**: `640x480`
- **Частота кадров (FPS)**: `15 FPS` (в 2 раза снижает нагрузку на CPU по сравнению с 30 FPS, достаточно для скорости движения $0.25\text{ м/с}$)
- **Выравнивание глубины (`align_depth.enable`)**: `true`
- **Синхронизация потоков (`enable_sync`)**: `true`
- **Облако точек (`pointcloud.enable`)**: **`false`** *(КРИТИЧНО: генерация PointCloud2 на 4-ядерном CPU Cortex-A72 вызывает 100% загрузку и троттлинг)*

---

## 2. Аппаратные требования и подключение

> [!IMPORTANT]
> 1. **Порт USB 3.0**: Подключайте камеру **только в синий порт USB 3.0** на Raspberry Pi 4B. В черных портах USB 2.0 камера инициализируется в урезанном режиме USB 2.1, где многие разрешения и связки потоков заблокированы.
> 2. **Качественный кабель**: Используйте короткий экранированный кабель USB Type-C на USB 3.0 Type-A.
> 3. **Питание**: RealSense D435 в пиках потребляет до 1.5–2 А. Питание Raspberry Pi должно обеспечивать 5В $\ge 3$А (качественный BEC от аккумулятора 14.8В).

### Проверка подключения на уровне ОС:
```bash
# 1. Проверка обнаружения устройства
lsusb | grep -i intel

# 2. Проверка режима шины (должно быть 5000M, а не 480M)
lsusb -t
```

---

## 3. Установка пакетов и правил udev на Raspberry Pi

Если пакеты еще не установлены на Raspberry Pi, выполните:

```bash
sudo apt update

# Установка драйвера RealSense, утилиты лазерскана и плагинов сжатия
sudo apt install -y \
  ros-jazzy-realsense2-camera \
  ros-jazzy-realsense2-description \
  ros-jazzy-depthimage-to-laserscan \
  ros-jazzy-image-transport-plugins

# Установка правил udev (чтобы устройство открывалось без прав root)
sudo apt install -y librealsense2-udev-rules || {
  sudo curl -sSL https://raw.githubusercontent.com/IntelRealSense/librealsense/master/config/99-realsense-libusb.rules -o /etc/udev/rules.d/99-realsense-libusb.rules
}
sudo udevadm control --reload-rules && sudo udevadm trigger
```

---

## 4. Способы запуска

### Способ 1: Через проектный лаунч `ijkbot_bringup` (Рекомендуемый)

Лаунч запускает и камеру в энергоэффективном режиме, и ноду формирования `/scan`:

```bash
source ~/IJKbot/install/setup.bash

# Запуск камеры и лазерскана
ros2 launch ijkbot_bringup realsense_laserscan.launch.py
```

*Или в составе полного робота (включая моторы):*
```bash
ros2 launch ijkbot_bringup robot.launch.py
```

---

### Способ 2: Прямой запуск драйвера камеры через CLI

Если требуется проверить работу исключительно камеры:

```bash
ros2 launch realsense2_camera rs_launch.py \
  camera_name:=camera \
  rgb_camera.color_profile:=640x480x15 \
  depth_module.depth_profile:=640x480x15 \
  enable_color:=true \
  enable_depth:=true \
  align_depth.enable:=true \
  pointcloud.enable:=false \
  enable_sync:=true
```

---

### Способ 3: Ручной запуск ноды `depthimage_to_laserscan`

Если драйвер камеры уже запущен отдельно, ноду лазерскана можно поднять командой:

```bash
ros2 run depthimage_to_laserscan depthimage_to_laserscan_node \
  --ros-args \
  -r image:=/camera/camera/depth/image_rect_raw \
  -r camera_info:=/camera/camera/depth/camera_info \
  -r scan:=/scan \
  -p range_min:=0.2 \
  -p range_max:=4.0 \
  -p scan_height:=20 \
  -p output_frame:=camera_link
```
*(Примечание: если топики камеры начинаются с одного слова `/camera/depth/...`, замените путь в ремаппинге `image` и `camera_info`)*.

---

## 5. Проверка работоспособности и топиков

После запуска проверьте топики в соседнем терминале:

### 1. Список топиков:
```bash
ros2 topic list | grep -E 'camera|scan'
```
Ожидаемые топики:
- `/camera/camera/color/image_raw` — цветное видео
- `/camera/camera/color/image_raw/compressed` — сжатый JPEG поток для ноутбука
- `/camera/camera/depth/image_rect_raw` — сырая карта глубины
- `/scan` — 2D лазерскан для Nav2

### 2. Проверка частоты публикации:
```bash
# Должно быть ~15 Гц
ros2 topic hz /scan

# Частота цветного потока (~15 Гц)
ros2 topic hz /camera/camera/color/image_raw
```

### 3. Просмотр данных лазерскана:
```bash
ros2 topic echo /scan --once
```
В массиве `ranges` должны отображаться расстояния до препятствий в метрах (значения от 0.2 до 4.0, либо `inf` для свободного пространства).

---

## 6. Устранение неполадок (Troubleshooting)

### Проблема 1: `WARNING: topic [/scan] does not appear to be published yet`
1. Проверьте реальные имена топиков камеры:
   ```bash
   ros2 topic list | grep depth
   ```
2. Если топик называется `/camera/depth/image_rect_raw` (с одним словом `camera`):
   В файле `ijkbot_bringup/launch/realsense_laserscan.launch.py` исправьте строки ремаппинга:
   ```python
   ('image', '/camera/depth/image_rect_raw'),
   ('camera_info', '/camera/depth/camera_info'),
   ```
3. Проверьте, что в топик глубины действительно идут сообщения:
   ```bash
   ros2 topic hz /camera/depth/image_rect_raw
   ```

---

### Проблема 2: Камера не определяется или определяется как USB 2.1 (`480M`)
- Переподключите кабель в другой **синий** порт USB 3.0.
- Переверните штекер Type-C в камере (в некоторых дешевых кабелях линии USB 3.0 разведены только с одной стороны).
- Проверьте кабель на ПК: убедитесь, что кабель поддерживает стандарт USB 3.0 (SuperSpeed 5 Gbps).

---

### Проблема 3: Высокая загрузка процессора и перегрев Pi 4B
- Проверьте, что облако точек отключено: `pointcloud.enable:=false`.
- Проверьте температуру процессора:
  ```bash
  vcgencmd measure_temp
  vcgencmd get_throttled
  ```
  *(Если температура выше 75°C или флаг throttled отличен от `0x0`, проверьте кулер и радиатор на процессоре Raspberry Pi)*.

