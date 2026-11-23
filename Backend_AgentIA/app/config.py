from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    app_database_url: str = "postgresql+psycopg2://arato:arato@localhost:5432/arato_app"
    crm_url: str = "http://localhost:8001"
    crm_service_key: str = "change-me-service-key"
    jwt_secret: str = "change-me"
    admin_email: str = "responsable@arato.mg"      # premier compte responsable (créé au démarrage s'il n'existe pas)
    admin_password: str = "changeme"
    app_env: str = "development"                   # « production » : le démarrage est refusé avec des secrets par défaut

    # Fournisseur LLM : API en ligne (toute API compatible OpenAI : Groq, Google Gemini, OpenRouter, Mistral…).
    # La clé d'API se configure UNIQUEMENT ici (fichier .env du serveur) ; elle n'est jamais exposée à l'interface.
    llm_base_url: str = "https://api.groq.com/openai/v1"
    llm_model: str = "llama-3.3-70b-versatile"
    llm_api_key: str = ""
    llm_timeout: int = 120            # secondes par appel
    llm_max_retries: int = 4          # nouvelles tentatives sur 429 / 5xx / erreur réseau
    llm_min_interval: float = 2.5     # secondes minimum entre deux appels (limite de débit des API en ligne)
    llm_max_doc_chars: int = 15000    # taille maximale du cahier des charges envoyé au modèle

    mail_server: str = "localhost"
    mail_port: int = 1025
    mail_from: str = "agent-ia@arato.mg"
    mail_username: str = ""
    mail_password: str = ""
    mail_starttls: bool | None = None   # None = automatique (STARTTLS dès que le serveur le propose, toujours sur le port 587)
    mail_ssl_tls: bool | None = None    # None = automatique (SSL sur le port 465)
    holidays: str = "2026-11-01,2026-12-25,2027-01-01,2027-03-29,2027-05-01,2027-06-26,2027-08-15"
    work_day_end: str = "17:00"
    seuil_jours: int = 2
    seuil_avancement: int = 50
    event_poll_seconds: int = 2      # détection des changements du CRM (la situation suit en quelques secondes)
    temporal_tick_seconds: int = 60
    auto_eval_seconds: int = 30       # évaluation automatique : délai de détection d'un projet sans synthèse
    upload_max_mb: int = 10
    cors_origins: str = "http://localhost:5173"


settings = Settings()
