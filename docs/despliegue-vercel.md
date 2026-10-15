# Despliegue en Vercel — Archivo TIC IA

Reto autónomo de la práctica 2.3. Documenta cómo se adaptó el prototipo local a Vercel,
qué errores aparecieron y cómo se corrigieron. **El prototipo local no cambia de comportamiento.**

## 1. Dos modos de ejecución

| | Modo local (`python app.py`) | Modo web (Vercel) |
|---|---|---|
| Se activa | Por defecto | Automáticamente si existe `VERCEL`, o con `APP_MODE=web` |
| Acceso | Sin cuentas (equipo propio) | Contraseña compartida `ACCESS_PASSWORD` (`POST /auth/login`, solo JSON) |
| Sesión | — | Cookie firmada (`SESSION_SECRET`), `Secure`, `SameSite=Lax`, 8 h; se invalida si cambia la contraseña |
| Lectura de Drive | OAuth Desktop (`drive.readonly`), `token.json` | **No accede a Drive** |
| `POST /api/sync` | Solo loopback (+ `X-Admin-Key` opcional) | **403 siempre** |
| `GET /api/documents`, `POST /api/ask` | Abiertos en localhost | **Requieren sesión** (401) |
| Catálogo de documentos y citas | `data/manifest.json` | `attributes` de cada archivo del Vector Store |
| `GET /api/health` | Incluye `configured` | Solo `{"status":"ok"}` |

**Decisión de arquitectura.** La sincronización Drive → OpenAI se mantiene en el entorno local de
administración y Vercel solo consulta el Vector Store ya indexado. Así el servidor público nunca
guarda tokens de Drive ni usa el alcance restringido `drive.readonly` (que exigiría verificación de
Google y auditoría de seguridad).

**Acceso con contraseña.** Se evaluó Google Sign-In (OpenID Connect con `state`, `nonce` y lista de
correos), pero exige crear un cliente OAuth *Web* y configurar unas 8 variables. Para el alcance del
reto se eligió una contraseña compartida: 4 variables y ningún cambio en Google Cloud. Protege los
créditos de OpenAI y el índice, aunque no identifica a cada persona (ver limitaciones).

## 2. Variables de entorno en Vercel

*Project → Settings → Environment Variables* (Production y Preview). Tras cambiarlas hay que **volver a desplegar**.

| Variable | Tipo | Valor |
|---|---|---|
| Variable | Tipo | Valor |
|---|---|---|
| `OPENAI_API_KEY` | Secret | Clave **distinta** a la local, con presupuesto propio |
| `VECTOR_STORE_ID` | Config | ID `vs_...` de `data/manifest.json` |
| `ACCESS_PASSWORD` | Secret | ≥ 12 caracteres; se comparte solo con quien debe consultar |
| `SESSION_SECRET` | Secret | ≥ 32 caracteres aleatorios: `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `OPENAI_MODEL` | Config | Opcional; por defecto `gpt-4.1-mini` |

No se configuran: `GOOGLE_DRIVE_FOLDER_ID`, `LOCAL_ADMIN_KEY`, `PORT`, `credentials.json`, `token.json`.
Si falta alguna obligatoria, la app **no arranca** y el log muestra los nombres que faltan (nunca valores).

## 3. Pasos

1. **Reindexar en local** para que cada archivo del Vector Store tenga `attributes`:
   `python scripts/forzar_reindexacion.py` y después *Sincronizar desde Drive*.
2. **Vercel → Add New → Project → Import** `melissaManzano/agente-documental-tic`.
   Framework preset: FastAPI. Configurar las variables del punto 2.
3. Desplegar, abrir *Deployments → Build Logs / Runtime Logs* y registrar errores en la bitácora.
4. *Settings → Deployment Protection*: proteger los despliegues de Preview.

## 4. Problemas detectados antes del despliegue

| # | Problema | Causa | Corrección |
|---|---|---|---|
| 1 | Punto de entrada ambiguo | `app.py` (raíz) y el paquete `app/` comparten el nombre `app` | `index.py` como punto de entrada + `.vercelignore` excluye `app.py` (ver bitácora) |
| 2 | OAuth Desktop imposible | `run_local_server()` abre un navegador en el servidor | Vercel no accede a Drive; el acceso web es con contraseña (`ACCESS_PASSWORD`) y sesión firmada |
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

- Una sola contraseña compartida: no identifica a cada persona ni permite revocar a alguien en
  particular (se cambia `ACCESS_PASSWORD` y se vuelve a desplegar; las sesiones previas caducan).
  Trabajo futuro: Google Sign-In con lista de correos.
- Cada intento fallido espera 1 s, pero no hay bloqueo por IP; usar una contraseña larga
  (opcional: regla de *Rate Limit* del Vercel WAF sobre `/auth/login` y `/api/ask`).
- Todos los usuarios ven el mismo índice: no hay permisos por documento.
- El tope de gasto es el presupuesto del proyecto de OpenAI.
- La sincronización automática desde Vercel (Cron + cuenta de servicio) queda como trabajo futuro.
