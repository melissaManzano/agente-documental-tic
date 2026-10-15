"""Marca todos los documentos del manifiesto como modificados.

La siguiente sincronización (botón o POST /api/sync en localhost) volverá a subir cada
archivo con su nombre real y sus attributes, y eliminará la versión anterior del
Vector Store y de OpenAI Files. Útil tras actualizar el formato de indexación.

Uso:  python scripts/forzar_reindexacion.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.sync_service import SyncService  # noqa: E402

manifest = SyncService.load_manifest()
docs = manifest.get("documents", {})
for doc in docs.values():
    doc["modified_time"] = None
SyncService.save_manifest(manifest)
print(f"{len(docs)} documentos marcados para reindexar. Ahora pulsa 'Sincronizar desde Drive'.")
