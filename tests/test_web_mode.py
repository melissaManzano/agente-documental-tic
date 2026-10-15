"""Modo web (Vercel): sin sesión no hay consultas, la sincronización está cerrada y el login usa state."""
from types import SimpleNamespace as NS
from urllib.parse import urlparse, parse_qs
import pytest
from fastapi.testclient import TestClient
from app.core.config import Settings
from app.main import create_app
from app.services.catalog import VectorStoreCatalog

WEB = dict(web_mode=True, openai_api_key="sk-test", vector_store_id="vs_test",
           google_client_id="cliente.apps.googleusercontent.com", google_client_secret="secreto",
           oauth_redirect_uri="https://archivo.example/auth/callback", session_secret="s" * 32,
           allowed_emails="alumna@example.com")


@pytest.fixture
def client():
    # base_url https: la cookie de sesión se marca Secure (https_only=True).
    return TestClient(create_app(Settings(**WEB)), base_url="https://testserver")


def test_modo_web_falla_cerrado_si_falta_configuracion():
    with pytest.raises(RuntimeError, match="SESSION_SECRET"):
        create_app(Settings(**{**WEB, "session_secret": ""}))
    with pytest.raises(RuntimeError, match="ALLOWED_EMAILS"):
        create_app(Settings(**{**WEB, "allowed_emails": "", "allowed_domain": ""}))


def test_endpoints_protegidos_sin_sesion(client):
    assert client.post("/api/ask", json={"question": "¿RTO?"}).status_code == 401
    assert client.get("/api/documents").status_code == 401
    assert client.get("/api/me").json() == {"mode": "web", "user": None}


def test_health_no_revela_configuracion(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_sync_cerrado_en_modo_web(client):
    # Aunque la petición llegue como loopback, en modo web no se permite sincronizar.
    assert client.post("/api/sync").status_code == 403


def test_login_redirige_a_google_con_state(client):
    r = client.get("/auth/login", follow_redirects=False)
    assert r.status_code == 302
    url = urlparse(r.headers["location"])
    query = parse_qs(url.query)
    assert url.netloc == "accounts.google.com"
    assert query["scope"] == ["openid email"]
    assert query["redirect_uri"] == [WEB["oauth_redirect_uri"]]
    assert len(query["state"][0]) >= 32 and query["nonce"]


def test_callback_rechaza_state_falso(client):
    client.get("/auth/login", follow_redirects=False)
    r = client.get("/auth/callback?code=abc&state=falso", follow_redirects=False)
    assert r.headers["location"] == "/?auth=error"
    assert client.get("/api/me").json()["user"] is None


def test_lista_de_permitidos():
    from app.core.auth import WebAuth
    auth = WebAuth(Settings(**{**WEB, "allowed_emails": "A@example.com", "allowed_domain": "tec.mx"}))
    assert auth.is_allowed("a@example.com")
    assert auth.is_allowed("otro@tec.mx", "tec.mx")
    assert not auth.is_allowed("otro@tec.mx", "")  # el dominio se valida con el claim hd, no con el texto del correo
    assert not auth.is_allowed("intruso@gmail.com")


def test_catalogo_desde_attributes_del_vector_store():
    files = [NS(id="file-1", attributes={"name": "guia.pdf", "url": "https://drive.google.com/file/d/a/view"}),
             NS(id="file-2", attributes=None)]  # indexado antes de guardar attributes: se omite
    store_files = NS(list=lambda **kw: iter(files),
                     retrieve=lambda file_id, vector_store_id: next(f for f in files if f.id == file_id))
    catalog = VectorStoreCatalog(NS(vector_stores=NS(files=store_files)), "vs_test")
    assert [d["name"] for d in catalog.documents()] == ["guia.pdf"]
    assert catalog.lookup("file-1")["url"] == "https://drive.google.com/file/d/a/view"
    assert catalog.lookup("file-2") is None
    assert catalog.lookup("file-inexistente") is None
