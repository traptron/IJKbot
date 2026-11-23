# Onboard platform decision and read-only Pi inventory

**Date:** 2026-11-16. **Author:** traptron (team decision recorded by assistant).

## Team decision

The team explicitly selected its available Jetson Nano DevKit as the planned onboard platform after questioning Pi 4B capacity. This supersedes the independent reviewers' Pi-first recommendation. No extra permission to reflect this decision in the concept is needed. The original immutable brief and completed reviews remain historical evidence, not reviews of the changed platform choice.

The team's expectation that everything will certainly run on Nano is not a verified property. The earlier model description identifies original Nano, not Orin Nano. Keep LLM, toy/sign detection, QR decoding and UI on the external laptop as the initial proposed distribution. Nano's target role is devices, odometry/TF, local motion protection, navigation and bounded depth-hazard processing. Moving additional tasks onboard requires a measured reason.

## Verified software constraints

* NVIDIA's Jetson Linux R32.7.6 supports original Nano, uses an Ubuntu 18.04-based sample filesystem, and is the final JetPack 4 / R32 release: [NVIDIA release documentation](https://developer.nvidia.com/embedded/linux-tegra-r3276).
* The archive distinguishes original Nano from the Orin family: [NVIDIA JetPack archive](https://developer.nvidia.com/embedded/jetpack-archive).
* ROS 2 Jazzy deb installation targets Ubuntu 24.04: [official ROS documentation source](https://raw.githubusercontent.com/ros2/ros2_documentation/jazzy/source/Installation/Ubuntu-Install-Debs.rst).

Inference: replacing the Pi is not an established drop-in deployment. The software route must be selected and demonstrated on the actual unit. These sources do not prove impossibility, measured superiority/inferiority, or adequate workload capacity. No reinstall, ROS downgrade, community OS image, container solution or cross-distribution integration has been selected or executed.

## Read-only Pi inspection

The user said Pi was available on the local network. Known addresses were unreachable; a bounded TCP/22 discovery of the current Wi-Fi `/24` found `10.16.115.154`. Existing SSH-key access as `otmorozki` succeeded. Read `/proc/device-tree/model`, `/etc/os-release`, selected `/proc/meminfo` fields, thermal temperature, CPU count and installed ROS directories.

| Observation | Result |
| --- | --- |
| Board | Raspberry Pi 4 Model B Rev 1.2 |
| Reported RAM | 3,874,892 KiB (approximately 4 GB board) |
| Available memory at observation | 3,480,820 KiB |
| Configured swap | 0 KiB |
| CPU cores | 4 |
| OS | Ubuntu 24.04.5 LTS |
| ROS directory | `/opt/ros/jazzy` |
| Reported temperature | 35.537 °C |
| Physical cooling | Not established by this inspection |

No workload was started, ROS command sent, motor moved, service restarted or installation/configuration changed. The temperature and available memory describe that instant, not capacity under the planned workload. SSH may write ordinary access records and the client accepted the host key for the new address.

## Next evidence and schedule consequence

**Later access update:** The team reports Jetson is not on the network and expects access during the week of 16–22 November, without a fixed day. No Jetson inspection has occurred. The earlier six-hour migration slot is therefore conditional on access; it is not a promise that deployment can be completed before 18 November. The concept now separates before-delivery evidence/prop preparation from board-dependent checks and proposes a schedule reassessment on 20 November if access or a software route is still missing. No new permission gate is required to record this constraint.

Identify the exact Jetson unit and its current software/access; establish required device and ROS operation with mock hardware before moving motor connections. Then measure the complete workload and end-to-end stopping response. Include mounting, regulated power, cooling, storage and USB device connections in migration time. The first six planned shared hours now include this migration feasibility work; they are not six additional hours. If it does not fit, explicitly revise later milestones and City allocation while protecting final full-run testing.

Preserve the Pi installation as a recoverable reference. Its known low-obstacle limitations still prevent calling it a safe competition fallback without further validation. No hardware was purchased or changed during this decision update.
