"""Export /odom and /cmd_vel from a rosbag2 to CSV (+ PNG plot if matplotlib exists).

Runs inside the ROS 2 environment (pixi), invoked by `./ijk ops bag-export`.
"""

import csv
import math
import sys
from pathlib import Path

try:
    import rosbag2_py
    from rclpy.serialization import deserialize_message
    from rosidl_runtime_py.utilities import get_message
except ImportError:
    print("[bag] rosbag2_py недоступен: запустите через ./ijk (pixi окружение).")
    sys.exit(1)


def main() -> int:
    bag = Path(sys.argv[1])
    reader = rosbag2_py.SequentialReader()
    reader.open(rosbag2_py.StorageOptions(uri=str(bag), storage_id=""),
                rosbag2_py.ConverterOptions("cdr", "cdr"))
    types = {t.name: t.type for t in reader.get_all_topics_and_types()}
    wanted = {"/odom", "/cmd_vel"}
    reader.set_filter(rosbag2_py.StorageFilter(topics=[t for t in wanted if t in types]))

    odom, cmd = [], []
    while reader.has_next():
        topic, data, stamp = reader.read_next()
        msg = deserialize_message(data, get_message(types[topic]))
        t = stamp * 1e-9
        if topic == "/odom":
            p, q, tw = msg.pose.pose.position, msg.pose.pose.orientation, msg.twist.twist
            yaw = math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))
            odom.append((t, p.x, p.y, yaw, tw.linear.x, tw.angular.z))
        else:
            cmd.append((t, msg.linear.x, msg.angular.z))

    if not odom:
        print("[bag] В записи нет /odom.")
        return 1
    t0 = odom[0][0]
    out_csv = bag / "odom.csv"
    with open(out_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t", "x", "y", "yaw", "v", "w"])
        w.writerows([(r[0] - t0, *r[1:]) for r in odom])
    dist = sum(math.hypot(b[1] - a[1], b[2] - a[2]) for a, b in zip(odom, odom[1:]))
    print(f"[bag] {bag.name}: {len(odom)} odom, {len(cmd)} cmd_vel, длительность {odom[-1][0] - t0:.1f} с, путь {dist:.2f} м")
    print(f"[bag] CSV: {out_csv}")

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("[bag] matplotlib не установлен — PNG пропущен.")
        return 0
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12, 5))
    a1.plot([r[1] for r in odom], [r[2] for r in odom])
    a1.set_aspect("equal"); a1.set_title("Траектория (odom)"); a1.set_xlabel("x, м"); a1.set_ylabel("y, м"); a1.grid()
    a2.plot([r[0] - t0 for r in odom], [r[4] for r in odom], label="v факт")
    if cmd:
        a2.plot([r[0] - t0 for r in cmd], [r[1] for r in cmd], "--", label="v команда")
    a2.set_title("Линейная скорость"); a2.set_xlabel("t, с"); a2.legend(); a2.grid()
    out_png = bag / "summary.png"
    fig.tight_layout(); fig.savefig(out_png, dpi=110)
    print(f"[bag] PNG: {out_png}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

