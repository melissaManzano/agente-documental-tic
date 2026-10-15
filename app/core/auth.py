"""Autenticación del modo web: Google Sign-In (OpenID Connect) y sesión en cookie firmada.

Solo pide los permisos `openid email` (no sensibles): sirve para saber QUIÉN entra,
no para leer Drive. La lectura de Drive sigue siendo local (OAuth Desktop).
"""
import secrets
from urllib.parse import urlencode
import httpx
from fastapi import HTTPException, Request
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import id_token
from app.core.config import Settings

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"


class WebAuth:
    def __init__(self, cfg: Settings):
        self.cfg = cfg
        self.emails = {e.strip().lower() for e in cfg.allowed_emails.split(",") if e.strip()}
        self.domain = cfg.allowed_domain.strip().lower()

    def is_allowed(self, email: str, hosted_domain: str = "") -> bool:
        return email in self.emails or bool(self.domain and hosted_domain == self.domain)

    def login_url(self, request: Request) -> str:
        # state protege contra CSRF; nonce liga el id_token a esta sesión.
        state, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        request.session.update({"oauth_state": state, "oauth_nonce": nonce})
        return AUTH_URL + "?" + urlencode({
            "client_id": self.cfg.google_client_id, "redirect_uri": self.cfg.oauth_redirect_uri,
            "response_type": "code", "scope": "openid email", "state": state, "nonce": nonce,
            "prompt": "select_account"})

    def complete_login(self, request: Request, code: str, state: str) -> dict:
        expected = request.session.pop("oauth_state", "")
        nonce = request.session.pop("oauth_nonce", "")
        if not expected or not secrets.compare_digest(expected, state or ""):
            raise HTTPException(status_code=400, detail="Estado OAuth inválido o caducado")
        response = httpx.post(TOKEN_URL, timeout=15, data={
            "code": code, "client_id": self.cfg.google_client_id,
            "client_secret": self.cfg.google_client_secret,
            "redirect_uri": self.cfg.oauth_redirect_uri, "grant_type": "authorization_code"})
        if response.status_code != 200:
            raise HTTPException(status_code=400, detail="Google rechazó el código de autorización")
        # Verifica firma, emisor, audiencia (client_id) y caducidad del id_token.
        claims = id_token.verify_oauth2_token(response.json()["id_token"], GoogleRequest(),
                                              self.cfg.google_client_id)
        if not nonce or claims.get("nonce") != nonce:
            raise HTTPException(status_code=400, detail="nonce inválido")
        email, hosted_domain = claims.get("email", "").lower(), claims.get("hd", "").lower()
        if not claims.get("email_verified") or not self.is_allowed(email, hosted_domain):
            raise HTTPException(status_code=403, detail="Cuenta no autorizada")
        user = {"email": email, "hd": hosted_domain}
        request.session.clear()  # sesión nueva tras autenticar
        request.session["user"] = user
        return user

    def current_user(self, request: Request) -> dict:
        user = request.session.get("user")
        # La lista de permitidos se revalida en cada petición por si cambió.
        if not user or not self.is_allowed(user.get("email", ""), user.get("hd", "")):
            raise HTTPException(status_code=401, detail="Inicia sesión con una cuenta autorizada")
        return user
