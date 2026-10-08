"""Base du CRM : tickets, membres, projets, historique. Aucun calcul de date ici."""
import datetime as dt
from typing import Optional

from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Integer, String, Table, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from .config import settings

engine = create_engine(settings.crm_database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


ticket_membres = Table(
    "ticket_membres", Base.metadata,
    Column("ticket_id", ForeignKey("tickets.id"), primary_key=True),
    Column("membre_id", ForeignKey("membres.id"), primary_key=True),
)
ticket_deps = Table(
    "ticket_deps", Base.metadata,
    Column("ticket_id", ForeignKey("tickets.id"), primary_key=True),
    Column("depend_de_id", ForeignKey("tickets.id"), primary_key=True),
)


class Projet(Base):
    __tablename__ = "projets"
    id: Mapped[int] = mapped_column(primary_key=True)
    nom: Mapped[str] = mapped_column(String(200))


class Membre(Base):
    __tablename__ = "membres"
    id: Mapped[int] = mapped_column(primary_key=True)
    nom: Mapped[str] = mapped_column(String(120))
    profil: Mapped[str] = mapped_column(String(80))
    email: Mapped[str] = mapped_column(String(200))


class Ticket(Base):
    __tablename__ = "tickets"
    id: Mapped[int] = mapped_column(primary_key=True)
    titre: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    statut: Mapped[str] = mapped_column(String(20), default="nouveau")
    avancement_declare: Mapped[int] = mapped_column(Integer, default=0)
    date_creation: Mapped[dt.date] = mapped_column(Date, default=dt.date.today)
    echeance: Mapped[dt.date] = mapped_column(Date)           # écriture : connecteur seul
    est_en_retard: Mapped[bool] = mapped_column(Boolean, default=False)  # écriture : connecteur seul
    date_fermeture: Mapped[Optional[dt.date]] = mapped_column(Date, nullable=True)
    motif_attente_courant: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    motif_retard_courant: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    projet_id: Mapped[int] = mapped_column(ForeignKey("projets.id"))
    membres = relationship(Membre, secondary=ticket_membres, lazy="selectin")
    depend_de = relationship(
        "Ticket", secondary=ticket_deps, lazy="selectin",
        primaryjoin="Ticket.id==ticket_deps.c.ticket_id",
        secondaryjoin="Ticket.id==ticket_deps.c.depend_de_id",
    )


class HistoriqueStatut(Base):
    """Chaque changement de statut ET chaque motif (attente / retard). Jamais écrasé."""
    __tablename__ = "historique_statut"
    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), index=True)
    date: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.now)
    statut: Mapped[str] = mapped_column(String(20))
    type_motif: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)  # attente | retard
    categorie: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    motif: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    auteur_id: Mapped[Optional[int]] = mapped_column(nullable=True)
    date_resolution: Mapped[Optional[dt.datetime]] = mapped_column(DateTime, nullable=True)


class HistoriqueAvancement(Base):
    __tablename__ = "historique_avancement"
    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), index=True)
    date: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.now)
    ancienne: Mapped[int] = mapped_column(Integer)
    nouvelle: Mapped[int] = mapped_column(Integer)
    auteur_id: Mapped[Optional[int]] = mapped_column(nullable=True)


class Evenement(Base):
    """Flux des changements, lu par le backend via le connecteur (détection événementielle)."""
    __tablename__ = "evenements"
    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(Integer, index=True)
    type: Mapped[str] = mapped_column(String(40))
    detail: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(10), default="crm")  # crm (équipe) | service (backend)
    date: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.now)
