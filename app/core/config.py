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
    access_password: str = os.getenv("ACCESS_PASSWORD", "")
    session_secret: str = os.getenv("SESSION_SECRET", "")

    def missing_web_settings(self) -> list[str]:
        """Nombres (nunca valores) de las variables obligatorias que faltan en modo web.

        ACCESS_PASSWORD es opcional: vacía = sitio público; con valor = se pide contraseña
        y entonces SESSION_SECRET también es obligatoria.
        """
        required = {"OPENAI_API_KEY": self.openai_api_key, "VECTOR_STORE_ID": self.vector_store_id}
        if self.access_password:
            required["SESSION_SECRET"] = self.session_secret
        missing = [name for name, value in required.items() if not value]
        if 0 < len(self.access_password) < 12:
            missing.append("ACCESS_PASSWORD (mínimo 12 caracteres)")
        if self.access_password and 0 < len(self.session_secret) < 32:
            missing.append("SESSION_SECRET (mínimo 32 caracteres)")
        return missing

settings = Settings()
