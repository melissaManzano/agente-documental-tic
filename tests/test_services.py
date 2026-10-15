"""Pruebas de SyncService y AgentService con dobles locales: sin Drive, sin OpenAI, sin claves."""
from types import SimpleNamespace as NS
import pytest
from app.services import sync_service
from app.services.sync_service import SyncService
from app.services.agent_service import AgentService

PDF = "application/pdf"
GDOC = "application/vnd.google-apps.document"


@pytest.fixture(autouse=True)
def manifest_temporal(tmp_path, monkeypatch):
    monkeypatch.setattr(sync_service, "MANIFEST", tmp_path / "manifest.json")


class FakeDrive:
    def __init__(self, files):
        self.files = files

    def list_files(self, folder_id):
        return self.files

    def get_bytes(self, item):
        if item["mimeType"] == GDOC:
            return b"texto", item["name"] + ".txt", "text/plain"
        return b"%PDF", item["name"], item["mimeType"]


class FakeVectorFiles:
    def __init__(self):
        self.uploaded, self.deleted, self.count = [], [], 0

    def upload_and_poll(self, vector_store_id, file):
        self.count += 1
        self.uploaded.append(file[0])
        return NS(id=f"file-{self.count}", status="completed")

    def delete(self, vector_store_id, file_id):
        self.deleted.append(file_id)


def fake_openai():
    files = FakeVectorFiles()
    return NS(vector_stores=NS(create=lambda name: NS(id="vs_test"), files=files)), files


def item(id_, name, mime, modified="2026-01-01T00:00:00Z"):
    return {"id": id_, "name": name, "mimeType": mime, "modifiedTime": modified}


def test_sync_altas_cambios_bajas_y_omitidos():
    client, files = fake_openai()
    drive = FakeDrive([item("a", "guia.pdf", PDF), item("b", "Glosario", GDOC),
                       item("c", "notas.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")])
    first = SyncService(client=client, drive=drive).sync()["stats"]
    assert (first["added"], first["unchanged"]) == (2, 0)
    assert first["skipped"] == [{"file": "notas.docx", "mime_type": drive.files[2]["mimeType"]}]
    # Nombre real de Drive y extensión garantizada para los Google Docs exportados.
    assert files.uploaded == ["guia.pdf", "Glosario.txt"]

    drive.files = [item("a", "guia.pdf", PDF, modified="2026-02-01T00:00:00Z")]
    second = SyncService(client=client, drive=drive).sync()["stats"]
    assert (second["updated"], second["removed"], second["added"]) == (1, 1, 0)
    # Se borran la versión anterior del PDF y el Google Doc eliminado.
    assert sorted(files.deleted) == ["file-1", "file-2"]
    manifest = SyncService.load_manifest()
    assert list(manifest["documents"]) == ["a"]
    assert manifest["documents"]["a"]["openai_file_id"] == "file-3"


def test_sync_sin_cambios_no_vuelve_a_subir():
    client, files = fake_openai()
    drive = FakeDrive([item("a", "guia.pdf", PDF)])
    SyncService(client=client, drive=drive).sync()
    stats = SyncService(client=client, drive=drive).sync()["stats"]
    assert stats["unchanged"] == 1 and files.count == 1


def respuesta(*annotations):
    content = NS(annotations=list(annotations))
    return NS(output=[NS(content=[content])], output_text="respuesta")


def test_fuentes_solo_de_citas_verificadas():
    SyncService.save_manifest({"vector_store_id": "vs_test", "documents": {
        "a": {"name": "guia.pdf", "url": "https://drive.google.com/file/d/a/view", "openai_file_id": "file-1"}}})
    resp = respuesta(NS(type="file_citation", file_id="file-1"),
                     NS(type="file_citation", file_id="file-1"),      # duplicada
                     NS(type="file_citation", file_id="file-ajeno"),  # no está en el manifiesto
                     NS(type="url_citation", file_id=""))
    calls = []
    client = NS(responses=NS(create=lambda **kw: calls.append(kw) or resp))
    result = AgentService(client=client).ask("¿RTO?", use_search=True)
    assert result["sources"] == [{"name": "guia.pdf", "url": "https://drive.google.com/file/d/a/view"}]
    assert calls[0]["tools"][0]["vector_store_ids"] == ["vs_test"]


def test_sin_file_search_no_envia_herramientas():
    calls = []
    client = NS(responses=NS(create=lambda **kw: calls.append(kw) or respuesta()))
    result = AgentService(client=client).ask("¿RTO?", use_search=False)
    assert "tools" not in calls[0] and result["sources"] == []


def test_file_search_requiere_sincronizar_primero():
    client = NS(responses=NS(create=lambda **kw: respuesta()))
    with pytest.raises(ValueError):
        AgentService(client=client).ask("¿RTO?", use_search=True)
