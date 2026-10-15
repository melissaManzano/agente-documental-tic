"""Autenticación del modo web: contraseña de acceso compartida y sesión en cookie firmada.

La contraseña vive solo en la variable de entorno ACCESS_PASSWORD (Vercel); el navegador la
envía una vez a POST /auth/login y desde entonces usa la cookie de sesión.
"""
import hashlib
import hmac
import time
from fastapi import HTTPException, Request
from app.core.config import Settings

FAILED_LOGIN_DELAY = 1.0  # segundos; encarece los intentos por fuerza bruta


class WebAuth:
    def __init__(self, cfg: Settings):
        self.password = cfg.access_password.encode()
        # Huella de la contraseña vigente: si se cambia ACCESS_PASSWORD, las sesiones viejas dejan de valer.
        self.fingerprint = hmac.new(cfg.session_secret.encode(), self.password, hashlib.sha256).hexdigest()[:32]

    def login(self, request: Request, password: str) -> dict:
        if not hmac.compare_digest(password.encode(), self.password):
            time.sleep(FAILED_LOGIN_DELAY)
            raise HTTPException(status_code=401, detail="Contraseña incorrecta")
        user = {"name": "invitado"}
        request.session.clear()  # sesión nueva tras autenticar
        request.session.update({"user": user, "pw": self.fingerprint})
        return user

    def current_user(self, request: Request) -> dict:
        user = request.session.get("user")
        if not user or not hmac.compare_digest(request.session.get("pw", ""), self.fingerprint):
            raise HTTPException(status_code=401, detail="Escribe la contraseña de acceso")
        return user
