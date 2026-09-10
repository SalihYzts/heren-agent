"""LAN access: self-signed TLS (the phone's mic needs a secure context) + reachable URLs."""
import ssl
from pathlib import Path

from cryptography import x509

from heren_core.config import Settings
from heren_core.netaccess import access_urls, ensure_self_signed, lan_addresses


def test_lan_addresses_are_private_ipv4_only(monkeypatch):
    monkeypatch.setattr("heren_core.netaccess._all_ipv4", lambda: ["127.0.0.1", "192.168.1.150", "10.0.0.7", "8.8.8.8", "172.17.0.1"])
    assert lan_addresses() == ["192.168.1.150", "10.0.0.7", "172.17.0.1"]


def test_access_urls_use_scheme_port_and_every_lan_address(monkeypatch):
    monkeypatch.setattr("heren_core.netaccess._all_ipv4", lambda: ["127.0.0.1", "192.168.1.150"])
    monkeypatch.setattr("heren_core.netaccess._hostname", lambda: "pussinboots")
    s = Settings(host="0.0.0.0", port=8700, tls=True)
    urls = access_urls(s)
    assert urls == ["https://192.168.1.150:8700", "https://pussinboots.local:8700"]
    assert access_urls(Settings(host="127.0.0.1", port=8700)) == []   # bound to loopback: not reachable from LAN


def test_ensure_self_signed_creates_cert_with_lan_sans_and_reuses_it(tmp_path, monkeypatch):
    monkeypatch.setattr("heren_core.netaccess._all_ipv4", lambda: ["127.0.0.1", "192.168.1.150"])
    monkeypatch.setattr("heren_core.netaccess._hostname", lambda: "pussinboots")
    cert, key = ensure_self_signed(tmp_path / "tls")
    assert cert.exists() and key.exists()
    assert (key.stat().st_mode & 0o777) == 0o600
    c = x509.load_pem_x509_certificate(cert.read_bytes())
    san = c.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert "192.168.1.150" in [str(ip) for ip in san.get_values_for_type(x509.IPAddress)]
    names = san.get_values_for_type(x509.DNSName)
    assert "pussinboots.local" in names and "localhost" in names
    # loads into an ssl context (what uvicorn will do)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(str(cert), str(key))
    # second call: same files, nothing regenerated
    m1 = cert.stat().st_mtime_ns
    assert ensure_self_signed(tmp_path / "tls") == (cert, key)
    assert cert.stat().st_mtime_ns == m1


def test_settings_tls_defaults_off_and_paths_default_under_data():
    s = Settings()
    assert s.tls is False
    assert Path(s.tls_dir) == Path("data/tls")
