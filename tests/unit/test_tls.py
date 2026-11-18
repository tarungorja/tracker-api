import ssl

from pymongo import AsyncMongoClient

from app.core.tls import httpx_verify, requests_session


def test_default_verification_is_untouched():
    assert httpx_verify(False) is True


def test_system_ca_is_scoped_to_http_clients_not_global():
    context = httpx_verify(True)
    assert isinstance(context, ssl.SSLContext)
    requests_session(True)

    # Regression: a global truststore.inject_into_ssl() made PyMongo's TLS setup recurse forever.
    AsyncMongoClient("mongodb://localhost:27017/?tls=true", connect=False)
