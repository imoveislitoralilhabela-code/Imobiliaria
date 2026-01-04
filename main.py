# main.py

from fastapi import FastAPI, Request, Form, Depends, HTTPException, status, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from typing import List, Optional
import os
import shutil

# Importações de Segurança
from passlib.context import CryptContext
from jose import jwt, JWTError

# Importações de Banco de Dados
from database import Base, engine, SessionLocal, HeroDB, LugarDB, ImovelDB, ContatoDB, AdminUser

# =========================================================================
# 1. CONFIGURAÇÃO DE SEGURANÇA E ARQUIVOS
# =========================================================================

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
SECRET_KEY = "sua-chave-secreta-litoralprime"
ALGORITHM = "HS256"

UPLOAD_DIR = "static/uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

TRANSLATION_PT_FALLBACK = {
    "home": "Início", "location": "O Lugar", "admin": "Admin", "details": "Ver Detalhes", "contact": "Contato"
}

Base.metadata.create_all(bind=engine)

def create_initial_admin_user(db: Session):
    if not db.query(AdminUser).filter(AdminUser.username == "admin").first():
        RAW_PASSWORD = "123456" 
        hashed_password = pwd_context.hash(RAW_PASSWORD)
        admin_user = AdminUser(
            username="admin", 
            hashed_password=hashed_password
        )
        db.add(admin_user)
        db.commit()
        print("\n✅ Usuário Admin ('admin' / '123456') criado no banco de dados.\n")

with SessionLocal() as db:
    create_initial_admin_user(db)


# =========================================================================
# 3. CONFIGURAÇÃO DO APP E UTILITÁRIOS
# =========================================================================

app = FastAPI()
templates = Jinja2Templates(directory="templates")

app.mount("/static", StaticFiles(directory="static"), name="static")

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=30) 
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def decode_access_token(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        return username
    except JWTError:
        return None

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def salvar_arquivos(files: List[UploadFile]) -> List[str]:
    saved_paths = []
    for file in files:
        if file.filename:
            filename_seguro = file.filename.replace(' ', '_').replace('/', '_')
            file_path = os.path.join(UPLOAD_DIR, filename_seguro)
            
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
            
            saved_paths.append(f"/static/uploads/{filename_seguro}") 
    return saved_paths

def check_admin(request: Request):
    token = request.cookies.get("access_token")
    
    if not token:
        raise HTTPException(status_code=status.HTTP_307_TEMPORARY_REDIRECT, headers={"Location": "/login"})
    
    username = decode_access_token(token)
    
    if username is None:
        raise HTTPException(status_code=status.HTTP_307_TEMPORARY_REDIRECT, headers={"Location": "/logout"})
    
    return username

# --- FUNÇÕES AUXILIARES DE CONVERSÃO ---

def imovel_to_dict(imovel):
    if not imovel: return None
    
    lugar_nome = imovel.lugar.nome if imovel.lugar else "Local não definido"
    
    lista_fotos = imovel.fotos.split(",") if imovel.fotos else []
    lista_fotos = [foto.strip() for foto in lista_fotos if foto.strip()]
    
    foto_capa = lista_fotos[0] if lista_fotos else "/static/uploads/placeholder.png"
    
    return {
        "id": imovel.id, "titulo": imovel.titulo, "descricao": imovel.descricao,
        "preco": imovel.preco, "bairro": lugar_nome, 
        "quartos": imovel.quartos, "banheiros": imovel.banheiros, "area": imovel.area, 
        "whatsapp": imovel.whatsapp, "tipo": imovel.tipo, 
        "lista_fotos": lista_fotos,  
        "foto_capa": foto_capa
    }

def lugar_to_dict(lugar):
    if not lugar: return None
    return {
        "id": lugar.id,
        "nome": lugar.nome,
        "descricao": lugar.descricao,
        "bares_restaurantes": lugar.bares_restaurantes or "",
        "pontos_interesse": lugar.pontos_interesse or "",
        "imagem_principal": lugar.imagem_principal or "",
    }


# =========================================================================
# 4. ROTAS PÚBLICAS
# =========================================================================

@app.get("/", response_class=HTMLResponse)
async def home(request: Request, db: Session = Depends(get_db)):
    imoveis = [imovel_to_dict(i) for i in db.query(ImovelDB).all()]
    hero = db.query(HeroDB).first()
    if not hero: hero = HeroDB()
    
    return templates.TemplateResponse("index.html", {
        "request": request, "imoveis": imoveis, "hero": hero,
        "txt": TRANSLATION_PT_FALLBACK
    })

@app.get("/lugar", response_class=HTMLResponse)
async def list_lugares(request: Request, db: Session = Depends(get_db)):
    lugares_list = db.query(LugarDB).all()
    lugares_data = {l.nome: lugar_to_dict(l) for l in lugares_list}

    return templates.TemplateResponse("local.html", {
        "request": request, 
        "lugares_data": lugares_data,
        "txt": TRANSLATION_PT_FALLBACK
    })

@app.get("/imovel/{id}", response_class=HTMLResponse)
async def detalhes(request: Request, id: int, db: Session = Depends(get_db)):
    imovel = db.query(ImovelDB).filter(ImovelDB.id == id).first()
    if not imovel: 
        raise HTTPException(status_code=404, detail="Imóvel não encontrado")
    
    lugar_data = None
    if imovel.lugar_id:
        lugar_obj = db.query(LugarDB).filter(LugarDB.id == imovel.lugar_id).first()
        if lugar_obj:
            lugar_data = lugar_to_dict(lugar_obj)

    return templates.TemplateResponse("detalhes.html", {
        "request": request, 
        "imovel": imovel_to_dict(imovel),
        "lugar_guia": lugar_data,  
        "txt": TRANSLATION_PT_FALLBACK
    })

@app.post("/contato/enviar")
async def enviar_contato(request: Request, imovel_id: int = Form(...), nome: str = Form(...), email: str = Form(...), telefone: str = Form(...), mensagem: str = Form(...), db: Session = Depends(get_db)):
    imovel = db.query(ImovelDB).filter(ImovelDB.id == imovel_id).first()
    titulo_imovel = imovel.titulo if imovel else "Imóvel desconhecido"

    novo_contato = ContatoDB(imovel_id=imovel_id, imovel_titulo=titulo_imovel, nome=nome, email=email, telefone=telefone, mensagem=mensagem)
    db.add(novo_contato)
    db.commit()
    
    return RedirectResponse(f"/imovel/{imovel_id}", status_code=status.HTTP_303_SEE_OTHER)


# =========================================================================
# 5. ROTAS DE ADMINISTRAÇÃO
# =========================================================================

@app.get("/admin", response_class=HTMLResponse)
async def admin_panel(request: Request, username: str = Depends(check_admin), db: Session = Depends(get_db)):
    imoveis = [imovel_to_dict(i) for i in db.query(ImovelDB).all()]
    lugares = db.query(LugarDB).all()
    contatos = db.query(ContatoDB).order_by(ContatoDB.id.desc()).all()
    hero = db.query(HeroDB).first()
    if not hero: hero = HeroDB() 
    
    return templates.TemplateResponse("admin.html", {
        "request": request, "imoveis": imoveis, "lugares": lugares, 
        "contatos": contatos, "hero": hero, "user": username,
        "txt": TRANSLATION_PT_FALLBACK
    })

# --- ROTAS DE LOGIN/LOGOUT ---

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {
        "request": request,
        "txt": TRANSLATION_PT_FALLBACK
    })

@app.post("/login")
async def login_post(request: Request, username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(AdminUser).filter(AdminUser.username == username).first()

    if user and pwd_context.verify(password, user.hashed_password):
        access_token = create_access_token(data={"sub": user.username})
        
        response = RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)
        response.set_cookie(key="access_token", value=access_token, httponly=True) 
        return response

    return templates.TemplateResponse("login.html", {
        "request": request, 
        "error": "Usuário ou senha inválidos.",
        "txt": TRANSLATION_PT_FALLBACK
    })

@app.get("/logout")
async def logout(request: Request):
    response = RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(key="access_token")
    return response

# --- ROTAS DE EDIÇÃO DA CAPA (HERO) ---
@app.post("/admin/hero")
async def update_hero(titulo: str = Form(...), subtitulo: str = Form(...), file_capa: Optional[UploadFile] = File(None), db: Session = Depends(get_db), username: str = Depends(check_admin)):
    
    hero = db.query(HeroDB).first()
    if not hero:
        hero = HeroDB()
        db.add(hero)
        db.flush() 

    hero.titulo_capa = titulo
    hero.subtitulo_capa = subtitulo
    
    if file_capa and file_capa.filename:
        if file_capa.content_type.startswith(('image/')):
            caminhos = salvar_arquivos([file_capa])
            if caminhos: hero.imagem_capa = caminhos[0]
    
    try:
        db.commit() 
    except Exception as e:
        db.rollback()
        print(f"Erro ao salvar HeroDB: {e}")
    
    return RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)

# --- CRUD DE LUGARES ---
@app.post("/admin/lugar/adicionar")
async def admin_add_lugar(
    nome: str = Form(...), 
    descricao: str = Form(None), 
    bares_restaurantes: str = Form(None), 
    pontos_interesse: str = Form(None),
    file_imagem: Optional[UploadFile] = File(None), 
    db: Session = Depends(get_db), 
    username: str = Depends(check_admin)
):
    
    caminho_imagem = None
    if file_imagem and file_imagem.filename:
        caminhos = salvar_arquivos([file_imagem])
        if caminhos: caminho_imagem = caminhos[0]

    novo_lugar = LugarDB(
        nome=nome, 
        descricao=descricao, 
        bares_restaurantes=bares_restaurantes, 
        pontos_interesse=pontos_interesse,
        imagem_principal=caminho_imagem
    )
    db.add(novo_lugar)
    db.commit()
    return RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/admin/lugar/editar/{id}")
async def admin_edit_lugar(
    id: int, 
    nome: str = Form(...), 
    descricao: str = Form(None), 
    bares_restaurantes: str = Form(None), 
    pontos_interesse: str = Form(None),
    file_imagem: Optional[UploadFile] = File(None), 
    db: Session = Depends(get_db), 
    username: str = Depends(check_admin)
):
    lugar = db.query(LugarDB).filter(LugarDB.id == id).first()
    if lugar:
        lugar.nome = nome
        lugar.descricao = descricao
        lugar.bares_restaurantes = bares_restaurantes
        lugar.pontos_interesse = pontos_interesse
        
        if file_imagem and file_imagem.filename:
             caminhos = salvar_arquivos([file_imagem])
             if caminhos: lugar.imagem_principal = caminhos[0] 

        db.commit()
    return RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/admin/lugar/deletar/{id}")
async def admin_delete_lugar(id: int, db: Session = Depends(get_db), username: str = Depends(check_admin)):
    db.query(LugarDB).filter(LugarDB.id == id).delete()
    db.commit()
    return RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)

# --- ROTA DE ADICIONAR IMÓVEL ---

@app.post("/admin/adicionar")
async def admin_add(
    titulo: str = Form(...), preco: str = Form(...), lugar_id: int = Form(...), descricao: str = Form(...),
    quartos: int = Form(...), banheiros: int = Form(...), area: int = Form(...), whatsapp: str = Form(...), tipo: str = Form(...),
    
    # Define TODOS os campos de arquivo que o seu HTML envia
    fotos_fachada: List[UploadFile] = File(default=[]), 
    fotos_sala: List[UploadFile] = File(default=[]),
    fotos_cozinha: List[UploadFile] = File(default=[]), 
    fotos_quartos: List[UploadFile] = File(default=[]),
    fotos_banheiros: List[UploadFile] = File(default=[]), 
    fotos_lazer: List[UploadFile] = File(default=[]),
    fotos_outros: List[UploadFile] = File(default=[]),
    
    db: Session = Depends(get_db), username: str = Depends(check_admin)
):
    
    # Concatena TODOS os UploadFiles em uma única lista
    lista_arquivos_completos = (
        fotos_fachada + fotos_sala + fotos_cozinha + fotos_quartos +
        fotos_banheiros + fotos_lazer + fotos_outros
    )
    
    todas_fotos = salvar_arquivos(lista_arquivos_completos)
    
    if not todas_fotos: todas_fotos = ["/static/uploads/placeholder.png"]

    novo = ImovelDB(
        titulo=titulo, preco=preco, lugar_id=lugar_id, descricao=descricao, quartos=quartos, banheiros=banheiros,
        area=area, whatsapp=whatsapp, tipo=tipo, fotos=",".join(todas_fotos), bairro=""
    )
    db.add(novo)
    db.commit()
    return RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)

# --- ROTA DE EXCLUSÃO DE FOTO INDIVIDUAL (NOVA) ---

@app.get("/admin/imovel/remover_foto/{id}")
async def admin_remove_foto(id: int, caminho: str, db: Session = Depends(get_db), username: str = Depends(check_admin)):
    
    imovel = db.query(ImovelDB).filter(ImovelDB.id == id).first()
    
    if not imovel:
        raise HTTPException(status_code=404, detail="Imóvel não encontrado.")
    
    # 1. Tenta remover o arquivo físico
    try:
        # caminho_local: converte /static/uploads/... para static/uploads/...
        caminho_local = caminho.lstrip('/')
        if os.path.exists(caminho_local) and caminho_local.startswith('static/uploads/'):
            os.remove(caminho_local)
            print(f"✅ Arquivo removido: {caminho_local}")
        else:
            print(f"⚠️ Aviso: Arquivo não encontrado localmente ou caminho inválido: {caminho_local}")
    except Exception as e:
        print(f"❌ Erro ao deletar arquivo: {e}")
        pass 
    
    # 2. Atualiza a lista no banco de dados (removendo o caminho)
    lista_fotos_antiga = imovel.fotos.split(',')
    # Filtra o caminho exato da foto a ser removida
    lista_fotos_nova = [foto.strip() for foto in lista_fotos_antiga if foto.strip() != caminho.strip()]
    
    imovel.fotos = ','.join(lista_fotos_nova)
    db.commit()
    
    # Redireciona de volta para a página de edição
    return RedirectResponse(f"/admin/imovel/editar/{id}", status_code=status.HTTP_303_SEE_OTHER)


# --- ROTAS DE EDIÇÃO/DELETE DE IMÓVEL ---

@app.get("/admin/imovel/editar/{id}", response_class=HTMLResponse)
async def admin_edit_imovel_form(request: Request, id: int, db: Session = Depends(get_db), username: str = Depends(check_admin)):
    imovel = db.query(ImovelDB).filter(ImovelDB.id == id).first()
    lugares = db.query(LugarDB).all()
    if not imovel:
        return RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)
    
    imovel_dict = imovel_to_dict(imovel)
    
    return templates.TemplateResponse("admin_imovel_editar.html", {
        "request": request, 
        "imovel": imovel_dict, 
        "lugares": lugares, 
        "username": username,
        "txt": TRANSLATION_PT_FALLBACK 
    })

@app.post("/admin/imovel/editar/{id}")
async def admin_edit_imovel_submit(
    id: int, titulo: str = Form(...), preco: str = Form(...), lugar_id: int = Form(...),
    descricao: str = Form(...), quartos: int = Form(...), banheiros: int = Form(...),
    area: int = Form(...), whatsapp: str = Form(...), tipo: str = Form(...),
    db: Session = Depends(get_db), username: str = Depends(check_admin)
):
    imovel = db.query(ImovelDB).filter(ImovelDB.id == id).first()
    if imovel:
        imovel.titulo = titulo
        imovel.preco = preco
        imovel.lugar_id = lugar_id
        imovel.descricao = descricao
        imovel.quartos = quartos
        imovel.banheiros = banheiros
        imovel.area = area
        imovel.whatsapp = whatsapp
        imovel.tipo = tipo
        imovel.bairro = "" 
        
        db.commit()
    return RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/admin/deletar/{id}")
async def admin_delete(id: int, db: Session = Depends(get_db), username: str = Depends(check_admin)):
    db.query(ImovelDB).filter(ImovelDB.id == id).delete()
    db.commit()
    return RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)