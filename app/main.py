"""Archivo TIC IA.

Modo local (por defecto): prototipo de laboratorio; sincronización solo desde localhost.
Modo web (Vercel o APP_MODE=web): exige contraseña de acceso (ACCESS_PASSWORD) y sesión firmada;
la sincronización con Drive queda deshabilitada y se sigue haciendo en local.
"""
import logging
from pathlib import Path
from ipaddress import ip_address
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from app.core.config import Settings, settings
from app.models.documento import AskRequest, AskResponse, LoginRequest
from app.services.sync_service import SyncService
from app.services.agent_service import AgentService
from app.services.catalog import ManifestCatalog, VectorStoreCatalog

ROOT = Path(__file__).resolve().parents[1]
log = logging.getLogger("archivo_tic")


def create_app(cfg: Settings) -> FastAPI:
    app = FastAPI(title="Archivo TIC IA", version="1.1.0")
    auth = None
    if cfg.web_mode:
        missing = cfg.missing_web_settings()
        if missing:
            # Falla al arrancar (visible en los logs de Vercel) en lugar de quedar abierta.
            raise RuntimeError("Modo web sin configurar. Faltan variables: " + ", ".join(missing))
        from app.core.auth import WebAuth
        auth = WebAuth(cfg)
        app.add_middleware(SessionMiddleware, secret_key=cfg.session_secret, session_cookie="archivo_tic_session",
                           max_age=8 * 3600, same_site="lax", https_only=True)

    def require_user(request: Request):
        """Modo local: sin cuentas (uso en la propia computadora). Modo web: sesión obligatoria."""
        return auth.current_user(request) if auth else None

    def local_only(request: Request):
        """Defensa básica para el laboratorio; no equivale a autenticación pública."""
        if cfg.web_mode:
            # En Vercel la app corre detrás de un adaptador y la IP del cliente puede aparecer
            # como 127.0.0.1, así que la comprobación de loopback no es confiable allí.
            raise HTTPException(status_code=403, detail="La sincronización con Drive solo se ejecuta en el entorno local")
        host = request.client.host if request.client else ""
        try:
            if not ip_address(host).is_loopback: raise ValueError()
        except ValueError:
            raise HTTPException(status_code=403, detail="Sincronización disponible solo desde localhost")
        key = cfg.local_admin_key
        if key and request.headers.get("X-Admin-Key") != key:
            raise HTTPException(status_code=401, detail="Clave administrativa incorrecta")

    def catalog():
        if cfg.web_mode:
            return VectorStoreCatalog(AgentService().client, cfg.vector_store_id)
        return ManifestCatalog(SyncService.load_manifest())

    @app.get("/")
    def index():
        return FileResponse(ROOT / "index.html")

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon():
        # Algunos navegadores lo piden aunque index.html declare el SVG.
        return FileResponse(ROOT / "assets" / "img" / "favicon-32.png", media_type="image/png")

    @app.get("/api/health")
    def health():
        if cfg.web_mode: return {"status": "ok"}  # no revela detalles de configuración en Internet
        return {"status": "ok", "configured": bool(cfg.openai_api_key and cfg.drive_folder_id)}

    @app.get("/api/me")
    def me(request: Request):
        if not auth: return {"mode": "local", "user": None}
        try:
            return {"mode": "web", "user": auth.current_user(request)}
        except HTTPException:
            return {"mode": "web", "user": None}

    @app.post("/auth/login")
    def login(payload: LoginRequest, request: Request):
        # Solo JSON: un formulario de otro sitio no puede enviarlo sin pasar por CORS.
        if not auth: raise HTTPException(status_code=404)
        return {"success": True, "user": auth.login(request, payload.password)}

    @app.post("/auth/logout")
    def logout(request: Request):
        if auth: request.session.clear()
        return {"success": True}

    @app.get("/api/documents", dependencies=[Depends(require_user)])
    def documents():
        if cfg.web_mode:
            try:
                docs = catalog().documents()
            except Exception:
                log.exception("Fallo al listar el Vector Store")
                raise HTTPException(status_code=502, detail="No se pudo leer el índice documental")
            return {"documents": docs, "indexed": len(docs), "vector_store_configured": True}
        doc = SyncService.load_manifest()
        return {"documents": list(doc.get("documents", {}).values()),
                "indexed": len(doc.get("documents", {})),
                "vector_store_configured": bool(cfg.vector_store_id or doc.get("vector_store_id"))}

    @app.post("/api/ask", response_model=AskResponse, dependencies=[Depends(require_user)])
    def ask(payload: AskRequest):
        try:
            if not cfg.openai_api_key: raise ValueError("Falta OPENAI_API_KEY")
            agent = AgentService(catalog=catalog() if cfg.web_mode else None)
            return agent.ask(payload.question, payload.use_search)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception:
            log.exception("Fallo en /api/ask")  # aparece en la terminal local o en los logs de Vercel
            raise HTTPException(status_code=502, detail="Error al consultar OpenAI. Revisa el registro del servidor.")

    @app.post("/api/sync", dependencies=[Depends(local_only)])
    def sync():
        try:
            if not cfg.openai_api_key: raise ValueError("Falta OPENAI_API_KEY")
            return SyncService().sync()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            log.exception("Fallo en /api/sync")
            raise HTTPException(status_code=502, detail=f"Sincronización fallida: {exc}")

    # Al final: así las rutas declaradas arriba tienen prioridad sobre los archivos que Vercel sube al CDN.
    app.mount("/assets", StaticFiles(directory=ROOT / "assets"), name="assets")
    return app


app = create_app(settings)
