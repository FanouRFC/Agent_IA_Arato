-- v19 : cases cochées des critères d'acceptation (clôture conditionnée).
-- Nouvelle TABLE uniquement : aucune table ni colonne existante n'est modifiée. Idempotent.
-- Base concernée : arato_app (l'application la crée aussi automatiquement au démarrage via create_all).
CREATE TABLE IF NOT EXISTS validations_criteres (
    id         SERIAL PRIMARY KEY,
    id_ticket  INTEGER NOT NULL,
    critere    TEXT NOT NULL,
    valide_par VARCHAR(254) NOT NULL DEFAULT '',
    date       TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_validations_criteres_id_ticket ON validations_criteres (id_ticket);
