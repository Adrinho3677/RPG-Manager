import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
INSTANCE_DIR = os.path.join(BASE_DIR, "instance")


def _flag(name, default):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "sim", "yes", "on")


class Config:
    # Assina os cookies de sessão: quem conhece a chave consegue se passar por
    # qualquer usuário. Com cookies seguros ligados (produção) o app se recusa a
    # subir com esta chave padrão — veja create_app.
    DEFAULT_SECRET_KEY = "troque-esta-chave-em-producao"
    SECRET_KEY = os.environ.get("SECRET_KEY", DEFAULT_SECRET_KEY)
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "sqlite:///" + os.path.join(INSTANCE_DIR, "rpgmanager.db")
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
    JSON_AS_ASCII = False
    MAX_CONTENT_LENGTH = 4 * 1024 * 1024

    # Migrações rodam sozinhas ao iniciar o app, para não precisar abrir um
    # console depois de cada atualização. Desligue com AUTO_MIGRATE=0 se for
    # rodar vários processos web ao mesmo tempo.
    AUTO_MIGRATE = _flag("AUTO_MIGRATE", True)
    MIGRATIONS_DIR = os.path.join(BASE_DIR, "migrations")

    UPLOAD_DIR = os.environ.get("UPLOAD_DIR", os.path.join(INSTANCE_DIR, "uploads"))
    BACKUP_DIR = os.environ.get("BACKUP_DIR", os.path.join(INSTANCE_DIR, "backups"))
    BACKUP_KEEP = int(os.environ.get("BACKUP_KEEP", "14"))

    # Cookies: SameSite=Lax impede que outro site mande o navegador do usuário
    # fazer POST aqui com a sessão dele. Secure exige HTTPS — o PythonAnywhere
    # usa HTTPS, mas http://localhost não, então fica desligado por padrão
    # localmente e deve ser ligado em produção com SECURE_COOKIES=1.
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _flag("SECURE_COOKIES", False)
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_SECURE = _flag("SECURE_COOKIES", False)

    WTF_CSRF_TIME_LIMIT = None  # o token vale enquanto durar a sessão

    # O banco guarda horários em UTC (o servidor do PythonAnywhere roda em UTC).
    # Na hora de mostrar, converte para este fuso.
    TIMEZONE = os.environ.get("TIMEZONE", "America/Sao_Paulo")

    # Atrás de proxy (PythonAnywhere), o IP de verdade vem num cabeçalho. Sem
    # isso todos os visitantes teriam o IP do proxy — e o bloqueio de login por
    # IP travaria o site inteiro. Liga sozinho no PythonAnywhere.
    BEHIND_PROXY = _flag("BEHIND_PROXY", bool(os.environ.get("PYTHONANYWHERE_DOMAIN")))
