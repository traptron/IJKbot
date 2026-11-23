"""Network discovery for Raspberry Pi (IJKbot).

Cascade:
1. Explicit --host flag or ROBOT_IP / PI_HOST env
2. Last cached IP (~/.cache/ijk/last_ip)
3. mDNS (ijkbot.local and tokmachka.local)
4. Known hosts list from config/ijk.yaml
5. Fast subnet port 22 scan + SSH banner validation
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional
import ipaddress
import os
import socket
import subprocess
import time

from tools.ijk.config import IjkConfig, get_cached_ip, save_last_ip


def is_port_open(ip: str, port: int = 22, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False


def is_ssh_responsive(ip: str, user: str, timeout: int = 2) -> bool:
    if not is_port_open(ip, 22, timeout=0.6):
        return False
    try:
        # Quick non-interactive check with BatchMode=yes
        cmd = [
            "ssh",
            "-p", "22",
            "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=no",
            "-o", f"ConnectTimeout={timeout}",
            f"{user}@{ip}",
            "hostname",
        ]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout + 1, text=True)
        if proc.returncode == 0:
            return True
    except (subprocess.TimeoutExpired, OSError):
        pass
    return False


def resolve_mdns(hostname: str) -> Optional[str]:
    try:
        addr = socket.gethostbyname(hostname)
        if addr:
            return addr
    except socket.gaierror:
        pass
    return None


def get_local_subnets() -> List[str]:
    """Find local IPv4 subnets from ip route."""
    subnets = []
    try:
        proc = subprocess.run(["ip", "-4", "route", "show"], stdout=subprocess.PIPE, text=True, timeout=1.5)
        for line in proc.stdout.splitlines():
            parts = line.split()
            if parts and "/" in parts[0] and not parts[0].startswith("127."):
                interface=parts[parts.index("dev")+1] if "dev" in parts else ""
                if interface.startswith(("docker", "br-", "veth", "tun", "tap", "wg", "happ-")):continue
                subnets.append(parts[0])
    except (subprocess.TimeoutExpired, OSError):
        pass
    return subnets


def scan_subnet_for_ssh(subnet_cidr: str, user: str, timeout_sec: float = 1.5, progress=None) -> Optional[str]:
    """Probe the entire bounded subnet, including candidates that finish late.

    timeout_sec controls the per-address probe budget, not an early exit that
    discards successful SSH checks still running in the executor.
    """
    try:
        net = ipaddress.ip_network(subnet_cidr, strict=False)
        if net.num_addresses > 512:
            if progress:progress(f'[discovery] Пропуск слишком большой подсети: {subnet_cidr}')
            return None
    except ValueError:
        return None
    candidates=[str(ip) for ip in net.hosts()]
    probe_timeout=min(1.,max(.3,timeout_sec/2))
    def check(ip):
        if not is_port_open(ip,22,timeout=probe_timeout):return None
        if progress:progress(f'[discovery] {ip}: порт SSH открыт; проверяем вход {user}')
        if is_ssh_responsive(ip,user,timeout=2):return ip
        if progress:progress(f'[discovery] {ip}: вход по SSH не подтверждён')
        return None
    found=None
    with ThreadPoolExecutor(max_workers=64) as executor:
        futures=[executor.submit(check,ip) for ip in candidates]
        for done,future in enumerate(as_completed(futures),1):
            result=future.result()
            if result:
                found=result
                for pending in futures:pending.cancel()
                break
            if progress and (done%32==0 or done==len(candidates)):
                progress(f'[discovery] {subnet_cidr}: проверено {done}/{len(candidates)} адресов')
    return found


def discover_robot(config: IjkConfig, explicit_host: Optional[str] = None, verbose: bool = True, progress=None) -> Optional[str]:
    def report(message):
        if verbose: print(message)
        if progress: progress(message)

    user = config.network.default_user
    def check(address, timeout):
        reachable=is_ssh_responsive(address,user,timeout=timeout)
        report(f'[discovery] {address}: '+('вход по SSH подтверждён' if reachable else 'SSH недоступен или вход не подтверждён'))
        return reachable

    # 1. Explicit argument / environment variable
    candidate = explicit_host or os.environ.get("ROBOT_IP") or os.environ.get("PI_HOST")
    if candidate:
        report(f"[discovery] Проверка указанного хоста: {candidate}...")
        if check(candidate,2):
            save_last_ip(candidate)
            return candidate
        report(f"[discovery] Предупреждение: указанный хост {candidate} не отвечает по SSH.")

    # 2. Last cached IP
    cached_ip = get_cached_ip()
    if cached_ip:
        report(f"[discovery] Проверка сохранённого IP из кэша: {cached_ip}...")
        if check(cached_ip,2):
            return cached_ip

    # 3. mDNS names: preserve the configured primary and try aliases as fallbacks.
    mdns_names=dict.fromkeys([config.network.mdns_hostname, *config.network.mdns_aliases])
    for hostname in filter(None, mdns_names):
        report(f"[discovery] Поиск по mDNS: {hostname}...")
        mdns_ip = resolve_mdns(hostname)
        if not mdns_ip:report(f"[discovery] mDNS: имя {hostname} не найдено")
        if mdns_ip and check(mdns_ip,2):
            save_last_ip(mdns_ip)
            return mdns_ip

    # 4. Known hosts from config
    for host in config.network.known_hosts:
        report(f"[discovery] Проверка известного IP: {host}...")
        if check(host,2):
            save_last_ip(host)
            return host

    # 5. Fast subnet scan
    report("[discovery] Поиск робота сканированием локальной сети...")
    for subnet in get_local_subnets():
        report(f"[discovery] Сканируем подсеть: {subnet}")
        found = scan_subnet_for_ssh(subnet, user, timeout_sec=config.network.subnet_scan_timeout_sec, progress=report)
        if found:
            report(f"[discovery] Робот успешно обнаружен по адресу: {found}")
            save_last_ip(found)
            return found

    return None

