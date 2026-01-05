# main.py
import os
import shutil
import smtplib
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import quote
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import FastAPI, Request, Form, Depends, HTTPException, status, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from passlib.context import CryptContext
from jose import jwt, JWTError

from database import Base, engine, SessionLocal, HeroDB, LugarDB, ImovelDB, ContatoDB, AdminUser

# =========================================================================
# 1) CONFIG
# =========================================================================

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

SECRET_KEY = os.getenv("SECRET_KEY", "dev-chave-local-troque-no-render")
ALGORITHM = "HS256"

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "123456")
RESET_ADMIN_PASSWORD = os.getenv("RESET_ADMIN_PASSWORD", "0") == "1"

TRANSLATION_PT_FALLBACK = {
    "home": "Início", "location": "O Lugar", "admin": "Admin",
    "details": "Ver Detalhes", "contact": "Contato"
}

BASE_DIR = Path(__file__).resolve().parent

# =========================================================================
# 2) UPLOADS
# Render (free) não garante persistência de arquivo.
# Mesmo assim, deixo funcionando localmente pra testes.
# =========================================================================
UPLOAD_DIR = BASE_DIR / "static" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# =========================================================================
# 3) APP / TEMPLATES / STATIC
# =========================================================================

app = FastAPI()
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

PLACEHOLDER = "/static/uploads/placeholder.png"  # precisa existir no repo

# =========================================================================
# 4) HELPERS
# =========================================================================

def build_whatsapp_link(phone: str, text: str) -> str:
    """
    phone: só números com DDI + DDD (ex: 5512991709650)
    """
    phone_digits = "".join([c for c in phone if c.isdigit()])
    return f"https://wa.me/{phone_digits}?text={quote(text)}"

def normalize_image_url(path: Optional[str]) -> str:
    if not path:
        return PLACEHOLDER

    path = path.strip()
    if not path.startswith("/"):
        path = "/" + path
    return path

def normalize_csv_images(csv: Optional[str]) -> str:
    if not csv:
        return ""
    parts = [p.strip() for p in csv.split(",") if p.strip()]
    parts = [normalize_image_url(p) for p in parts]
    return ",".join(parts)

def salvar_arquivos(files: List[UploadFile]) -> List[str]:
    """
    Salva em static/uploads e retorna /static/uploads/...
    """
    saved_paths: List[str] = []
    for file in files:
        if file and file.filename:
            filename_seguro = file.filename.replace(" ", "_").replace("/", "_")
            file_path = UPLOAD_DIR / filename_seguro

            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)

            saved_paths.append(f"/static/uploads/{filename_seguro}")
    return saved_paths

# =========================================================================
# 5) AUTH TOKEN
# =========================================================================

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=30)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def decode_access_token(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload.get("sub")
    except JWTError:
        return None

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def check_admin(request: Request):
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=status.HTTP_307_TEMPORARY_REDIRECT,
                            headers={"Location": "/login"})

    username = decode_access_token(token)
    if username is None:
        raise HTTPException(status_code=status.HTTP_307_TEMPORARY_REDIRECT,
                            headers={"Location": "/logout"})
    return username

# =========================================================================
# 6) EMAIL (SMTP)
# =========================================================================

def send_email(to_email: str, subject: str, body: str, cc_email: Optional[str] = None):
    host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_PASS")
    mail_from = os.getenv("MAIL_FROM", user)

    if not user or not password or not mail_from:
        raise RuntimeError("SMTP não configurado. Verifique SMTP_USER/SMTP_PASS/MAIL_FROM no Render.")

    msg = EmailMessage()
    msg["From"] = mail_from
    msg["To"] = to_email
    msg["Subject"] = subject
    if cc_email:
        msg["Cc"] = cc_email
    msg.set_content(body)

    recipients = [to_email] + ([cc_email] if cc_email else [])

    with smtplib.SMTP(host, port) as server:
        server.ehlo()
        server.starttls()
        server.login(user, password)
        server.send_message(msg, from_addr=mail_from, to_addrs=recipients)

# =========================================================================
# 7) CONVERSORES
# =========================================================================

def imovel_to_dict(imovel):
    if not imovel:
        return None

    lugar_nome = imovel.lugar.nome if getattr(imovel, "lugar", None) else "Local não definido"
    fotos_csv = normalize_csv_images(imovel.fotos)
    lista_fotos = [p.strip() for p in fotos_csv.split(",") if p.strip()] if fotos_csv else []
    foto_capa = lista_fotos[0] if lista_fotos else PLACEHOLDER

    return {
        "id": imovel.id,
        "titulo": imovel.titulo,
        "descricao": imovel.descricao,
        "preco": imovel.preco,
        "bairro": lugar_nome,
        "quartos": imovel.quartos,
        "banheiros": imovel.banheiros,
        "area": imovel.area,
        "whatsapp": imovel.whatsapp,
        "tipo": imovel.tipo,
        "lista_fotos": lista_fotos,
        "foto_capa": foto_capa,
    }

def lugar_to_dict(lugar):
    if not lugar:
        return None
    return {
        "id": lugar.id,
        "nome": lugar.nome,
        "descricao": lugar.descricao,
        "bares_restaurantes": lugar.bares_restaurantes or "",
        "pontos_interesse": lugar.pontos_interesse or "",
        "imagem_principal": normalize_image_url(lugar.imagem_principal),
    }

# =========================================================================
# 8) STARTUP (cria tabelas + admin + hero inicial)
# =========================================================================

def create_or_reset_admin_user(db: Session):
    user = db.query(AdminUser).filter(AdminUser.username == ADMIN_USERNAME).first()
    if (user is None) or RESET_ADMIN_PASSWORD:
        hashed_password = pwd_context.hash(ADMIN_PASSWORD)
        if user is None:
            user = AdminUser(username=ADMIN_USERNAME, hashed_password=hashed_password)
            db.add(user)
        else:
            user.hashed_password = hashed_password
        db.commit()
        print(f"✅ Admin pronto: username='{ADMIN_USERNAME}'")

def ensure_hero(db: Session):
    hero = db.query(HeroDB).first()
    if not hero:
        hero = HeroDB(
            titulo_capa="Encontre seu Lar",
            subtitulo_capa="As melhores oportunidades da região",
            imagem_capa=PLACEHOLDER,
        )
        db.add(hero)
        db.commit()
        print("✅ Hero criado com valores padrão")

@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        create_or_reset_admin_user(db)
        ensure_hero(db)

# =========================================================================
# 9) ROTAS PÚBLICAS
# =========================================================================

@app.get("/", response_class=HTMLResponse)
async def home(request: Request, db: Session = Depends(get_db)):
    imoveis = [imovel_to_dict(i) for i in db.query(ImovelDB).all()]
    hero = db.query(HeroDB).first() or HeroDB()
    hero.imagem_capa = normalize_image_url(getattr(hero, "imagem_capa", None))

    return templates.TemplateResponse("index.html", {
        "request": request,
        "imoveis": imoveis,
        "hero": hero,
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

    # sucesso do contato via querystring
    sucesso_contato = request.query_params.get("ok") == "1"
    nome_cliente = request.query_params.get("nome", "")

    imovel_dict = imovel_to_dict(imovel)
    whatsapp_text = f"Olá, tenho interesse no imóvel: {imovel_dict['titulo']} (ID {imovel_dict['id']}). Podemos conversar?"
    whatsapp_link = build_whatsapp_link(imovel_dict.get("whatsapp", ""), whatsapp_text)

    return templates.TemplateResponse("detalhes.html", {
        "request": request,
        "imovel": imovel_dict,
        "lugar_guia": lugar_data,
        "txt": TRANSLATION_PT_FALLBACK,
        "sucesso_contato": sucesso_contato,
        "nome_cliente": nome_cliente,
        "whatsapp_link": whatsapp_link
    })

@app.post("/contato/enviar")
async def enviar_contato(
    request: Request,
    imovel_id: int = Form(...),
    nome: str = Form(...),
    email: str = Form(...),
    telefone: str = Form(...),
    mensagem: str = Form(...),
    db: Session = Depends(get_db)
):
    try:
        imovel = db.query(ImovelDB).filter(ImovelDB.id == imovel_id).first()
        titulo_imovel = imovel.titulo if imovel else "Imóvel desconhecido"

        novo_contato = ContatoDB(
            imovel_id=imovel_id,
            imovel_titulo=titulo_imovel,
            nome=nome,
            email=email,
            telefone=telefone,
            mensagem=mensagem
        )
        db.add(novo_contato)
        db.commit()

        # Email para você + confirmação para o cliente (se SMTP configurado)
        try:
            dono = os.getenv("MAIL_CC", "imoveislitoralilhabela@gmail.com")

            body_admin = f"""Novo contato recebido

Imóvel: {titulo_imovel} (ID {imovel_id})
Nome: {nome}
Email: {email}
Telefone: {telefone}

Mensagem:
{mensagem}
"""
            send_email(to_email=dono, subject=f"📩 Novo contato (Imóvel #{imovel_id})", body=body_admin)

            body_cliente = f"""Olá {nome},

Recebemos sua mensagem com interesse no imóvel:
{titulo_imovel} (ID {imovel_id})

Mensagem enviada:
{mensagem}

Em breve retornaremos por aqui.

Atenciosamente,
Imóveis Litoral Ilhabela
"""
            send_email(to_email=email, subject="✅ Recebemos sua mensagem", body=body_cliente, cc_email=dono)

        except Exception as e:
            # não quebra o fluxo do site
            print("⚠️ Erro ao enviar email (SMTP):", repr(e))

        # volta para detalhes com mensagem de sucesso
        return RedirectResponse(f"/imovel/{imovel_id}?ok=1&nome={quote(nome)}", status_code=status.HTTP_303_SEE_OTHER)

    except Exception as e:
        db.rollback()
        print("❌ ERRO ao salvar contato:", repr(e))
        raise HTTPException(status_code=500, detail="Erro ao enviar contato. Verifique os logs.")

# =========================================================================
# 10) ADMIN
# =========================================================================

@app.get("/admin", response_class=HTMLResponse)
async def admin_panel(request: Request, username: str = Depends(check_admin), db: Session = Depends(get_db)):
    imoveis = [imovel_to_dict(i) for i in db.query(ImovelDB).all()]
    lugares = db.query(LugarDB).all()
    contatos = db.query(ContatoDB).order_by(ContatoDB.id.desc()).all()
    hero = db.query(HeroDB).first() or HeroDB()
    hero.imagem_capa = normalize_image_url(getattr(hero, "imagem_capa", None))

    for l in lugares:
        l.imagem_principal = normalize_image_url(getattr(l, "imagem_principal", None))

    return templates.TemplateResponse("admin.html", {
        "request": request,
        "imoveis": imoveis,
        "lugares": lugares,
        "contatos": contatos,
        "hero": hero,
        "user": username,
        "txt": TRANSLATION_PT_FALLBACK
    })

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "txt": TRANSLATION_PT_FALLBACK})

@app.post("/login")
async def login_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    user = db.query(AdminUser).filter(AdminUser.username == username).first()
    if user and pwd_context.verify(password, user.hashed_password):
        access_token = create_access_token(data={"sub": user.username})
        response = RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)
        response.set_cookie(
            key="access_token",
            value=access_token,
            httponly=True,
            secure=False,  # Render geralmente é https via proxy; se der problema, deixe False
            samesite="lax",
            max_age=60 * 30
        )
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

# =========================================================================
# 11) ADMIN CRUD - HERO
# =========================================================================

@app.post("/admin/hero")
async def update_hero(
    titulo: str = Form(...),
    subtitulo: str = Form(...),
    file_capa: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    username: str = Depends(check_admin)
):
    try:
        hero = db.query(HeroDB).first()
        if not hero:
            hero = HeroDB()
            db.add(hero)
            db.flush()

        hero.titulo_capa = titulo
        hero.subtitulo_capa = subtitulo

        if file_capa and file_capa.filename and (file_capa.content_type or "").startswith("image/"):
            caminhos = salvar_arquivos([file_capa])
            if caminhos:
                hero.imagem_capa = caminhos[0]

        hero.imagem_capa = normalize_image_url(getattr(hero, "imagem_capa", None))
        db.commit()
        return RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)

    except Exception as e:
        db.rollback()
        print("❌ ERRO /admin/hero:", repr(e))
        raise HTTPException(status_code=500, detail="Erro ao salvar Hero.")

# =========================================================================
# 12) ADMIN CRUD - LUGARES
# =========================================================================

@app.post("/admin/lugar/adicionar")
async def admin_add_lugar(
    nome: str = Form(...),
    descricao: str = Form(""),
    bares_restaurantes: str = Form(""),
    pontos_interesse: str = Form(""),
    file_imagem: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    username: str = Depends(check_admin)
):
    try:
        caminho_imagem = None
        if file_imagem and file_imagem.filename and (file_imagem.content_type or "").startswith("image/"):
            caminhos = salvar_arquivos([file_imagem])
            if caminhos:
                caminho_imagem = caminhos[0]

        novo_lugar = LugarDB(
            nome=nome.strip(),
            descricao=descricao,
            bares_restaurantes=bares_restaurantes,
            pontos_interesse=pontos_interesse,
            imagem_principal=caminho_imagem
        )
        db.add(novo_lugar)
        db.commit()
        return RedirectResponse("/admin?tab=lugares&lugar=ok", status_code=status.HTTP_303_SEE_OTHER)
    except Exception as e:
        db.rollback()
        print("❌ ERRO /admin/lugar/adicionar:", repr(e))
        raise HTTPException(status_code=500, detail="Erro ao adicionar lugar.")

@app.post("/admin/lugar/editar/{id}")
async def admin_edit_lugar(
    id: int,
    nome: str = Form(...),
    descricao: str = Form(""),
    bares_restaurantes: str = Form(""),
    pontos_interesse: str = Form(""),
    file_imagem: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    username: str = Depends(check_admin)
):
    try:
        lugar = db.query(LugarDB).filter(LugarDB.id == id).first()
        if not lugar:
            raise HTTPException(status_code=404, detail="Lugar não encontrado")

        lugar.nome = nome.strip()
        lugar.descricao = descricao
        lugar.bares_restaurantes = bares_restaurantes
        lugar.pontos_interesse = pontos_interesse

        if file_imagem and file_imagem.filename and (file_imagem.content_type or "").startswith("image/"):
            caminhos = salvar_arquivos([file_imagem])
            if caminhos:
                lugar.imagem_principal = caminhos[0]

        db.commit()
        return RedirectResponse("/admin?tab=lugares&edit=ok", status_code=status.HTTP_303_SEE_OTHER)
    except Exception as e:
        db.rollback()
        print("❌ ERRO /admin/lugar/editar:", repr(e))
        raise HTTPException(status_code=500, detail="Erro ao editar lugar.")

@app.get("/admin/lugar/deletar/{id}")
async def admin_delete_lugar(
    id: int,
    db: Session = Depends(get_db),
    username: str = Depends(check_admin)
):
    try:
        lugar = db.query(LugarDB).filter(LugarDB.id == id).first()
        if not lugar:
            return RedirectResponse("/admin?tab=lugares&del=notfound", status_code=status.HTTP_303_SEE_OTHER)

        db.delete(lugar)
        db.commit()
        return RedirectResponse("/admin?tab=lugares&del=ok", status_code=status.HTTP_303_SEE_OTHER)
    except Exception as e:
        db.rollback()
        print("❌ ERRO /admin/lugar/deletar:", repr(e))
        raise HTTPException(status_code=500, detail="Erro ao deletar lugar.")

# =========================================================================
# 13) ADMIN - IMÓVEL (adicionar / editar / deletar)
# =========================================================================

@app.post("/admin/adicionar")
async def admin_add(
    titulo: str = Form(...),
    preco: str = Form(...),
    lugar_id: int = Form(...),
    descricao: str = Form(""),
    quartos: int = Form(0),
    banheiros: int = Form(0),
    area: int = Form(0),
    whatsapp: str = Form(...),
    tipo: str = Form("Venda"),

    fotos_fachada: List[UploadFile] = File(default=[]),
    fotos_sala: List[UploadFile] = File(default=[]),
    fotos_cozinha: List[UploadFile] = File(default=[]),
    fotos_quartos: List[UploadFile] = File(default=[]),
    fotos_banheiros: List[UploadFile] = File(default=[]),
    fotos_lazer: List[UploadFile] = File(default=[]),
    fotos_outros: List[UploadFile] = File(default=[]),

    db: Session = Depends(get_db),
    username: str = Depends(check_admin)
):
    try:
        lista_arquivos = (
            fotos_fachada + fotos_sala + fotos_cozinha + fotos_quartos +
            fotos_banheiros + fotos_lazer + fotos_outros
        )
        todas_fotos = salvar_arquivos(lista_arquivos)
        if not todas_fotos:
            todas_fotos = [PLACEHOLDER]

        novo = ImovelDB(
            titulo=titulo,
            preco=preco,
            lugar_id=lugar_id,
            descricao=descricao,
            quartos=quartos,
            banheiros=banheiros,
            area=area,
            whatsapp=whatsapp,
            tipo=tipo,
            fotos=",".join(todas_fotos),
            bairro=""
        )
        db.add(novo)
        db.commit()
        return RedirectResponse("/admin?imovel=ok", status_code=status.HTTP_303_SEE_OTHER)

    except Exception as e:
        db.rollback()
        print("❌ ERRO /admin/adicionar:", repr(e))
        raise HTTPException(status_code=500, detail="Erro ao adicionar imóvel.")

@app.get("/admin/deletar/{id}")
async def admin_delete(
    id: int,
    db: Session = Depends(get_db),
    username: str = Depends(check_admin)
):
    try:
        imovel = db.query(ImovelDB).filter(ImovelDB.id == id).first()
        if not imovel:
            return RedirectResponse("/admin?del=notfound", status_code=status.HTTP_303_SEE_OTHER)
        db.delete(imovel)
        db.commit()
        return RedirectResponse("/admin?del=ok", status_code=status.HTTP_303_SEE_OTHER)
    except Exception as e:
        db.rollback()
        print("❌ ERRO /admin/deletar:", repr(e))
        raise HTTPException(status_code=500, detail="Erro ao deletar imóvel.")

# =========================================================================
# 14) ADMIN - CAIXA DE ENTRADA (APAGAR + RESPONDER)
# =========================================================================

@app.get("/admin/apagar_mensagem/{contato_id}")
async def admin_apagar_mensagem(
    contato_id: int,
    db: Session = Depends(get_db),
    username: str = Depends(check_admin)
):
    try:
        contato = db.query(ContatoDB).filter(ContatoDB.id == contato_id).first()
        if not contato:
            return RedirectResponse("/admin?msg=notfound", status_code=status.HTTP_303_SEE_OTHER)

        db.delete(contato)
        db.commit()
        return RedirectResponse("/admin?msg=delok", status_code=status.HTTP_303_SEE_OTHER)

    except Exception as e:
        db.rollback()
        print("❌ ERRO /admin/apagar_mensagem:", repr(e))
        return RedirectResponse("/admin?msg=delerr", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/admin/contato/responder/{contato_id}")
async def responder_contato(
    contato_id: int,
    assunto: str = Form(...),
    resposta: str = Form(...),
    enviar_copia: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    username: str = Depends(check_admin)
):
    contato = db.query(ContatoDB).filter(ContatoDB.id == contato_id).first()
    if not contato:
        raise HTTPException(status_code=404, detail="Contato não encontrado.")

    cc = os.getenv("MAIL_CC", "imoveislitoralilhabela@gmail.com") if enviar_copia else None

    corpo = f"""Olá {contato.nome},

{resposta}

---
Mensagem original:
{contato.mensagem}

Contato:
Email: {contato.email}
Telefone: {contato.telefone}
Imóvel: {contato.imovel_titulo} (ID {contato.imovel_id})
"""

    try:
        send_email(to_email=contato.email, subject=assunto, body=corpo, cc_email=cc)
        return RedirectResponse("/admin?reply=ok", status_code=status.HTTP_303_SEE_OTHER)
    except Exception as e:
        print("❌ ERRO ao enviar resposta:", repr(e))
        return RedirectResponse("/admin?reply=err", status_code=status.HTTP_303_SEE_OTHER)
