"""Catálogo de documentos indexados: de dónde salen la lista y los datos de cada cita.

- ManifestCatalog: modo local, lee data/manifest.json (escrito por SyncService).
- VectorStoreCatalog: modo web, lee los attributes de cada archivo del Vector Store,
  porque en Vercel no existe un disco persistente para el manifiesto.
"""


class ManifestCatalog:
    def __init__(self, manifest: dict):
        self.docs = manifest.get("documents", {})
        self.by_file = {d["openai_file_id"]: d for d in self.docs.values()}

    def documents(self) -> list[dict]:
        return list(self.docs.values())

    def lookup(self, openai_file_id: str) -> dict | None:
        return self.by_file.get(openai_file_id)


class VectorStoreCatalog:
    def __init__(self, client, vector_store_id: str):
        self.client, self.store = client, vector_store_id

    @staticmethod
    def _as_document(vs_file) -> dict | None:
        attrs = vs_file.attributes or {}
        if not attrs.get("name"): return None  # archivo indexado antes de guardar attributes
        questions = [q for q in str(attrs.get("questions") or "").split("\n") if q.strip()]
        return {"name": attrs["name"], "url": attrs.get("url"), "mime_type": attrs.get("mime_type"),
                "summary": attrs.get("summary") or "", "questions": questions}

    def documents(self) -> list[dict]:
        docs = (self._as_document(f) for f in
                self.client.vector_stores.files.list(vector_store_id=self.store, filter="completed", limit=100))
        return sorted((d for d in docs if d), key=lambda d: d["name"])

    def lookup(self, openai_file_id: str) -> dict | None:
        try:
            vs_file = self.client.vector_stores.files.retrieve(openai_file_id, vector_store_id=self.store)
        except Exception:
            return None
        return self._as_document(vs_file)
