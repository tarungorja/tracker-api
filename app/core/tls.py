"""Optional OS certificate-store trust for outbound HTTPS (corporate networks that intercept TLS).

This is applied per HTTP client, never globally: `truststore.inject_into_ssl()` replaces
`ssl.SSLContext` process-wide and makes PyMongo's TLS setup recurse infinitely.
"""

import ssl

import requests
from requests.adapters import HTTPAdapter


def _system_context() -> ssl.SSLContext:
    import truststore

    return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


def httpx_verify(use_system_ca: bool) -> ssl.SSLContext | bool:
    """Value for httpx's `verify=` argument."""
    return _system_context() if use_system_ca else True


class _SystemCaAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        kwargs["ssl_context"] = _system_context()
        super().init_poolmanager(*args, **kwargs)


def requests_session(use_system_ca: bool) -> requests.Session:
    session = requests.Session()
    if use_system_ca:
        session.mount("https://", _SystemCaAdapter())
    return session
