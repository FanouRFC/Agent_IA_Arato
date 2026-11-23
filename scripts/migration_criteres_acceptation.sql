-- Migration : critères d'acceptation des tickets (base du CRM « arato_crm »).
-- Idempotente et sans perte : le CRM l'applique aussi tout seul à son démarrage (CRM_AgentIA/app/main.py : migrer()).
--   psql -U arato -d arato_crm -f scripts/migration_criteres_acceptation.sql
ALTER TABLE tickets ADD COLUMN IF NOT EXISTS criteres_acceptation JSON;
-- Base de l'application « arato_app » : la colonne taches.criteres_acceptation (JSON) existe déjà, aucune migration.
