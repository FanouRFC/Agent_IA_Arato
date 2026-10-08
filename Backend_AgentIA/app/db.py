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


def init_db():
    from . import models  # noqa: F401
    Base.metadata.create_all(engine)
    if engine.dialect.name == "postgresql":  # le trigger n'existe que sous PostgreSQL (dev et production)
        with engine.begin() as conn:
            conn.exec_driver_sql(TRIGGER_SQL)
