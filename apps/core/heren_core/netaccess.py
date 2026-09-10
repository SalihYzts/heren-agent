"""LAN access for phones/tablets.

Browsers only expose the microphone in a *secure context* (https or localhost), so reaching
Heren from a phone needs TLS. We mint a self-signed certificate once (SANs = every LAN IPv4 +
<hostname>.local + localhost) and reuse it; the user accepts it once per device.
"""
from __future__ import annotations

import datetime as dt
import ipaddress
import os
import socket
from pathlib import Path

from heren_core.config import Settings


def _all_ipv4() -> list[str]:
    """Every IPv4 assigned to this host (no external calls)."""
    out: list[str] = []
    try:
        for fam, _, _, _, sockaddr in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            out.append(str(sockaddr[0]))
    except OSError:
        pass
    # getaddrinfo on the hostname often returns only 127.0.1.1; walk interfaces via /proc-free trick
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))          # no packet is sent; picks the default-route interface
        out.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        import psutil  # optional
        for addrs in psutil.net_if_addrs().values():
            out.extend(a.address for a in addrs if a.family == socket.AF_INET)
    except Exception:
        pass
    seen: list[str] = []
    for ip in out:
        if ip not in seen:
            seen.append(ip)
    return seen


def _hostname() -> str:
    return socket.gethostname().split(".")[0].lower()


def lan_addresses() -> list[str]:
    """Private (RFC1918) IPv4s of this host — what a phone on the same Wi-Fi can reach."""
    res = []
    for ip in _all_ipv4():
        try:
            a = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if a.is_private and not a.is_loopback and not a.is_link_local:
            res.append(ip)
    return res


def access_urls(settings: Settings) -> list[str]:
    """URLs to show the user for phone/tablet access. Empty if bound to loopback only."""
    if settings.host in ("127.0.0.1", "localhost", "::1"):
        return []
    scheme = "https" if settings.tls else "http"
    urls = [f"{scheme}://{ip}:{settings.port}" for ip in lan_addresses()]
    urls.append(f"{scheme}://{_hostname()}.local:{settings.port}")
    return urls


def ensure_self_signed(tls_dir: Path, days: int = 3650) -> tuple[Path, Path]:
    """Create data/tls/{cert,key}.pem once; return their paths."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    tls_dir.mkdir(parents=True, exist_ok=True)
    cert_p, key_p = tls_dir / "cert.pem", tls_dir / "key.pem"
    if cert_p.exists() and key_p.exists():
        return cert_p, key_p

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Heren Agent")])
    sans: list[x509.GeneralName] = [x509.DNSName("localhost"), x509.DNSName(f"{_hostname()}.local"),
                                    x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
    for ip in lan_addresses():
        sans.append(x509.IPAddress(ipaddress.ip_address(ip)))
    now = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder()
            .subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(minutes=5)).not_valid_after(now + dt.timedelta(days=days))
            .add_extension(x509.SubjectAlternativeName(sans), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .sign(key, hashes.SHA256()))
    key_p.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                        serialization.NoEncryption()))
    os.chmod(key_p, 0o600)
    cert_p.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return cert_p, key_p
