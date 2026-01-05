from pydantic import BaseModel
from typing import List, Optional

class Imovel(BaseModel):
    id: int
    titulo: str
    descricao: str
    preco: str
    bairro: str
    quartos: int
    banheiros: int
    area: int
    fotos: List[str]  # Agora é uma lista de URLs para o carrossel
    whatsapp: str
    tipo: str         # "Venda" ou "Aluguel"