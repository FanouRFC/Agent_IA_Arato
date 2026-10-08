"""Jeu de données de test, réexécutable : python -m app.seed
3-5 projets, 8-12 membres, 30-50 tickets, tous statuts, retards avec/sans motif, attentes multiples, etc."""
import datetime as dt
import random

from .models import (Base, Evenement, HistoriqueAvancement, HistoriqueStatut, Membre, Projet, SessionLocal, Ticket,
                     engine)

random.seed(7)
TODAY = dt.date.today()


def bd(d, n):
    """Jours ouvrés (sans jours fériés dans le seed)."""
    step = 1 if n >= 0 else -1
    k = abs(n)
    while k:
        d += dt.timedelta(days=step)
        if d.weekday() < 5:
            k -= 1
    return d


def ago(days):
    return dt.datetime.now() - dt.timedelta(days=days)


def main():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    db = SessionLocal()
    projets = [Projet(nom=n) for n in ("Portail client", "Application mobile", "Migration ERP", "Site e-commerce")]
    membres = [Membre(nom=n, profil=p, email=f"{n.split()[0].lower()}@arato.test") for n, p in [
        ("Faly Rakoto", "Développeur backend"), ("Miora Andry", "Développeur frontend"),
        ("Tojo Rabe", "Développeur backend"), ("Lalaina Ravo", "Designer UI/UX"),
        ("Hery Randria", "Testeur QA"), ("Nirina Soa", "Chef de projet"),
        ("Voahangy Ny", "Analyste données"), ("Kanto Mamy", "DevOps"),
        ("Fenitra Hasi", "Développeur frontend"), ("Aina Tiana", "Développeur backend")]]
    db.add_all(projets + membres)
    db.flush()

    def mk(titre, p, statut, av, off, mem, deps=(), closed_off=None, desc=""):
        t = Ticket(titre=titre, description=desc or titre, projet_id=projets[p].id, statut=statut,
                   avancement_declare=av, echeance=bd(TODAY, off), date_creation=bd(TODAY, off - 8))
        t.membres = [membres[i] for i in mem]
        t.depend_de = list(deps)
        if closed_off is not None:
            t.date_fermeture = bd(t.echeance, closed_off)
        db.add(t)
        db.flush()
        db.add(HistoriqueStatut(ticket_id=t.id, statut="nouveau", date=ago(12)))
        if av:
            db.add(HistoriqueAvancement(ticket_id=t.id, ancienne=0, nouvelle=av, auteur_id=membres[mem[0]].id,
                                        date=ago(4)))
        return t

    def attente(t, cat, motif, d0, d1=None):
        db.add(HistoriqueStatut(ticket_id=t.id, statut="en_attente", date=ago(d0), auteur_id=t.membres[0].id))
        db.add(HistoriqueStatut(ticket_id=t.id, statut="en_attente", type_motif="attente", categorie=cat, motif=motif,
                                auteur_id=t.membres[0].id, date=ago(d0), date_resolution=ago(d1) if d1 else None))
        if d1:
            db.add(HistoriqueStatut(ticket_id=t.id, statut="en_cours", date=ago(d1), auteur_id=t.membres[0].id))
        else:
            t.motif_attente_courant = motif

    # Scénarios clés
    t_int = mk("Connecteur API paiement", 0, "en_cours", 50, -3, [0], desc="Intégration API de paiement")
    t_int.motif_retard_courant = "Erreur d'intégration"
    db.add(HistoriqueStatut(ticket_id=t_int.id, statut="en_cours", type_motif="retard",
                            motif="Erreur d'intégration", auteur_id=membres[0].id, date=ago(1)))
    attente(t_int, "problème technique", "Erreur d'intégration", 9, 7)
    attente(t_int, "problème technique", "Erreur d'intégration", 6, 4)
    attente(t_int, "problème technique", "Erreur d'intégration", 3, 2)
    mk("Écran de connexion", 0, "en_cours", 25, -1, [1])                      # retard sans motif
    base = mk("Modèle de données commandes", 0, "en_cours", 25, 1, [2])       # à surveiller, bloque 2 tickets
    mk("API commandes", 0, "nouveau", 0, 5, [0], deps=[base])
    mk("Page récapitulatif commande", 0, "nouveau", 0, 6, [1], deps=[base])
    t_att = mk("Import des données client", 2, "en_attente", 50, -2, [6])      # attente + échéance dépassée
    attente(t_att, "information manquante", "Données du client manquantes", 7, 5)
    attente(t_att, "information manquante", "Données du client manquantes", 4)
    mk("Maquettes tunnel d'achat", 3, "ferme", 100, -6, [3], closed_off=1)    # fermé avec retard final
    mk("Recette module panier", 3, "ferme", 100, -4, [4], closed_off=0)
    o1 = mk("Refonte navigation mobile", 1, "ouvert", 25, 2, [1, 8])          # ouvert multi, à surveiller
    o2 = mk("Tests de charge", 1, "ouvert", 50, -2, [7, 4, 9])                # ouvert multi en retard
    o2.motif_retard_courant = "Environnement de test indisponible"
    db.add(HistoriqueStatut(ticket_id=o2.id, statut="ouvert", type_motif="retard",
                            motif="Environnement de test indisponible", auteur_id=membres[7].id, date=ago(1)))
    mk("Déploiement préproduction", 1, "en_cours", 75, 10, [7])               # normal
    # Remplissage aléatoire
    titres = ["Authentification SSO", "Export PDF", "Tableau de bord KPI", "Notifications push", "Recherche avancée",
              "Gestion des rôles", "Migration des comptes", "Optimisation requêtes", "Documentation utilisateur",
              "Formulaire d'inscription", "Cache applicatif", "Revue de sécurité", "Module de paiement",
              "Journal d'audit", "Synchronisation hors-ligne", "Import CSV", "Pagination", "Thème sombre",
              "Intégration annuaire", "Rapports mensuels", "Sauvegarde automatique", "Tests end-to-end"]
    for titre in titres:
        statut = random.choice(["nouveau", "ouvert", "en_cours", "en_cours", "en_attente", "ferme"])
        mem = random.sample(range(len(membres)), 2 if statut == "ouvert" else 1)
        off = random.choice([-4, -1, 2, 3, 6, 8, 12])
        av = {"nouveau": 0, "ferme": 100}.get(statut, random.choice([0, 25, 50, 75]))
        t = mk(titre, random.randrange(len(projets)), statut, av, off, mem,
               closed_off=random.choice([0, 0, 2]) if statut == "ferme" else None)
        if statut == "en_attente":
            attente(t, random.choice(["attente d'une validation", "dépendance non terminée"]), "En attente de retour", 3)
    db.add(Evenement(ticket_id=0, type="seed", source="service"))
    db.commit()
    print(f"{len(projets)} projets, {len(membres)} membres, {db.query(Ticket).count()} tickets créés.")


if __name__ == "__main__":
    main()
