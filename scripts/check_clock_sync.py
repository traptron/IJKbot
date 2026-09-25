#!/usr/bin/env python3
"""
check_clock_sync.py — Автоматическая предстартовая проверка расхождения часов.

Хакатон «Эвакуация» (Кубок РТК Высшая Лига, Ижевск).
Регламент: |Δt| < 5.0 мс между бортовым компьютером (Raspberry Pi 4B)
и рабочей станцией (Ноутбук) для корректной работы TF-дерева, Nav2 и Vision.
"""

import argparse
from dataclasses import dataclass
import json
import os
import re
import subprocess
import sys
import time
from typing import Any, Dict, Optional, Tuple


@dataclass
class ChronyTrackingInfo:
    reference_id: str = 'UNKNOWN'
    stratum: Optional[int] = None
    last_offset_sec: Optional[float] = None
    rms_offset_sec: Optional[float] = None
    system_time_offset_sec: Optional[float] = None
    leap_status: str = 'UNKNOWN'
    is_synced: bool = False
    raw_text: str = ''


@dataclass
class ClockSyncResult:
    passed: bool
    status: str  # 'PASS', 'FAIL', 'ERROR'
    delta_ms: float
    threshold_ms: float
    laptop_offset_ms: Optional[float]
    robot_offset_ms: Optional[float]
    laptop_stratum: Optional[int]
    robot_stratum: Optional[int]
    connected_host: str
    message: str
    details: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            'passed': self.passed,
            'status': self.status,
            'delta_ms': round(self.delta_ms, 3),
            'threshold_ms': self.threshold_ms,
            'laptop_offset_ms': (
                round(self.laptop_offset_ms, 3)
                if self.laptop_offset_ms is not None else None
            ),
            'robot_offset_ms': (
                round(self.robot_offset_ms, 3)
                if self.robot_offset_ms is not None else None
            ),
            'laptop_stratum': self.laptop_stratum,
            'robot_stratum': self.robot_stratum,
            'connected_host': self.connected_host,
            'message': self.message,
            'details': self.details,
        }


def parse_chrony_tracking(output: str) -> ChronyTrackingInfo:
    """Парсинг вывода команды 'chronyc tracking'."""
    info = ChronyTrackingInfo(raw_text=output)
    if not output:
        return info

    ref_m = re.search(r'Reference ID\s*:\s*([^\n]+)', output)
    if ref_m:
        info.reference_id = ref_m.group(1).strip()

    strat_m = re.search(r'Stratum\s*:\s*(\d+)', output)
    if strat_m:
        info.stratum = int(strat_m.group(1))

    last_off_m = re.search(r'Last offset\s*:\s*([+-]?[\d.eE-]+)\s*seconds', output)
    if last_off_m:
        info.last_offset_sec = float(last_off_m.group(1))

    rms_off_m = re.search(r'RMS offset\s*:\s*([+-]?[\d.eE-]+)\s*seconds', output)
    if rms_off_m:
        info.rms_offset_sec = float(rms_off_m.group(1))

    sys_time_m = re.search(
        r'System time\s*:\s*([+-]?[\d.eE-]+)\s*seconds\s+(slow|fast)', output
    )
    if sys_time_m:
        val = float(sys_time_m.group(1))
        direction = sys_time_m.group(2)
        info.system_time_offset_sec = -val if direction == 'slow' else val

    leap_m = re.search(r'Leap status\s*:\s*([^\n]+)', output)
    if leap_m:
        info.leap_status = leap_m.group(1).strip()

    info.is_synced = (
        info.stratum is not None
        and 0 < info.stratum < 16
        and info.leap_status.lower() == 'normal'
    )
    return info


def query_local_chrony(timeout: float = 3.0) -> Tuple[bool, ChronyTrackingInfo, str]:
    """Получение статуса локального Chrony на ноутбуке."""
    try:
        res = subprocess.run(
            ['chronyc', 'tracking'],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if res.returncode == 0:
            return True, parse_chrony_tracking(res.stdout), res.stdout
        return (
            False,
            ChronyTrackingInfo(),
            f'chronyc tracking вернул код {res.returncode}: {res.stderr}',
        )
    except FileNotFoundError:
        return False, ChronyTrackingInfo(), 'chronyc не установлен в системе'
    except Exception as ex:
        return False, ChronyTrackingInfo(), f'Ошибка вызова chronyc tracking: {ex}'


def query_remote_chrony(
    host: str,
    user: str = 'otmorozki',
    timeout: float = 5.0,
) -> Tuple[bool, ChronyTrackingInfo, str]:
    """Получение статуса Chrony на Raspberry Pi через SSH."""
    cmd = [
        'ssh',
        '-o', 'BatchMode=yes',
        '-o', 'StrictHostKeyChecking=no',
        '-o', f'ConnectTimeout={int(max(1, timeout))}',
        f'{user}@{host}',
        'chronyc tracking',
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if res.returncode == 0:
            return True, parse_chrony_tracking(res.stdout), res.stdout
        return (
            False,
            ChronyTrackingInfo(),
            f'SSH вернул код {res.returncode}: {res.stderr.strip()}',
        )
    except subprocess.TimeoutExpired:
        return (
            False,
            ChronyTrackingInfo(),
            f'Таймаут подключения по SSH к {host} ({timeout} с)',
        )
    except Exception as ex:
        return False, ChronyTrackingInfo(), f'Ошибка соединения с {host}: {ex}'


def measure_direct_remote_time(
    host: str,
    user: str = 'otmorozki',
    timeout: float = 4.0,
) -> Tuple[bool, Optional[float], Optional[float], str]:
    """Измерение времени и RTT на Pi через одиночный SSH-запрос (алгоритм Кристиана)."""
    t0 = time.time()
    cmd = [
        'ssh',
        '-o', 'BatchMode=yes',
        '-o', 'StrictHostKeyChecking=no',
        '-o', f'ConnectTimeout={int(max(1, timeout))}',
        f'{user}@{host}',
        "python3 -c 'import time; print(time.time())'",
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        t1 = time.time()
        if res.returncode == 0 and res.stdout.strip():
            t_remote = float(res.stdout.strip())
            rtt = t1 - t0
            offset = t_remote - (t0 + t1) / 2.0
            return True, offset, rtt, ''
        return False, None, None, res.stderr.strip()
    except Exception as ex:
        return False, None, None, str(ex)


def check_clock_sync(
    host: str = '192.168.1.10',
    user: str = 'otmorozki',
    threshold_ms: float = 5.0,
    timeout: float = 4.0,
    mock: bool = False,
    allow_fallback: bool = True,
) -> ClockSyncResult:
    """Основная функция проверки синхронизации часов между ноутбуком и Raspberry Pi."""
    if mock:
        return ClockSyncResult(
            passed=True,
            status='PASS',
            delta_ms=0.85,
            threshold_ms=threshold_ms,
            laptop_offset_ms=-0.42,
            robot_offset_ms=-1.27,
            laptop_stratum=3,
            robot_stratum=3,
            connected_host='mock-hardware',
            message='[PASS] [MOCK] Синхронизация часов симулирована (Δt = 0.85 мс < 5.0 мс)',
            details={'mode': 'mock'},
        )

    candidate_hosts = [host]
    if allow_fallback:
        fallback_host = '172.22.35.154' if host != '172.22.35.154' else '192.168.1.10'
        if fallback_host not in candidate_hosts:
            candidate_hosts.append(fallback_host)

    # 1. Локальный Chrony
    loc_ok, loc_info, _ = query_local_chrony(timeout=2.0)
    laptop_offset = (
        loc_info.last_offset_sec if loc_info.last_offset_sec is not None else 0.0
    )

    # 2. Удаленный Chrony на Raspberry Pi
    remote_ok = False
    rem_info = ChronyTrackingInfo()
    rem_err = ''
    active_host = host

    for target_host in candidate_hosts:
        ok, info, err = query_remote_chrony(target_host, user=user, timeout=timeout)
        if ok:
            remote_ok = True
            rem_info = info
            active_host = target_host
            break
        rem_err = err

    if not remote_ok:
        return ClockSyncResult(
            passed=False,
            status='ERROR',
            delta_ms=float('inf'),
            threshold_ms=threshold_ms,
            laptop_offset_ms=laptop_offset * 1000.0 if loc_ok else None,
            robot_offset_ms=None,
            laptop_stratum=loc_info.stratum,
            robot_stratum=None,
            connected_host=active_host,
            message=f'Не удалось связаться с Raspberry Pi ({active_host}): {rem_err}',
            details={
                'local_chrony_ok': loc_ok,
                'remote_chrony_ok': False,
                'error': rem_err,
                'tried_hosts': candidate_hosts,
            },
        )

    if rem_info.last_offset_sec is not None:
        robot_offset_sec = rem_info.last_offset_sec
        delta_sec = abs(robot_offset_sec - laptop_offset)
    elif rem_info.system_time_offset_sec is not None:
        robot_offset_sec = rem_info.system_time_offset_sec
        delta_sec = abs(robot_offset_sec - laptop_offset)
    else:
        direct_ok, direct_offset, _, _ = measure_direct_remote_time(
            active_host, user, timeout
        )
        if direct_ok and direct_offset is not None:
            robot_offset_sec = direct_offset
            delta_sec = abs(direct_offset)
        else:
            robot_offset_sec = 0.0
            delta_sec = float('inf')

    delta_ms = delta_sec * 1000.0
    passed = delta_ms < threshold_ms

    status_str = 'PASS' if passed else 'FAIL'
    if passed:
        verdict = f'Часы синхронизированы (|Δt| = {delta_ms:.2f} мс < {threshold_ms:.1f} мс)'
    else:
        verdict = (
            f'Расхождение часов превышает допуск '
            f'(|Δt| = {delta_ms:.2f} мс >= {threshold_ms:.1f} мс!)'
        )

    msg = f'[{status_str}] {verdict} (Робот: {active_host}, Stratum: {rem_info.stratum})'

    details = {
        'active_host': active_host,
        'laptop_stratum': loc_info.stratum,
        'robot_stratum': rem_info.stratum,
        'laptop_offset_sec': laptop_offset,
        'robot_offset_sec': robot_offset_sec,
        'robot_leap_status': rem_info.leap_status,
        'robot_ref_id': rem_info.reference_id,
    }

    return ClockSyncResult(
        passed=passed,
        status=status_str,
        delta_ms=delta_ms,
        threshold_ms=threshold_ms,
        laptop_offset_ms=laptop_offset * 1000.0,
        robot_offset_ms=robot_offset_sec * 1000.0,
        laptop_stratum=loc_info.stratum,
        robot_stratum=rem_info.stratum,
        connected_host=active_host,
        message=msg,
        details=details,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description='IJKbot — Предстартовая проверка синхронизации часов Chrony'
    )
    parser.add_argument(
        '--host',
        type=str,
        default=os.environ.get('PI_HOST', os.environ.get('ROBOT_IP', '192.168.1.10')),
        help='IP-адрес Raspberry Pi (по умолчанию 192.168.1.10)',
    )
    parser.add_argument(
        '--user',
        type=str,
        default=os.environ.get('PI_USER', os.environ.get('ROBOT_USER', 'otmorozki')),
        help='SSH пользователь на роботе (по умолчанию otmorozki)',
    )
    parser.add_argument(
        '--threshold-ms',
        type=float,
        default=5.0,
        help='Максимально допустимое расхождение часов в мс (по умолчанию 5.0)',
    )
    parser.add_argument(
        '--timeout',
        type=float,
        default=4.0,
        help='Таймаут опроса в секундах (по умолчанию 4.0)',
    )
    parser.add_argument(
        '--json',
        action='store_true',
        help='Вывод результатов в формате JSON',
    )
    parser.add_argument(
        '--mock',
        action='store_true',
        help='Режим симуляции (для офлайн тестирования и CI)',
    )
    parser.add_argument(
        '--no-fallback',
        action='store_true',
        help='Запретить автопереключение на резервный IP при недоступности основного',
    )

    args = parser.parse_args()

    result = check_clock_sync(
        host=args.host,
        user=args.user,
        threshold_ms=args.threshold_ms,
        timeout=args.timeout,
        mock=args.mock,
        allow_fallback=not args.no_fallback,
    )

    if args.json:
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
    else:
        print('=' * 64)
        print('IJKbot — Проверка синхронизации часов (Хакатон «Эвакуация»)')
        print('=' * 64)
        print(f'Целевой хост робота: {result.connected_host} (user: {args.user})')
        if result.laptop_offset_ms is not None:
            print(
                f'Ноутбук: Stratum {result.laptop_stratum} | '
                f'Смещение: {result.laptop_offset_ms:+.3f} мс'
            )
        else:
            print('Ноутбук: статус недоступен')
        if result.robot_offset_ms is not None:
            print(
                f'Робот:   Stratum {result.robot_stratum} | '
                f'Смещение: {result.robot_offset_ms:+.3f} мс'
            )
        else:
            print('Робот:   недоступен')
        print(
            f'Расхождение |Δt|: {result.delta_ms:.3f} мс  '
            f'[Порог регламента: {result.threshold_ms:.1f} мс]'
        )
        print('-' * 64)
        print(f'Вердикт: {result.message}')
        print('=' * 64)

    return 0 if result.passed else 1


if __name__ == '__main__':
    sys.exit(main())
