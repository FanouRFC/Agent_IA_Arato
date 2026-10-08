from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    app_database_url: str = "postgresql+psycopg2://arato:arato@localhost:5432/arato_app"
    crm_url: str = "http://localhost:8001"
    crm_service_key: str = "change-me-service-key"
    jwt_secret: str = "change-me"
    admin_username: str = "responsable"
    admin_password: str = "changeme"
    # Fournisseur LLM : simple paramètre de configuration (API compatible OpenAI : Ollama, vLLM, etc.)
    llm_base_url: str = "http://localhost:11434/v1"
    llm_model: str = "qwen2.5:7b-instruct"
    llm_api_key: str = "ollama"
    mail_server: str = "localhost"
    mail_port: int = 1025
    mail_from: str = "agent-ia@arato.mg"
    mail_username: str = ""
    mail_password: str = ""
    mail_starttls: bool = False
    mail_ssl_tls: bool = False
    holidays: str = "2026-11-01,2026-12-25,2027-01-01,2027-03-29,2027-05-01,2027-06-26,2027-08-15"
    work_day_end: str = "17:00"
    seuil_jours: int = 2
    seuil_avancement: int = 50
    event_poll_seconds: int = 10
    temporal_tick_seconds: int = 60
    cors_origins: str = "http://localhost:5173"


settings = Settings()
