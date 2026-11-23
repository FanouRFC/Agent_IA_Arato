"""Réinitialise la base de l'application (supprime puis recrée toutes les tables et le trigger).
À utiliser après une mise à jour du modèle de données : python -m app.reset"""
from .db import Base, engine, init_db


def main():
    from . import models  # noqa: F401
    Base.metadata.drop_all(engine)
    init_db()
    print("Base de l'application réinitialisée (tables + trigger PostgreSQL). Relancez le backend.")


if __name__ == "__main__":
    main()
