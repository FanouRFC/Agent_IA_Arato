from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings

engine = create_engine(settings.app_database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    with SessionLocal() as db:
        yield db


# Trigger PostgreSQL : date_echeance_initiale est un repère historique immuable (tout UPDATE est rejeté)
TRIGGER_SQL = """
CREATE OR REPLACE FUNCTION freeze_echeance_initiale() RETURNS trigger AS $$
BEGIN
  IF OLD.date_echeance_initiale IS NOT NULL
     AND NEW.date_echeance_initiale IS DISTINCT FROM OLD.date_echeance_initiale THEN
    RAISE EXCEPTION 'date_echeance_initiale est immuable (figée par trigger)';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_freeze_echeance ON taches;
CREATE TRIGGER trg_freeze_echeance BEFORE UPDATE ON taches
  FOR EACH ROW EXECUTE FUNCTION freeze_echeance_initiale();
"""


def _migrer_utilisateurs():
    """Mise à jour d'une base existante : utilisateurs.nom → email, + colonnes actif et date_creation.
    Idempotent ; ne supprime aucune donnée (id, password_hash et role sont conservés)."""
    from sqlalchemy import inspect, text
    if engine.dialect.name != "postgresql":
        return
    insp = inspect(engine)
    if "utilisateurs" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("utilisateurs")}
    with engine.begin() as conn:
        if "nom" in cols and "email" not in cols:
            conn.execute(text("ALTER TABLE utilisateurs RENAME COLUMN nom TO email"))
            conn.execute(text("ALTER TABLE utilisateurs ALTER COLUMN email TYPE VARCHAR(254)"))
            # l'ancien identifiant (ex. « responsable ») devient l'e-mail du premier compte
            conn.execute(text("UPDATE utilisateurs SET email = :e WHERE email NOT LIKE '%@%' AND id = "
                              "(SELECT MIN(id) FROM utilisateurs)"), {"e": settings.admin_email.lower()})
            conn.execute(text("UPDATE utilisateurs SET email = lower(email) WHERE email LIKE '%@%'"))
        if "actif" not in cols:
            conn.execute(text("ALTER TABLE utilisateurs ADD COLUMN actif BOOLEAN NOT NULL DEFAULT TRUE"))
        if "date_creation" not in cols:
            conn.execute(text("ALTER TABLE utilisateurs ADD COLUMN date_creation TIMESTAMP DEFAULT now()"))


def _migrer_conversations():
    """Ajoute conversations_chat.id_conversation aux bases existantes (idempotent, aucune donnée supprimée)."""
    from sqlalchemy import inspect, text
    if engine.dialect.name != "postgresql":
        return
    insp = inspect(engine)
    if "conversations_chat" not in insp.get_table_names():
        return
    if "id_conversation" not in {c["name"] for c in insp.get_columns("conversations_chat")}:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE conversations_chat ADD COLUMN id_conversation VARCHAR(40)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_conversations_chat_id_conversation ON conversations_chat (id_conversation)"))


def init_db():
    from . import models  # noqa: F401
    _migrer_utilisateurs()
    _migrer_conversations()
    Base.metadata.create_all(engine)
    if engine.dialect.name == "postgresql":  # le trigger n'existe que sous PostgreSQL (dev et production)
        with engine.begin() as conn:
            conn.exec_driver_sql(TRIGGER_SQL)
