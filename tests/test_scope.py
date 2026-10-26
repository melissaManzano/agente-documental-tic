"""Filtro de alcance: preguntas ajenas a los documentos no llegan al agente (sin OpenAI ni claves)."""
import json
from types import SimpleNamespace as NS
import pytest
from app.services import sync_service
from app.services.agent_service import AgentService
from app.services.scope_service import ScopeGuard
from app.services.sync_service import SyncService

DOCS = {"a": {"name": "guia.pdf", "url": "https://drive.google.com/file/d/a/view", "openai_file_id": "file-1",
              "summary": "Respaldos en AWS RDS"}}


@pytest.fixture(autouse=True)
def manifest_temporal(tmp_path, monkeypatch):
    monkeypatch.setattr(sync_service, "MANIFEST", tmp_path / "manifest.json")
    SyncService.save_manifest({"vector_store_id": "vs_test", "documents": DOCS})


def cliente(*salidas):
    """Cliente falso: cada llamada a responses.create devuelve la siguiente salida."""
    calls, pendientes = [], list(salidas)

    def create(**kwargs):
        calls.append(kwargs)
        salida = pendientes.pop(0)
        if isinstance(salida, Exception): raise salida
        return NS(output_text=salida, output=[])
    return NS(responses=NS(create=create)), calls


@pytest.mark.parametrize("use_search", [True, False])
def test_pregunta_ajena_recibe_mensaje_fijo_sin_consultar_al_agente(use_search):
    client, calls = cliente(json.dumps({"relacionada": False}))
    result = AgentService(client=client).ask("Tengo un dolor estomacal", use_search=use_search)
    assert result["out_of_scope"] is True and result["sources"] == []
    assert "Solo puedo responder preguntas relacionadas con los documentos" in result["answer"]
    assert "guia.pdf" in result["answer"]          # indica qué documentos sí hay
    assert len(calls) == 1                          # solo el filtro; el agente no se llamó


def test_pregunta_sobre_los_documentos_llega_al_agente():
    client, calls = cliente(json.dumps({"relacionada": True}), "El RTO es de 45 minutos.")
    result = AgentService(client=client).ask("¿Cuál es el RTO?", use_search=True)
    assert result["out_of_scope"] is False and result["answer"] == "El RTO es de 45 minutos."
    assert len(calls) == 2


def test_el_filtro_conoce_el_catalogo_y_usa_salida_estructurada():
    client, calls = cliente(json.dumps({"relacionada": True}))
    ScopeGuard(client, "modelo").is_relevant("¿RTO?", [{"name": "guia.pdf", "summary": "Respaldos en AWS RDS"}])
    assert "guia.pdf: Respaldos en AWS RDS" in calls[0]["instructions"]
    assert calls[0]["text"]["format"]["type"] == "json_schema"


def test_si_el_filtro_falla_deja_pasar_la_pregunta():
    client, _ = cliente(RuntimeError("sin red"))
    assert ScopeGuard(client, "modelo").is_relevant("¿RTO?", [{"name": "guia.pdf"}]) is True
