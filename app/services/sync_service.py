"""Sincronización unidireccional: Drive -> OpenAI Vector Store.
Nota: eliminar archivos de un vector store puede tener consistencia eventual.
"""
import json
import os
import threading
from pathlib import Path
from openai import OpenAI
from app.core.config import settings
from app.services.drive_service import DriveService
from app.services.summary_service import SummaryService

MANIFEST = Path(__file__).resolve().parents[2] / "data" / "manifest.json"
_LOCK = threading.Lock()
SUPPORTED = {"application/pdf", "text/plain", "application/vnd.google-apps.document"}

class SyncService:
    def __init__(self, client=None, drive=None, summarizer=None):
        self.client = client or OpenAI(api_key=settings.openai_api_key)
        self.drive = drive or DriveService()
        self.summarizer = summarizer or SummaryService(self.client, settings.openai_model)

    @staticmethod
    def load_manifest() -> dict:
        if not MANIFEST.exists(): return {"vector_store_id": "", "documents": {}}
        return json.loads(MANIFEST.read_text(encoding="utf-8"))

    @staticmethod
    def save_manifest(data: dict):
        MANIFEST.parent.mkdir(parents=True, exist_ok=True)
        tmp = MANIFEST.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, MANIFEST)

    def get_store(self, manifest):
        vector_id = settings.vector_store_id or manifest.get("vector_store_id")
        if not vector_id:
            vector_id = self.client.vector_stores.create(name="Archivo TIC IA - Documentos").id
        manifest["vector_store_id"] = vector_id
        return vector_id

    def remove_file(self, store: str, file_id: str):
        """Quita el archivo del Vector Store y también de OpenAI Files (si no, sigue ocupando almacenamiento)."""
        self.client.vector_stores.files.delete(vector_store_id=store, file_id=file_id)
        try:
            self.client.files.delete(file_id)
        except Exception:
            pass  # ya borrado o inexistente: no impide la sincronización

    def sync(self):
        if not _LOCK.acquire(blocking=False):
            raise RuntimeError("Ya existe una sincronización en curso")
        try:
            manifest = self.load_manifest()
            docs = manifest.setdefault("documents", {})
            store = self.get_store(manifest)
            self.save_manifest(manifest)
            source = self.drive.list_files(settings.drive_folder_id)
            eligible = {x["id"]: x for x in source if x["mimeType"] in SUPPORTED}
            stats = {"added": 0, "updated": 0, "removed": 0, "unchanged": 0, "errors": [],
                     "skipped": [{"file": x["name"], "mime_type": x["mimeType"]}
                                 for x in source if x["mimeType"] not in SUPPORTED]}
            for drive_id, item in eligible.items():
                previous = docs.get(drive_id)
                if previous and previous.get("modified_time") == item.get("modifiedTime"):
                    stats["unchanged"] += 1
                    continue
                try:
                    raw, filename, target_mime = self.drive.get_bytes(item)
                    if not raw: raise ValueError("El archivo está vacío")
                    # Se sube con el nombre real de Drive para que el modelo y las citas lo reconozcan;
                    # OpenAI deduce el formato por la extensión.
                    suffix = ".pdf" if target_mime == "application/pdf" else ".txt"
                    if not filename.lower().endswith(suffix): filename += suffix
                    url = item.get("webViewLink") or (
                        "https://docs.google.com/document/d/" + drive_id + "/edit" if item["mimeType"] == "application/vnd.google-apps.document" else "https://drive.google.com/file/d/" + drive_id + "/view")
                    # Los attributes viajan con el archivo en el Vector Store: el modo web (Vercel)
                    # los usa como catálogo porque allí no existe data/manifest.json.
                    guide = self.summarizer.summarize(raw, filename, target_mime)
                    # Los attributes admiten textos de hasta 512 caracteres: las preguntas van en líneas.
                    attributes = {"drive_id": drive_id, "name": item["name"][:512], "url": url[:512],
                                  "mime_type": item["mimeType"], "summary": guide["summary"][:512],
                                  "questions": "\n".join(guide["questions"])[:512]}
                    upload = self.client.vector_stores.files.upload_and_poll(
                        vector_store_id=store, file=(filename, raw), attributes=attributes)
                    if upload.status != "completed": raise RuntimeError("Indexación no completada: " + upload.status)
                    # Solo se elimina la versión antigua después de indexar exitosamente la nueva.
                    if previous:
                        self.remove_file(store, previous["openai_file_id"])
                    docs[drive_id] = {
                        "name": item["name"], "modified_time": item.get("modifiedTime"),
                        "mime_type": item["mimeType"], "openai_file_id": upload.id, "url": url,
                        "summary": guide["summary"], "questions": guide["questions"]
                    }
                    self.save_manifest(manifest)
                    stats["updated" if previous else "added"] += 1
                except Exception as exc:
                    stats["errors"].append({"file": item["name"], "error": str(exc)})
            for drive_id in set(docs) - set(eligible):
                try:
                    self.remove_file(store, docs[drive_id]["openai_file_id"])
                    del docs[drive_id]
                    self.save_manifest(manifest)
                    stats["removed"] += 1
                except Exception as exc:
                    stats["errors"].append({"file": drive_id, "error": str(exc)})
            return {"vector_store_id": store, "stats": stats, "documents": list(docs.values())}
        finally:
            _LOCK.release()
