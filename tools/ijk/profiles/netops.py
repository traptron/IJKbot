"""Network & pre-start ops: forced time sync, Wi-Fi profile switching, rosbag export."""

from pathlib import Path
from typing import Any, Dict, List, Optional
import shlex
import subprocess
import time

from tools.ijk.config import IjkConfig
from tools.ijk.runner import Runner

REPO_DIR = Path(__file__).resolve().parents[2]
BAGS_DIR = REPO_DIR / "bags"


# ---------------------------------------------------------------- timesync
def measure_offset_ms(runner: Runner) -> Optional[float]:
    """Rough laptop->Pi clock offset (ms) compensated by half the SSH round trip."""
    t0 = time.time()
    res = runner.run_remote_ssh("date +%s.%N", timeout=4)
    t1 = time.time()
    if res.returncode != 0:
        return None
    try:
        remote = float(res.stdout.strip())
    except ValueError:
        return None
    return (remote - (t0 + t1) / 2.0) * 1000.0


def run_ops_timesync(runner: Runner, config: IjkConfig, force: bool = False, threshold_ms: float = 5.0) -> int:
    print("\n=== Предстартовая синхронизация времени (ноутбук -> Pi) ===")
    if not runner.robot_ip or runner.local:
        print("[timesync] Робот не подключен — нечего синхронизировать.")
        return 1

    offset = measure_offset_ms(runner)
    if offset is None:
        print("[timesync] [FAIL] Не удалось прочитать время с Pi по SSH.")
        return 1
    print(f"[timesync] Текущее расхождение: {offset:+.1f} мс (порог {threshold_ms} мс)")

    if abs(offset) > threshold_ms or force:
        print("[timesync] Принудительная установка времени на Pi (требуется sudo без пароля)...")
        stamp = f"{time.time():.3f}"
        cmd = f"sudo -n date -s @{stamp} >/dev/null && (sudo -n chronyc makestep >/dev/null 2>&1 || true)"
        res = runner.run_remote_ssh(cmd, timeout=6)
        if res.returncode != 0:
            print(f"[timesync] [FAIL] Ошибка: {res.stderr.strip() or 'sudo требует пароль'}")
            print("  Подсказка: разрешите на Pi `date` и `chronyc` в sudoers (NOPASSWD).")
            return 1
        time.sleep(0.5)
        offset = measure_offset_ms(runner)
        if offset is None:
            return 1
        print(f"[timesync] Расхождение после коррекции: {offset:+.1f} мс")

    # SSH-based measurement has ~RTT/2 uncertainty, so treat it as an estimate.
    ok = abs(offset) <= max(threshold_ms, 20.0)
    print(f"[timesync] {'[OK] Готов к старту' if ok else '[WARN] Расхождение велико, проверьте chrony (./ijk ops chrony)'}")
    return 0 if ok else 1


# -------------------------------------------------------------------- wifi
def _wifi_profiles(config: IjkConfig) -> Dict[str, Dict[str, Any]]:
    return dict(config.raw.get("wifi", {}).get("profiles", {}) or {})


def run_ops_wifi(runner: Runner, config: IjkConfig, profile: Optional[str] = None) -> int:
    print("\n=== Wi-Fi профили Raspberry Pi ===")
    if not runner.robot_ip or runner.local:
        print("[wifi] Робот не подключен по сети.")
        return 1

    profiles = _wifi_profiles(config)
    if profile in (None, "list"):
        print("Профили (config/ijk.yaml + ijk.local.yaml, секция wifi.profiles):")
        for name, p in profiles.items():
            print(f"  • {name:10s} SSID={p.get('ssid')}  IP={p.get('address', 'DHCP')}")
        cur = runner.run_remote_ssh("nmcli -t -f ACTIVE,SSID dev wifi 2>/dev/null | grep '^yes' || iwgetid -r", timeout=5)
        print(f"Текущая сеть Pi: {cur.stdout.strip() or 'неизвестно'}")
        print("Использование: ./ijk ops wifi <профиль> | scan")
        return 0

    if profile == "scan":
        res = runner.run_remote_ssh("nmcli -f SSID,SIGNAL,FREQ dev wifi list 2>/dev/null || sudo -n iwlist wlan0 scan | grep ESSID", timeout=15)
        print(res.stdout or res.stderr)
        return res.returncode

    p = profiles.get(profile)
    if not p:
        print(f"[wifi] Профиль '{profile}' не найден. Доступны: {', '.join(profiles) or '—'}")
        return 1
    password = p.get("password")
    if not password:
        print(f"[wifi] Для профиля '{profile}' не задан пароль. Добавьте его в config/ijk.local.yaml (не коммитится).")
        return 1

    ssid = str(p["ssid"])
    addr = p.get("address")
    print(f"[wifi] ВНИМАНИЕ: после переключения Pi уйдёт в сеть '{ssid}' и связь по текущему IP пропадёт.")
    if input("Продолжить? [y/N]: ").strip().lower() not in ("y", "д"):
        return 1

    addr_part = (f" ipv4.method manual ipv4.addresses {shlex.quote(str(addr))}" if addr else " ipv4.method auto")
    # Run detached so that the SSH drop does not abort the switch; NM keeps old profile as fallback.
    script = (
        f"sudo -n nmcli connection delete ijk-{profile} >/dev/null 2>&1; "
        f"sudo -n nmcli connection add type wifi ifname wlan0 con-name ijk-{profile} ssid {shlex.quote(ssid)} "
        f"wifi-sec.key-mgmt wpa-psk wifi-sec.psk {shlex.quote(str(password))}{addr_part} "
        f"&& sudo -n nmcli connection up ijk-{profile}"
    )
    res = runner.run_remote_ssh(f"nohup bash -c {shlex.quote('sleep 1; ' + script)} >/tmp/ijk_wifi.log 2>&1 &", timeout=5)
    if res.returncode != 0:
        print(f"[wifi] [FAIL] {res.stderr.strip()}")
        return 1
    print(f"[wifi] Переключение запущено. Подключите ноутбук к '{ssid}' и выполните ./ijk discover")
    if addr:
        print(f"       Ожидаемый IP робота: {str(addr).split('/')[0]}")
    return 0


# -------------------------------------------------------------- bag export
def _latest_bag() -> Optional[Path]:
    if not BAGS_DIR.is_dir():
        return None
    bags = [d for d in BAGS_DIR.iterdir() if d.is_dir() and (d / "metadata.yaml").exists()]
    return max(bags, key=lambda d: d.stat().st_mtime) if bags else None


def run_ops_bag_export(runner: Runner, bag: Optional[str] = None) -> int:
    print("\n=== Экспорт rosbag: траектория и скорости ===")
    bag_path = Path(bag) if bag else _latest_bag()
    if bag_path and not bag_path.is_absolute() and not bag_path.exists():
        bag_path = BAGS_DIR / bag_path
    if not bag_path or not bag_path.exists():
        print(f"[bag] Записи не найдены в {BAGS_DIR}. Запишите заезд флагом --record.")
        return 1
    worker = REPO_DIR / "tools" / "ijk" / "profiles" / "bag_export_worker.py"
    p = runner.run_local_process(["python3", str(worker), str(bag_path)])
    return p.wait()

