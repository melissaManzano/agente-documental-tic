# Despliegue en Vercel — Archivo TIC IA

Reto autónomo de la práctica 2.3. Documenta cómo se adaptó el prototipo local a Vercel,
qué errores aparecieron y cómo se corrigieron. **El prototipo local no cambia de comportamiento.**

## 1. Dos modos de ejecución

| | Modo local (`python app.py`) | Modo web (Vercel) |
|---|---|---|
| Se activa | Por defecto | Automáticamente si existe `VERCEL`, o con `APP_MODE=web` |
| Usuarios | Sin cuentas (equipo propio) | Google Sign-In (`openid email`) + lista `ALLOWED_EMAILS` / `ALLOWED_DOMAIN` |
| Sesión | — | Cookie firmada (`SESSION_SECRET`), `Secure`, `SameSite=Lax`, 8 h |
| Lectura de Drive | OAuth Desktop (`drive.readonly`), `token.json` | **No accede a Drive** |
| `POST /api/sync` | Solo loopback (+ `X-Admin-Key` opcional) | **403 siempre** |
| `GET /api/documents`, `POST /api/ask` | Abiertos en localhost | **Requieren sesión** (401) |
| Catálogo de documentos y citas | `data/manifest.json` | `attributes` de cada archivo del Vector Store |
| `GET /api/health` | Incluye `configured` | Solo `{"status":"ok"}` |

**Decisión de arquitectura.** La sincronización Drive → OpenAI se mantiene en el entorno local de
administración y Vercel solo consulta el Vector Store ya indexado. Así el servidor público nunca
guarda tokens de Drive ni usa el alcance restringido `drive.readonly` (que exigiría verificación de
Google y auditoría de seguridad), y el inicio de sesión web solo usa alcances no sensibles.

## 2. Variables de entorno en Vercel

*Project → Settings → Environment Variables* (Production y Preview). Tras cambiarlas hay que **volver a desplegar**.

| Variable | Tipo | Valor |
|---|---|---|
| `OPENAI_API_KEY` | Secret | Clave **distinta** a la local, con presupuesto propio |
| `OPENAI_MODEL` | Config | `gpt-4.1-mini` |
| `VECTOR_STORE_ID` | Config | ID `vs_...` de `data/manifest.json` |
| `GOOGLE_CLIENT_ID` | Config | Cliente OAuth **Web application** (no el Desktop) |
| `GOOGLE_CLIENT_SECRET` | Secret | Del mismo cliente Web |
| `OAUTH_REDIRECT_URI` | Config | `https://<dominio>.vercel.app/auth/callback` (idéntica a la registrada en Google) |
| `SESSION_SECRET` | Secret | ≥ 32 caracteres aleatorios: `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `ALLOWED_EMAILS` | Config | Correos separados por coma |
| `ALLOWED_DOMAIN` | Config | Opcional: dominio de Google Workspace (se valida con el claim `hd`) |

No se configuran: `GOOGLE_DRIVE_FOLDER_ID`, `LOCAL_ADMIN_KEY`, `PORT`, `credentials.json`, `token.json`.
Si falta alguna obligatoria, la app **no arranca** y el log muestra los nombres que faltan (nunca valores).

## 3. Pasos

1. **Reindexar en local** para que cada archivo del Vector Store tenga `attributes`:
   `python scripts/forzar_reindexacion.py` y después *Sincronizar desde Drive*.
2. **Google Cloud → Google Auth Platform → Clientes → Crear cliente → Aplicación web.**
   URI de redirección: `https://<dominio>.vercel.app/auth/callback`.
3. **Vercel → Add New → Project → Import** `melissaManzano/agente-documental-tic`.
   Framework preset: FastAPI (detectado por `pyproject.toml`). Configurar las variables del punto 2.
4. Desplegar, abrir *Deployments → Build Logs / Runtime Logs* y registrar errores en la bitácora.
5. *Settings → Deployment Protection*: proteger los despliegues de Preview.

## 4. Problemas detectados antes del despliegue

| # | Problema | Causa | Corrección |
|---|---|---|---|
| 1 | Punto de entrada ambiguo | `app.py` (raíz) y el paquete `app/` comparten el nombre `app` | `index.py` como punto de entrada + `.vercelignore` excluye `app.py` (ver bitácora) |
| 2 | OAuth Desktop imposible | `run_local_server()` abre un navegador en el servidor | Modo web con Google Sign-In (`/auth/login`, `/auth/callback`), `state` + `nonce`, verificación del `id_token` |
| 3 | `token.json` y `manifest.json` no persisten | Sistema de archivos de solo lectura; `/tmp` es efímero | Vercel no usa Drive; el catálogo sale de los `attributes` del Vector Store |
| 4 | `local_only` no es confiable | Tras el adaptador de Vercel la IP del cliente puede verse como loopback | En modo web `/api/sync` responde 403 sin mirar la IP |
| 5 | `/api/ask` y `/api/documents` públicos | Sin autenticación | Dependencia `require_user` (401 sin sesión) |
| 6 | Errores 502 sin rastro | Las excepciones no se registraban | `log.exception(...)` visible en *Runtime Logs* |
| 7 | Archivos huérfanos en OpenAI Files | Al actualizar solo se quitaban del Vector Store | `SyncService.remove_file` borra también de OpenAI Files |

## 5. Bitácora del despliegue

| Fecha | Despliegue | Error observado (log) | Causa | Corrección / commit |
|---|---|---|---|---|
| 2026-10-15 | `dpl_HFey4xHR…` (production, `main`) | `500 FUNCTION_INVOCATION_FAILED`. Runtime log: `could not import "app.py"` → `ModuleNotFoundError: No module named 'app.main'; 'app' is not a package` | Vercel elige `app.py` (primer candidato) y lo importa como módulo `app`; dentro, `from app.main import app` busca en ese mismo archivo y no en el paquete `app/`. El `entrypoint` de `pyproject.toml` no se respetó. Cargar `app/main.py` con el nombre `app` falla igual | Nuevo `index.py` (`from app.main import app`), `entrypoint = "index:app"` y `.vercelignore` con `/app.py`. Verificado en local simulando el cargador de Vercel (`spec_from_file_location`): `GET /` 200, `/api/ask` 401, `/api/sync` 403. El arranque local con `python app.py` no cambia |

## 6. Limitaciones conocidas

- Todos los usuarios autorizados ven el mismo índice: no hay permisos por documento.
- Sin límite de peticiones por usuario; el tope es el presupuesto del proyecto de OpenAI
  (opcional: regla de *Rate Limit* del Vercel WAF sobre `/api/ask`).
- La sincronización automática desde Vercel (Cron + cuenta de servicio) queda como trabajo futuro.
