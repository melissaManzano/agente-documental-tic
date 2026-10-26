"""Modo web (Vercel): sin contraseña no hay consultas y la sincronización está cerrada."""
from types import SimpleNamespace as NS
import pytest
from fastapi.testclient import TestClient
from app.core import auth as auth_module
from app.core.config import Settings
from app.main import create_app
from app.services.catalog import VectorStoreCatalog

WEB = dict(web_mode=True, openai_api_key="sk-test", vector_store_id="vs_test",
           access_password="clave-de-prueba-123", session_secret="s" * 32)


@pytest.fixture(autouse=True)
def sin_espera(monkeypatch):
    monkeypatch.setattr(auth_module, "FAILED_LOGIN_DELAY", 0)


def cliente(**cambios):
    # base_url https: la cookie de sesión se marca Secure (https_only=True).
    return TestClient(create_app(Settings(**{**WEB, **cambios})), base_url="https://testserver")


def test_modo_web_falla_cerrado_si_falta_configuracion():
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        create_app(Settings(**{**WEB, "openai_api_key": ""}))
    with pytest.raises(RuntimeError, match="VECTOR_STORE_ID"):
        create_app(Settings(**{**WEB, "vector_store_id": ""}))
    with pytest.raises(RuntimeError, match="mínimo 12"):
        create_app(Settings(**{**WEB, "access_password": "corta"}))
    with pytest.raises(RuntimeError, match="SESSION_SECRET"):
        create_app(Settings(**{**WEB, "session_secret": "corto"}))


def test_endpoints_protegidos_sin_sesion():
    c = cliente()
    assert c.post("/api/ask", json={"question": "¿RTO?"}).status_code == 401
    assert c.get("/api/documents").status_code == 401
    assert c.get("/api/me").json() == {"mode": "web", "auth": True, "user": None}


def test_sin_contrasena_el_sitio_web_es_publico(monkeypatch):
    # Sin ACCESS_PASSWORD tampoco se exige SESSION_SECRET.
    c = cliente(access_password="", session_secret="")
    assert c.get("/api/me").json() == {"mode": "web", "auth": False, "user": None}
    store_files = NS(list=lambda **kw: iter([NS(id="f1", attributes={"name": "guia.pdf", "url": None})]))
    monkeypatch.setattr("app.main.AgentService", lambda **kw: NS(client=NS(vector_stores=NS(files=store_files))))
    assert c.get("/api/documents").json()["indexed"] == 1  # sin 401
    assert c.post("/auth/login", json={"password": "x"}).status_code == 404
    # Lo que no cambia: la sincronización sigue cerrada y health no revela configuración.
    assert c.post("/api/sync").status_code == 403
    assert c.get("/api/health").json() == {"status": "ok"}


def test_access_password_se_ignora_sin_require_password(monkeypatch):
    # Caso de Vercel: ACCESS_PASSWORD sigue definida, pero sin REQUIRE_PASSWORD el sitio es público.
    import importlib
    from app.core import config
    monkeypatch.setenv("ACCESS_PASSWORD", "clave-de-prueba-123")
    monkeypatch.delenv("REQUIRE_PASSWORD", raising=False)
    assert importlib.reload(config).Settings().access_password == ""
    monkeypatch.setenv("REQUIRE_PASSWORD", "true")
    assert importlib.reload(config).Settings().access_password == "clave-de-prueba-123"
    monkeypatch.delenv("REQUIRE_PASSWORD")
    importlib.reload(config)


def test_health_no_revela_configuracion():
    assert cliente().get("/api/health").json() == {"status": "ok"}


def test_sync_cerrado_en_modo_web():
    # Aunque haya sesión y la petición llegue como loopback, en modo web no se sincroniza.
    c = cliente()
    c.post("/auth/login", json={"password": WEB["access_password"]})
    assert c.post("/api/sync").status_code == 403


def test_login_correcto_abre_sesion_y_logout_la_cierra():
    c = cliente()
    assert c.post("/auth/login", json={"password": "incorrecta"}).status_code == 401
    assert c.get("/api/me").json()["user"] is None
    assert c.post("/auth/login", json={"password": WEB["access_password"]}).status_code == 200
    assert c.get("/api/me").json()["user"] == {"name": "invitado"}
    c.post("/auth/logout")
    assert c.get("/api/me").json()["user"] is None


def test_cambiar_la_contrasena_invalida_sesiones_anteriores():
    c = cliente()
    c.post("/auth/login", json={"password": WEB["access_password"]})
    cookie = c.cookies.get("archivo_tic_session")
    nueva = cliente(access_password="otra-clave-distinta-456")
    nueva.cookies.set("archivo_tic_session", cookie)
    assert nueva.get("/api/me").json()["user"] is None


def test_login_solo_acepta_json():
    # Un formulario HTML de otro sitio no puede enviar JSON sin CORS.
    r = cliente().post("/auth/login", data={"password": WEB["access_password"]})
    assert r.status_code == 422


def test_catalogo_desde_attributes_del_vector_store():
    files = [NS(id="file-1", attributes={"name": "guia.pdf", "url": "https://drive.google.com/file/d/a/view",
                                         "summary": "Respaldos en RDS", "questions": "¿RTO?\n¿RPO?"}),
             NS(id="file-2", attributes=None)]  # indexado antes de guardar attributes: se omite
    store_files = NS(list=lambda **kw: iter(files),
                     retrieve=lambda file_id, vector_store_id: next(f for f in files if f.id == file_id))
    catalog = VectorStoreCatalog(NS(vector_stores=NS(files=store_files)), "vs_test")
    assert [d["name"] for d in catalog.documents()] == ["guia.pdf"]
    assert catalog.documents()[0]["questions"] == ["¿RTO?", "¿RPO?"]
    assert catalog.lookup("file-1")["url"] == "https://drive.google.com/file/d/a/view"
    assert catalog.lookup("file-2") is None
    assert catalog.lookup("file-inexistente") is None
