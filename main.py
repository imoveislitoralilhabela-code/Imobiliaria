# main.py
import os
import shutil
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Optional
from urllib.parse import quote

from fastapi import (
    FastAPI, Request, Form, Depends,
    HTTPException, status, UploadFile, File
)
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from passlib.context import CryptContext
from jose import jwt, JWTError

from database import (
    Base, engine, SessionLocal,
    HeroDB, LugarDB, ImovelDB, ContatoDB, AdminUser
)

# =========================================================================
# 1. CONFIG (SEGURANÇA / ENV)
# =========================================================================

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

SECRET_KEY = os.getenv("SECRET_KEY", "dev-chave-local-troque")
ALGORITHM = "HS256"

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "123456")
# Se quiser resetar a senha do admin na próxima subida: set RESET_ADMIN_PASSWORD=1
RESET_ADMIN_PASSWORD = os.getenv("RESET_ADMIN_PASSWORD", "0") == "1"

TRANSLATION_PT_FALLBACK = {
    "home": "Início",
    "location": "O Lugar",
    "admin": "Admin",
    "details": "Ver Detalhes",
    "contact": "Contato",
}

BASE_DIR = Path(__file__).resolve().parent


def running_on_vercel() -> bool:
    return os.getenv("VERCEL") == "1"


def running_on_render() -> bool:
    # Render costuma ter RENDER=1 ou RENDER_SERVICE_ID
    return os.getenv("RENDER") == "1" or bool(os.getenv("RENDER_SERVICE_ID"))


# =========================================================================
# 2. UPLOADS (LOCAL x VERCEL x RENDER)
# - Vercel: só permite escrita em /tmp
# - Render: ideal usar Disk persistente em /var/data (se você habilitou Disk)
# =========================================================================

def get_upload_dir() -> Path:
    if running_on_vercel():
        return Path("/tmp/uploads")
    if running_on_render():
        # Se você criou Disk no Render, ele monta geralmente em /var/data
        # (padrão recomendado). Se não existir, cai para /tmp.
        if Path("/var/data").exists():
            return Path("/var/data/uploads")
        return Path("/tmp/uploads")
    # Local
    return BASE_DIR / "static" / "uploads"


UPLOAD_DIR = get_upload_dir()
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Placeholder precisa existir no repo: static/uploads/placeholder.png
PLACEHOLDER = "/static/uploads/placeholder.png"

# =========================================================================
# 3. APP / TEMPLATES / STATIC
# =========================================================================

app = FastAPI()
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# arquivos fixos do repo (css/js/imagens fixas)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

# uploads dinâmicos (Render/Vercel = pasta gravável)
# IMPORTANTE: No template, use as URLs que ficam no banco:
# - Local: /static/uploads/...
# - Vercel/Render: /uploads/...
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")


# =========================================================================
# 4. HELPERS (WHATSAPP / IMAGENS)
# =========================================================================

def build_whatsapp_link(phone: str, text: str) -> str:
    """
    phone: só números com DDI + DDD (ex: 5512991709650)
    """
    phone_digits = "".join([c for c in phone if c.isdigit()])
    return f"https://wa.me/{phone_digits}?text={quote(text)}"


def normalize_image_url(path: Optional[str]) -> str:
    """
    Garante URL válida:
    - Se vazio -> placeholder
    - Se veio sem "/" -> coloca
    - Se estamos em Vercel/Render e no banco ficou /static/uploads/... -> troca pra /uploads/...
    """
    if not path:
        return PLACEHOLDER

    path = path.strip()
    if not path.startswith("/"):
        path = "/" + path

    if (running_on_vercel() or running_on_render()) and path.startswith("/static/uploads/"):
        return path.replace("/static/uploads/", "/uploads/", 1)

    return path


def normalize_csv_images(csv: Optional[str]) -> str:
    if not csv:
        return ""
    parts = [p.strip() for p in csv.split(",") if p.strip()]
    parts = [normalize_image_url(p) for p in parts]
    return ",".join(parts)


# =========================================================================
# 5. DB / AUTH UTILS
# =========================================================================

def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=30)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> Optional[str]:
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


def save_files_return_public_urls(files: List[UploadFile]) -> List[str]:
    """
    - Local: salva em static/uploads e retorna /static/uploads/...
    - Render/Vercel: salva em UPLOAD_DIR e retorna /uploads/...
    """
    saved: List[str] = []

    for f in files:
        if not f or not f.filename:
            continue

        filename = f.filename.replace(" ", "_").replace("/", "_")
        file_path = UPLOAD_DIR / filename

        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(f.file, buffer)

        # URL pública
        if running_on_vercel() or running_on_render():
            saved.append(f"/uploads/{filename}")
        else:
            saved.append(f"/static/uploads/{filename}")

    return saved


def check_admin(request: Request) -> str:
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            headers={"Location": "/login"},
        )

    username = decode_access_token(token)
    if username is None:
        raise HTTPException(
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            headers={"Location": "/logout"},
        )

    return username


def create_or_reset_admin_user(db: Session):
    """
    - Cria admin se não existir
    - Se RESET_ADMIN_PASSWORD=1, reseta a senha do admin
    """
    user = db.query(AdminUser).filter(AdminUser.username == ADMIN_USERNAME).first()
    if (user is None) or RESET_ADMIN_PASSWORD:
        hashed = pwd_context.hash(ADMIN_PASSWORD)
        if user is None:
            user = AdminUser(username=ADMIN_USERNAME, hashed_password=hashed)
            db.add(user)
        else:
            user.hashed_password = hashed
        db.commit()
        print(f"✅ Admin pronto: {ADMIN_USERNAME}")


# =========================================================================
# 6. STARTUP (CRIA TABELAS + ADMIN + HERO INICIAL)
# =========================================================================

@app.on_event("startup")
def on_startup():
    try:
        Base.metadata.create_all(bind=engine)

        with SessionLocal() as db:
            create_or_reset_admin_user(db)

            hero = db.query(HeroDB).first()
            if not hero:
                hero = HeroDB(
                    titulo_capa="Encontre seu Lar",
                    subtitulo_capa="As melhores oportunidades da região",
                    imagem_capa=PLACEHOLDER,  # fica /static/... (ok)
                )
                db.add(hero)
                db.commit()

        print("✅ Startup OK")
        print(f"✅ Upload dir: {UPLOAD_DIR}")
    except Exception as e:
        print("❌ ERRO NO STARTUP:", repr(e))
        raise


# =========================================================================
# 7. CONVERSORES (DADOS -> TEMPLATE)
# =========================================================================

def imovel_to_dict(imovel):
    if not imovel:
        return None

    lugar_nome = imovel.lugar.nome if getattr(imovel, "lugar", None) else "Local não definido"

    fotos_csv = normalize_csv_images(imovel.fotos)
    lista_fotos = [p.strip() for p in fotos_csv.split(",") if p.strip()] if fotos_csv else []
    foto_capa = lista_fotos[0] if lista_fotos else PLACEHOLDER

    whatsapp_text = f"Olá, tenho interesse neste imóvel: {imovel.titulo}."
    whatsapp_url = build_whatsapp_link(imovel.whatsapp or "", whatsapp_text) if imovel.whatsapp else ""

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
        "whatsapp_url": whatsapp_url,
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
# 8. ROTAS PÚBLICAS
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

    return templates.TemplateResponse("detalhes.html", {
        "request": request,
        "imovel": imovel_to_dict(imovel),
        "lugar_guia": lugar_data,
        "txt": TRANSLATION_PT_FALLBACK
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

        novo = ContatoDB(
            imovel_id=imovel_id,
            imovel_titulo=titulo_imovel,
            nome=nome,
            email=email,
            telefone=telefone,
            mensagem=mensagem
        )
        db.add(novo)
        db.commit()

        return RedirectResponse(f"/imovel/{imovel_id}", status_code=status.HTTP_303_SEE_OTHER)

    except Exception as e:
        db.rollback()
        print("❌ ERRO ao salvar contato:", repr(e))
        raise HTTPException(status_code=500, detail="Erro ao enviar contato. Verifique os logs.")


# =========================================================================
# 9. ROTAS ADMIN (PAINEL / LOGIN / LOGOUT)
# =========================================================================

@app.get("/admin", response_class=HTMLResponse)
async def admin_panel(request: Request, username: str = Depends(check_admin), db: Session = Depends(get_db)):
    imoveis = [imovel_to_dict(i) for i in db.query(ImovelDB).all()]
    lugares = db.query(LugarDB).all()
    contatos = db.query(ContatoDB).order_by(ContatoDB.id.desc()).all()
    hero = db.query(HeroDB).first() or HeroDB()
    hero.imagem_capa = normalize_image_url(getattr(hero, "imagem_capa", None))

    # se o template usar direto lugares[x].imagem_principal
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
        access_token = create_access_token({"sub": user.username})
        response = RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)

        # Em HTTPS (Render/Prod), secure=True é o ideal.
        # Se estiver testando local via http, secure=False evita perder cookie.
        secure_cookie = bool(running_on_vercel() or running_on_render())
        response.set_cookie(
            key="access_token",
            value=access_token,
            httponly=True,
            secure=secure_cookie,
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
# 10. ADMIN CRUD (HERO / LUGARES / IMÓVEIS / FOTOS)
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
            caminhos = save_files_return_public_urls([file_capa])
            if caminhos:
                hero.imagem_capa = caminhos[0]

        hero.imagem_capa = normalize_image_url(getattr(hero, "imagem_capa", None))

        db.commit()
        return RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)

    except Exception as e:
        db.rollback()
        print("❌ ERRO /admin/hero:", repr(e))
        raise HTTPException(status_code=500, detail="Erro ao salvar Hero.")


# --- LUGARES ---

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
    if file_imagem and file_imagem.filename and (file_imagem.content_type or "").startswith("image/"):
        caminhos = save_files_return_public_urls([file_imagem])
        if caminhos:
            caminho_imagem = caminhos[0]

    novo = LugarDB(
        nome=nome,
        descricao=descricao,
        bares_restaurantes=bares_restaurantes,
        pontos_interesse=pontos_interesse,
        imagem_principal=caminho_imagem
    )
    db.add(novo)
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

        if file_imagem and file_imagem.filename and (file_imagem.content_type or "").startswith("image/"):
            caminhos = save_files_return_public_urls([file_imagem])
            if caminhos:
                lugar.imagem_principal = caminhos[0]

        db.commit()

    return RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/admin/lugar/deletar/{id}")
async def admin_delete_lugar(id: int, db: Session = Depends(get_db), username: str = Depends(check_admin)):
    db.query(LugarDB).filter(LugarDB.id == id).delete()
    db.commit()
    return RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)


# --- IMÓVEIS: ADICIONAR ---

@app.post("/admin/adicionar")
async def admin_add(
    titulo: str = Form(...),
    preco: str = Form(...),
    lugar_id: int = Form(...),
    descricao: str = Form(...),
    quartos: int = Form(...),
    banheiros: int = Form(...),
    area: int = Form(...),
    whatsapp: str = Form(...),
    tipo: str = Form(...),

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
    lista_arquivos = (
        fotos_fachada + fotos_sala + fotos_cozinha + fotos_quartos +
        fotos_banheiros + fotos_lazer + fotos_outros
    )

    todas_fotos = save_files_return_public_urls(lista_arquivos)
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
    return RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)


# --- REMOVER FOTO INDIVIDUAL ---

@app.get("/admin/imovel/remover_foto/{id}")
async def admin_remove_foto(
    id: int,
    caminho: str,
    db: Session = Depends(get_db),
    username: str = Depends(check_admin)
):
    imovel = db.query(ImovelDB).filter(ImovelDB.id == id).first()
    if not imovel:
        raise HTTPException(status_code=404, detail="Imóvel não encontrado.")

    # Remove do banco
    lista_antiga = [x.strip() for x in (imovel.fotos or "").split(",") if x.strip()]
    lista_nova = [x for x in lista_antiga if x != caminho.strip()]
    imovel.fotos = ",".join(lista_nova)
    db.commit()

    # Tenta remover arquivo físico SOMENTE se for arquivo local de upload
    # /uploads/arquivo.jpg -> UPLOAD_DIR/arquivo.jpg
    try:
        if caminho.startswith("/uploads/"):
            filename = caminho.replace("/uploads/", "", 1)
            file_path = UPLOAD_DIR / filename
            if file_path.exists():
                file_path.unlink()
    except Exception as e:
        print("⚠️ Falha ao remover arquivo físico:", repr(e))

    return RedirectResponse(f"/admin/imovel/editar/{id}", status_code=status.HTTP_303_SEE_OTHER)


# --- FORM DE EDIÇÃO DO IMÓVEL ---

@app.get("/admin/imovel/editar/{id}", response_class=HTMLResponse)
async def admin_edit_imovel_form(
    request: Request,
    id: int,
    db: Session = Depends(get_db),
    username: str = Depends(check_admin)
):
    imovel = db.query(ImovelDB).filter(ImovelDB.id == id).first()
    lugares = db.query(LugarDB).all()

    if not imovel:
        return RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)

    return templates.TemplateResponse("admin_imovel_editar.html", {
        "request": request,
        "imovel": imovel_to_dict(imovel),
        "lugares": lugares,
        "username": username,
        "txt": TRANSLATION_PT_FALLBACK
    })


@app.post("/admin/imovel/editar/{id}")
async def admin_edit_imovel_submit(
    id: int,
    titulo: str = Form(...),
    preco: str = Form(...),
    lugar_id: int = Form(...),
    descricao: str = Form(...),
    quartos: int = Form(...),
    banheiros: int = Form(...),
    area: int = Form(...),
    whatsapp: str = Form(...),
    tipo: str = Form(...),
    db: Session = Depends(get_db),
    username: str = Depends(check_admin)
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
