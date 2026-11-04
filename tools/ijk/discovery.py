"""Network discovery for Raspberry Pi (IJKbot).

Cascade:
1. Explicit --host flag or ROBOT_IP / PI_HOST env
2. Last cached IP (~/.cache/ijk/last_ip)
3. mDNS (ijkbot.local)
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
                subnets.append(parts[0])
    except (subprocess.TimeoutExpired, OSError):
        pass
    return subnets


def scan_subnet_for_ssh(subnet_cidr: str, user: str, timeout_sec: float = 1.5) -> Optional[str]:
    """Fast concurrent scan of /24 subnet for open port 22."""
    try:
        net = ipaddress.ip_network(subnet_cidr, strict=False)
        if net.num_addresses > 512:
            return None  # Don't scan huge networks
    except ValueError:
        return None

    candidate_ips = [str(ip) for ip in net.hosts()]

    def check_candidate(ip: str) -> Optional[str]:
        if is_port_open(ip, 22, timeout=0.3):
            if is_ssh_responsive(ip, user, timeout=1):
                return ip
        return None

    with ThreadPoolExecutor(max_workers=50) as executor:
        futures = {executor.submit(check_candidate, ip): ip for ip in candidate_ips}
        start = time.time()
        for fut in as_completed(futures):
            res = fut.result()
            if res:
                return res
            if time.time() - start > timeout_sec:
                break
    return None


def discover_robot(config: IjkConfig, explicit_host: Optional[str] = None, verbose: bool = True) -> Optional[str]:
    user = config.network.default_user

    # 1. Explicit argument / environment variable
    candidate = explicit_host or os.environ.get("ROBOT_IP") or os.environ.get("PI_HOST")
    if candidate:
        if verbose:
            print(f"[discovery] Проверка указанного хоста: {candidate}...")
        if is_ssh_responsive(candidate, user, timeout=2):
            save_last_ip(candidate)
            return candidate
        if verbose:
            print(f"[discovery] Предупреждение: указанный хост {candidate} не отвечает по SSH.")

    # 2. Last cached IP
    cached_ip = get_cached_ip()
    if cached_ip:
        if verbose:
            print(f"[discovery] Проверка сохранённого IP из кэша: {cached_ip}...")
        if is_ssh_responsive(cached_ip, user, timeout=1):
            return cached_ip

    # 3. mDNS hostname
    if config.network.mdns_hostname:
        if verbose:
            print(f"[discovery] Поиск по mDNS: {config.network.mdns_hostname}...")
        mdns_ip = resolve_mdns(config.network.mdns_hostname)
        if mdns_ip and is_ssh_responsive(mdns_ip, user, timeout=1):
            save_last_ip(mdns_ip)
            return mdns_ip

    # 4. Known hosts from config
    for host in config.network.known_hosts:
        if verbose:
            print(f"[discovery] Проверка известного IP: {host}...")
        if is_ssh_responsive(host, user, timeout=1):
            save_last_ip(host)
            return host

    # 5. Fast subnet scan
    if verbose:
        print("[discovery] Поиск робота сканированием локальной сети...")
    for subnet in get_local_subnets():
        found = scan_subnet_for_ssh(subnet, user, timeout_sec=config.network.subnet_scan_timeout_sec)
        if found:
            if verbose:
                print(f"[discovery] Робот успешно обнаружен по адресу: {found}")
            save_last_ip(found)
            return found

    return None

