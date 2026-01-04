from sqlalchemy import create_engine, Column, Integer, String, Float, Text, DateTime, ForeignKey, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime

DATABASE_URL = "sqlite:///./imoveis.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

# Tabela de Administração (Login)
class AdminUser(Base):
    __tablename__ = "admin_users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)

# Tabela de Lugares/Guias
class LugarDB(Base):
    __tablename__ = "lugares"
    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String, unique=True, index=True)
    descricao = Column(Text)
    bares_restaurantes = Column(Text, nullable=True)
    pontos_interesse = Column(Text, nullable=True)
    imagem_principal = Column(String, nullable=True)

    # CORREÇÃO: back_populates aponta para a propriedade 'lugar' em ImovelDB
    imoveis = relationship("ImovelDB", back_populates="lugar")

# Tabela de Imóveis
class ImovelDB(Base):
    __tablename__ = "imoveis"
    id = Column(Integer, primary_key=True, index=True)
    titulo = Column(String, index=True)
    descricao = Column(Text)
    preco = Column(String)
    
    # RELACIONAMENTO COM LUGAR
    lugar_id = Column(Integer, ForeignKey("lugares.id"), nullable=True)
    # CORREÇÃO: back_populates aponta para a propriedade 'imoveis' em LugarDB
    lugar = relationship("LugarDB", back_populates="imoveis")
    
    bairro = Column(String) 
    quartos = Column(Integer)
    banheiros = Column(Integer)
    area = Column(Integer)
    fotos = Column(String) 
    whatsapp = Column(String)
    tipo = Column(String)

# Tabela da Capa do Site (Hero)
class HeroDB(Base):
    __tablename__ = "hero"
    id = Column(Integer, primary_key=True, index=True)
    titulo_capa = Column(String, default="Viva o Melhor do Litoral")
    subtitulo_capa = Column(String, default="Encontre seu refúgio na praia.")
    imagem_capa = Column(String, default="/static/uploads/default_capa.jpg")

# Tabela de Contato/Leads
class ContatoDB(Base):
    __tablename__ = "contatos"
    id = Column(Integer, primary_key=True, index=True)
    imovel_id = Column(Integer)
    imovel_titulo = Column(String)
    nome = Column(String)
    email = Column(String)
    telefone = Column(String)
    mensagem = Column(Text)
    data_envio = Column(DateTime, default=datetime.now)