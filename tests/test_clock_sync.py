#!/usr/bin/env python3
"""Unit-тесты для модуля scripts/check_clock_sync.py."""

import json
import os
import subprocess
import sys
from unittest.mock import patch

import pytest

# Ensure repo root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.check_clock_sync import (  # noqa: E402
    check_clock_sync,
    ChronyTrackingInfo,
    parse_chrony_tracking,
)


CHRONY_SAMPLE_VALID = """
Reference ID    : B97DBE7A (ntp-nts-2.ps5.canonical.com)
Stratum         : 3
Ref time (UTC)  : Fri Sep 25 09:18:16 2026
System time     : 0.000000025 seconds slow of NTP time
Last offset     : -0.000577163 seconds
RMS offset      : 0.000763302 seconds
Frequency       : 7.543 ppm fast
Residual freq   : +0.019 ppm
Skew            : 4.873 ppm
Root delay      : 0.059053056 seconds
Root dispersion : 0.031146001 seconds
Update interval : 64.8 seconds
Leap status     : Normal
"""

CHRONY_SAMPLE_UNSYNCED = """
Reference ID    : 00000000 ()
Stratum         : 0
Ref time (UTC)  : Thu Jan 01 00:00:00 1970
System time     : 0.000000000 seconds slow of NTP time
Last offset     : +0.000000000 seconds
RMS offset      : +0.000000000 seconds
Frequency       : 0.000 ppm
Residual freq   : 0.000 ppm
Skew            : 0.000 ppm
Root delay      : 0.000000000 seconds
Root dispersion : 0.000000000 seconds
Update interval : 0.0 seconds
Leap status     : Not synchronised
"""


def test_parse_chrony_tracking_valid():
    """Тест парсинга валидного вывода chronyc tracking."""
    info = parse_chrony_tracking(CHRONY_SAMPLE_VALID)
    assert info.is_synced is True
    assert info.stratum == 3
    assert info.reference_id == 'B97DBE7A (ntp-nts-2.ps5.canonical.com)'
    assert info.last_offset_sec == pytest.approx(-0.000577163)
    assert info.rms_offset_sec == pytest.approx(0.000763302)
    assert info.system_time_offset_sec == pytest.approx(-0.000000025)
    assert info.leap_status == 'Normal'


def test_parse_chrony_tracking_unsynced():
    """Тест парсинга несинхронизированного состояния Chrony."""
    info = parse_chrony_tracking(CHRONY_SAMPLE_UNSYNCED)
    assert info.is_synced is False
    assert info.stratum == 0
    assert info.leap_status == 'Not synchronised'


def test_parse_chrony_tracking_empty():
    """Тест парсинга пустого вывода."""
    info = parse_chrony_tracking('')
    assert info.is_synced is False
    assert info.stratum is None
    assert info.last_offset_sec is None


def test_mock_clock_sync():
    """Тест mock-режима проверки синхронизации."""
    res = check_clock_sync(mock=True, threshold_ms=5.0)
    assert res.passed is True
    assert res.status == 'PASS'
    assert res.delta_ms < 5.0
    assert res.laptop_stratum == 3
    assert res.robot_stratum == 3

    d = res.to_dict()
    assert d['passed'] is True
    assert 'delta_ms' in d
    assert d['status'] == 'PASS'


def test_clock_sync_threshold_pass():
    """Тест прохождения порога расхождения часов (< 5.0 мс)."""
    mock_loc = ChronyTrackingInfo(
        stratum=3, last_offset_sec=0.001, is_synced=True, leap_status='Normal'
    )
    mock_rem = ChronyTrackingInfo(
        stratum=3, last_offset_sec=0.003, is_synced=True, leap_status='Normal'
    )

    with patch('scripts.check_clock_sync.query_local_chrony', return_value=(True, mock_loc, '')):
        with patch(
            'scripts.check_clock_sync.query_remote_chrony', return_value=(True, mock_rem, '')
        ):
            res = check_clock_sync(host='test-host', threshold_ms=5.0)
            assert res.passed is True
            assert res.status == 'PASS'
            # |0.003 - 0.001| = 0.002 s = 2.0 ms < 5.0 ms
            assert res.delta_ms == pytest.approx(2.0)


def test_clock_sync_threshold_fail():
    """Тест непрохождения порога расхождения часов (>= 5.0 мс)."""
    mock_loc = ChronyTrackingInfo(
        stratum=3, last_offset_sec=0.001, is_synced=True, leap_status='Normal'
    )
    mock_rem = ChronyTrackingInfo(
        stratum=3, last_offset_sec=0.010, is_synced=True, leap_status='Normal'
    )

    with patch('scripts.check_clock_sync.query_local_chrony', return_value=(True, mock_loc, '')):
        with patch(
            'scripts.check_clock_sync.query_remote_chrony', return_value=(True, mock_rem, '')
        ):
            res = check_clock_sync(host='test-host', threshold_ms=5.0)
            assert res.passed is False
            assert res.status == 'FAIL'
            # |0.010 - 0.001| = 0.009 s = 9.0 ms >= 5.0 ms
            assert res.delta_ms == pytest.approx(9.0)


def test_clock_sync_unreachable():
    """Тест обработки недоступности удаленного узла."""
    mock_loc = ChronyTrackingInfo(
        stratum=3, last_offset_sec=0.001, is_synced=True, leap_status='Normal'
    )

    with patch('scripts.check_clock_sync.query_local_chrony', return_value=(True, mock_loc, '')):
        with patch(
            'scripts.check_clock_sync.query_remote_chrony',
            return_value=(False, ChronyTrackingInfo(), 'SSH timeout'),
        ):
            res = check_clock_sync(host='invalid-host', allow_fallback=False)
            assert res.passed is False
            assert res.status == 'ERROR'


def test_cli_mock_invocation():
    """Тест вызова скрипта через CLI с флагами --mock и --json."""
    script_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), 'scripts', 'check_clock_sync.py'
    )
    res = subprocess.run([sys.executable, script_path, '--mock'], capture_output=True, text=True)
    assert res.returncode == 0
    assert '[PASS]' in res.stdout

    res_json = subprocess.run(
        [sys.executable, script_path, '--mock', '--json'], capture_output=True, text=True
    )
    assert res_json.returncode == 0
    data = json.loads(res_json.stdout)
    assert data['passed'] is True
    assert data['status'] == 'PASS'
