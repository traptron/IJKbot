# Supporting source checks

Checked by the primary agent on 2026-11-15, independently of the Goldfish reviewers. These are documentation checks, not robot tests. They may support synthesis after the independent reviews; they are not additional reviewer findings.

## Jetson Nano migration

NVIDIA lists the original Jetson Nano in the Jetson Linux R32.7.6 platform support list. That release uses an Ubuntu 18.04-based sample filesystem and is the final JetPack 4 / Linux R32 release. The JetPack archive distinguishes the original Nano from Orin Nano; the names must not be interchanged.

Sources:

* [NVIDIA Jetson Linux R32.7.6](https://developer.nvidia.com/embedded/linux-tegra-r3276)
* [NVIDIA JetPack archive](https://developer.nvidia.com/embedded/jetpack-archive)

The ROS 2 Jazzy installation documentation provides Ubuntu deb packages for Noble 24.04. The official rendered page denied automated access, so its source in the ROS project's Jazzy branch was read instead.

Source: [ROS 2 Jazzy installation documentation source](https://raw.githubusercontent.com/ros2/ros2_documentation/jazzy/source/Installation/Ubuntu-Install-Debs.rst).

Inference: an original Nano is not a demonstrated drop-in replacement for the project's Ubuntu 24.04 / ROS 2 Jazzy / GPU workload. A migration would require an explicit compatibility and deployment proof. This does not establish impossibility, inadequate measured performance, or the configuration of the university's particular board.

## Camera depth in Nav2

The Nav2 Jazzy voxel-layer documentation describes a 3D environmental representation projected into 2D planning space and supports LaserScan or PointCloud2 observations. It documents height filtering, marking, clearing, and observation-source configuration.

Source: [Nav2 Jazzy voxel-layer parameters](https://ros-navigation.github.io/mkdocs.nav2.org/jazzy/configuration_and_development/configuration_guide/core_servers/costmap_2d/costmap_plugins/voxel/).

Inference: the review should consider existing Nav2 sensor-ingestion mechanisms before introducing a custom planner or complete navigation rewrite. Merely enabling a voxel layer does not prove floor/bridge discrimination, 4 cm detection, useful latency, sufficient camera coverage, or safe handling of stale data. Local processing must respect the project's restriction on raw point clouds over Wi-Fi.
