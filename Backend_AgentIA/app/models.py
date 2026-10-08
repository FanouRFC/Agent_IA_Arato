"""Base de l'application (PostgreSQL) – figure 8."""
import datetime as dt
from typing import Optional

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class User(Base):
    __tablename__ = "utilisateurs"
    id: Mapped[int] = mapped_column(primary_key=True)
    nom: Mapped[str] = mapped_column(String(80), unique=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(30), default="haut_responsable")


class Projet(Base):
    __tablename__ = "projets"
    id: Mapped[int] = mapped_column(primary_key=True)
    nom: Mapped[str] = mapped_column(String(200))
    date_limite: Mapped[Optional[dt.date]] = mapped_column(Date, nullable=True)
    statut: Mapped[str] = mapped_column(String(30), default="en_preparation")
    crm_projet_id: Mapped[Optional[int]] = mapped_column(nullable=True)


class CahierDesCharges(Base):
    __tablename__ = "cahiers"
    id: Mapped[int] = mapped_column(primary_key=True)
    projet_id: Mapped[int] = mapped_column(ForeignKey("projets.id"))
    nom_fichier: Mapped[str] = mapped_column(String(300), default="texte")
    texte: Mapped[str] = mapped_column(Text)
    date_depot: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.now)
    statut: Mapped[str] = mapped_column(String(20), default="brouillon")  # brouillon | valide | partiel
    ambiguites: Mapped[list] = mapped_column(JSON, default=list)
    projet = relationship(Projet)
    taches = relationship("Tache", back_populates="cahier", order_by="Tache.ordre", cascade="all, delete-orphan")


class Tache(Base):
    """Brouillon de tâche, puis lien vers le ticket CRM."""
    __tablename__ = "taches"
    id: Mapped[int] = mapped_column(primary_key=True)
    cahier_id: Mapped[int] = mapped_column(ForeignKey("cahiers.id"))
    ordre: Mapped[int] = mapped_column(Integer)
    titre: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    criteres_acceptation: Mapped[list] = mapped_column(JSON, default=list)
    priorite: Mapped[str] = mapped_column(String(10), default="moyenne")
    raison_priorite: Mapped[str] = mapped_column(Text, default="")
    duree_estimee: Mapped[int] = mapped_column(Integer, default=1)   # jours ouvrés (validée / ajustée)
    duree_proposee: Mapped[int] = mapped_column(Integer, default=1)  # proposition initiale de l'agent
    date_echeance_initiale: Mapped[Optional[dt.date]] = mapped_column(Date, nullable=True)  # figée (trigger)
    depend_de: Mapped[list] = mapped_column(JSON, default=list)      # liste d'ordres de tâches
    source_dans_document: Mapped[str] = mapped_column(Text, default="")
    niveau_confiance: Mapped[float] = mapped_column(Float, default=0.5)
    profil_recommande: Mapped[str] = mapped_column(String(100), default="")
    ambiguites: Mapped[list] = mapped_column(JSON, default=list)
    membre_ids: Mapped[list] = mapped_column(JSON, default=list)
    origine: Mapped[str] = mapped_column(String(10), default="agent")  # agent | manuel
    statut_relecture: Mapped[str] = mapped_column(String(12), default="proposee")  # proposee|acceptee|modifiee|supprimee
    modifiee_par_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    id_ticket_crm: Mapped[Optional[int]] = mapped_column(nullable=True)
    cahier = relationship(CahierDesCharges, back_populates="taches")


class SuiviRetard(Base):
    __tablename__ = "suivi_retard"
    id: Mapped[int] = mapped_column(primary_key=True)
    id_ticket: Mapped[int] = mapped_column(Integer, index=True)
    date_calcul: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.now)
    est_en_retard: Mapped[bool] = mapped_column(Boolean)
    jours_de_retard: Mapped[int] = mapped_column(Integer, default=0)
    retard_final: Mapped[Optional[int]] = mapped_column(nullable=True)
    situation: Mapped[str] = mapped_column(String(20))


class AnalyseTicket(Base):
    __tablename__ = "analyses_ticket"
    id: Mapped[int] = mapped_column(primary_key=True)
    id_ticket: Mapped[int] = mapped_column(Integer, index=True)
    date: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.now)
    declencheur: Mapped[str] = mapped_column(String(200), default="")
    contenu: Mapped[dict] = mapped_column(JSON)   # analyse, risque, prédiction, diagnostic, source


class SyntheseSuivi(Base):
    __tablename__ = "syntheses_suivi"
    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.now)
    declencheur: Mapped[str] = mapped_column(String(200), default="")
    contenu: Mapped[str] = mapped_column(Text)
    chiffres: Mapped[dict] = mapped_column(JSON, default=dict)  # chiffres Python de référence


class Recommandation(Base):
    __tablename__ = "recommandations"
    id: Mapped[int] = mapped_column(primary_key=True)
    id_ticket: Mapped[int] = mapped_column(Integer, index=True)
    date: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.now)
    type: Mapped[str] = mapped_column(String(30), default="")
    texte: Mapped[str] = mapped_column(Text)
    chiffres: Mapped[dict] = mapped_column(JSON, default=dict)
    diagnostic: Mapped[str] = mapped_column(String(30), default="")
    source: Mapped[str] = mapped_column(String(10), default="llm")  # llm | fallback
    decision: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)  # suivie | rejetee


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(20), default="creation")
    id_tache: Mapped[int] = mapped_column(Integer)
    destinataire: Mapped[str] = mapped_column(String(200))
    texte: Mapped[str] = mapped_column(Text)
    statut: Mapped[str] = mapped_column(String(10), default="envoye")  # envoye | echec
    date_envoi: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.now)


class ConversationChat(Base):
    __tablename__ = "conversations_chat"
    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.now)
    question: Mapped[str] = mapped_column(Text)
    reponse: Mapped[str] = mapped_column(Text)


class JournalAction(Base):
    __tablename__ = "journal_actions"
    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.now)
    action: Mapped[str] = mapped_column(Text)
    auteur: Mapped[str] = mapped_column(String(80), default="système")


class Rapport(Base):
    __tablename__ = "rapports"
    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.now)
    format: Mapped[str] = mapped_column(String(10))
    contenu: Mapped[str] = mapped_column(Text, default="")


class Setting(Base):
    __tablename__ = "parametres"
    cle: Mapped[str] = mapped_column(String(60), primary_key=True)
    valeur: Mapped[dict] = mapped_column(JSON)  # {"v": ...}
