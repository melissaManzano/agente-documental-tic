"""Configuración centralizada; carga .env solo en el servidor."""
import os
from dataclasses import dataclass
from dotenv import load_dotenv
load_dotenv()

@dataclass(frozen=True)
class Settings:
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    drive_folder_id: str = os.getenv("GOOGLE_DRIVE_FOLDER_ID", "")
    vector_store_id: str = os.getenv("VECTOR_STORE_ID", "")
    local_admin_key: str = os.getenv("LOCAL_ADMIN_KEY", "")
    # Modo web (Vercel): se activa en Vercel o con APP_MODE=web. Ver docs/despliegue-vercel.md.
    web_mode: bool = bool(os.getenv("VERCEL")) or os.getenv("APP_MODE", "").lower() == "web"
    google_client_id: str = os.getenv("GOOGLE_CLIENT_ID", "")
    google_client_secret: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
    oauth_redirect_uri: str = os.getenv("OAUTH_REDIRECT_URI", "")
    session_secret: str = os.getenv("SESSION_SECRET", "")
    allowed_emails: str = os.getenv("ALLOWED_EMAILS", "")
    allowed_domain: str = os.getenv("ALLOWED_DOMAIN", "")

    def missing_web_settings(self) -> list[str]:
        """Nombres (nunca valores) de las variables obligatorias que faltan en modo web."""
        required = {"OPENAI_API_KEY": self.openai_api_key, "VECTOR_STORE_ID": self.vector_store_id,
                    "GOOGLE_CLIENT_ID": self.google_client_id, "GOOGLE_CLIENT_SECRET": self.google_client_secret,
                    "OAUTH_REDIRECT_URI": self.oauth_redirect_uri, "SESSION_SECRET": self.session_secret}
        missing = [name for name, value in required.items() if not value]
        if len(self.session_secret) < 32 and "SESSION_SECRET" not in missing:
            missing.append("SESSION_SECRET (mínimo 32 caracteres)")
        if not (self.allowed_emails or self.allowed_domain):
            missing.append("ALLOWED_EMAILS o ALLOWED_DOMAIN")
        return missing

settings = Settings()
