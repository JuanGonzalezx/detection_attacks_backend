"""Configuracion central: lee variables de entorno (o .env) y las valida."""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # WhatsApp Cloud API
    whatsapp_phone_number_id: str = ""
    whatsapp_access_token: str = ""
    whatsapp_verify_token: str = "change-me"
    whatsapp_api_version: str = "v22.0"
    whatsapp_app_secret: str = ""

    # Lambda de deteccion de fraude
    fraud_api_url: str = "https://6v39g0i9ga.execute-api.us-east-1.amazonaws.com/upload-image"

    # Supabase / Postgres
    database_url: str = ""

    # Gemini API
    gemini_api_key: str = ""

    @property
    def graph_base(self) -> str:
        return f"https://graph.facebook.com/{self.whatsapp_api_version}"

    def missing_required(self) -> list[str]:
        """Devuelve los nombres de las variables criticas que faltan."""
        required = {
            "WHATSAPP_PHONE_NUMBER_ID": self.whatsapp_phone_number_id,
            "WHATSAPP_ACCESS_TOKEN": self.whatsapp_access_token,
            "WHATSAPP_VERIFY_TOKEN": self.whatsapp_verify_token,
            "FRAUD_API_URL": self.fraud_api_url,
            "DATABASE_URL": self.database_url,
            "GEMINI_API_KEY": self.gemini_api_key,
        }
        return [name for name, value in required.items() if not value or value == "change-me"]


settings = Settings()
