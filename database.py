# database.py
import os
from datetime import datetime

from sqlalchemy import (
    create_engine, Column, Integer, String, Text, DateTime, ForeignKey
)
from sqlalchemy.orm import sessionmaker, relationship, declarative_base

# -----------------------------------------------------------------------------
# DATABASE_URL:
# - No Render: vem do Environment Variables (Postgres)
# - Local: cai no sqlite ./imoveis.db
# -----------------------------------------------------------------------------
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./imoveis.db")

connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# -----------------------------------------------------------------------------
# MODELS
# -----------------------------------------------------------------------------

class AdminUser(Base):
    __tablename__ = "admin_users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)

class LugarDB(Base):
    __tablename__ = "lugares"
    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String(200), unique=True, index=True, nullable=False)
    descricao = Column(Text, nullable=True)
    bares_restaurantes = Column(Text, nullable=True)
    pontos_interesse = Column(Text, nullable=True)
    imagem_principal = Column(String(500), nullable=True)

    imoveis = relationship("ImovelDB", back_populates="lugar")

class ImovelDB(Base):
    __tablename__ = "imoveis"
    id = Column(Integer, primary_key=True, index=True)
    titulo = Column(String(200), index=True, nullable=False)
    descricao = Column(Text, nullable=True)
    preco = Column(String(100), nullable=True)

    lugar_id = Column(Integer, ForeignKey("lugares.id"), nullable=True)
    lugar = relationship("LugarDB", back_populates="imoveis")

    bairro = Column(String(200), nullable=True)
    quartos = Column(Integer, nullable=True)
    banheiros = Column(Integer, nullable=True)
    area = Column(Integer, nullable=True)

    # csv: "/static/uploads/a.jpg,/static/uploads/b.jpg" etc
    fotos = Column(Text, nullable=True)

    whatsapp = Column(String(50), nullable=True)
    tipo = Column(String(100), nullable=True)

class HeroDB(Base):
    __tablename__ = "hero"
    id = Column(Integer, primary_key=True, index=True)
    titulo_capa = Column(String(200), default="Viva o Melhor do Litoral")
    subtitulo_capa = Column(String(300), default="Encontre seu refúgio na praia.")
    imagem_capa = Column(String(500), default="/static/uploads/placeholder.png")

class ContatoDB(Base):
    __tablename__ = "contatos"
    id = Column(Integer, primary_key=True, index=True)
    imovel_id = Column(Integer, nullable=False)
    imovel_titulo = Column(String(200), nullable=True)

    nome = Column(String(200), nullable=False)
    email = Column(String(200), nullable=False)
    telefone = Column(String(100), nullable=False)
    mensagem = Column(Text, nullable=False)

    data_envio = Column(DateTime, default=datetime.utcnow)
