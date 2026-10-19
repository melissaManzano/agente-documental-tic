"""SummaryService con un cliente falso: sin OpenAI ni claves."""
import json
from types import SimpleNamespace as NS
from app.services.summary_service import SummaryService


def cliente(output_text=None, error=None):
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        if error: raise error
        return NS(output_text=output_text)
    return NS(responses=NS(create=create)), calls


def test_pdf_se_envia_como_archivo_y_se_recorta_la_guia():
    texto = json.dumps({"summary": "Guía de respaldos. " * 30, "questions": ["¿A?", " ", "¿B?", "¿C?", "¿D?"]})
    client, calls = cliente(texto)
    guide = SummaryService(client, "modelo").summarize(b"%PDF-1.4", "guia.pdf", "application/pdf")
    document = calls[0]["input"][0]["content"][1]
    assert document["type"] == "input_file" and document["file_data"].startswith("data:application/pdf;base64,")
    assert calls[0]["text"]["format"]["type"] == "json_schema"
    assert len(guide["summary"]) <= 300
    assert guide["questions"] == ["¿A?", "¿B?", "¿C?"]  # sin vacías y máximo 3


def test_texto_plano_se_envia_como_texto():
    client, calls = cliente(json.dumps({"summary": "Inventario", "questions": ["¿Cuántos servidores?"]}))
    SummaryService(client, "modelo").summarize("6 servidores".encode(), "inventario.txt", "text/plain")
    document = calls[0]["input"][0]["content"][1]
    assert document == {"type": "input_text", "text": "DOCUMENTO:\n6 servidores"}


def test_si_falla_devuelve_guia_vacia_sin_romper_la_sincronizacion():
    client, _ = cliente(error=RuntimeError("sin red"))
    assert SummaryService(client, "modelo").summarize(b"x", "a.txt", "text/plain") == {"summary": "", "questions": []}
