-- Crée le rôle « arato » et les bases arato_app / arato_crm. Fonctionne sous Windows, macOS et Linux :
--   psql -U postgres -f scripts/setup_db.sql
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'arato') THEN
    CREATE ROLE arato LOGIN PASSWORD 'arato';
  END IF;
END $$;
SELECT 'CREATE DATABASE arato_app OWNER arato' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'arato_app')\gexec
SELECT 'CREATE DATABASE arato_crm OWNER arato' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'arato_crm')\gexec
