from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    crm_database_url: str = "postgresql+psycopg2://arato:arato@localhost:5432/arato_crm"
    crm_service_key: str = "change-me-service-key"


settings = Settings()
