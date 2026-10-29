import os
from dotenv import load_dotenv

# Carrega as variáveis do arquivo .env (que NÃO vai para o GitHub: veja .env.example)
load_dotenv()


def _lista(nome):
    """Lê uma variável com vários valores separados por vírgula."""
    return [v.strip() for v in os.getenv(nome, "").split(",") if v.strip()]


# =========================================================
# DESTINO DAS PLANILHAS
# =========================================================
# Para onde cada robô envia: "github", "vercel" ou "github,vercel".
DESTINO_WMS = _lista("DESTINO_WMS") or ["github"]
DESTINO_SINGRA = _lista("DESTINO_SINGRA") or ["vercel"]

# Repositório PRIVADO que guarda as planilhas (só a versão mais recente, sem histórico)
# Aceita também GITHUB_TOKEN, GITHUB_OWNER + GITHUB_REPO (ou GITHUB_REPO com dono/repositório ou o endereço completo)
GITHUB_STORAGE_TOKEN = (os.getenv("GITHUB_STORAGE_TOKEN") or os.getenv("GITHUB_TOKEN") or "").strip() or None


def _repo_storage():
    bruto = os.getenv("GITHUB_STORAGE_REPO", "")
    if not bruto:
        dono, repo = os.getenv("GITHUB_OWNER", ""), os.getenv("GITHUB_REPO", "")
        bruto = repo if "/" in repo else (f"{dono}/{repo}" if dono and repo else "DepfmrjAbastecimento/planilhas")
    bruto = bruto.strip()
    for prefixo in ("https://github.com/", "http://github.com/"):
        if bruto.lower().startswith(prefixo):
            bruto = bruto[len(prefixo):]
    return bruto.removesuffix(".git").strip("/")


GITHUB_STORAGE_REPO = _repo_storage()
GITHUB_STORAGE_BRANCH = os.getenv("GITHUB_STORAGE_BRANCH") or os.getenv("GITHUB_BRANCH") or "main"
GITHUB_API_URL = os.getenv("GITHUB_API_URL", "https://api.github.com")
# Pasta de cada robô dentro do repositório (vazio = raiz)
GITHUB_PASTA_WMS = os.getenv("GITHUB_PASTA_WMS", "dados_wms").strip("/")
GITHUB_PASTA_SINGRA = os.getenv("GITHUB_PASTA_SINGRA", "dados_singra").strip("/")

# =========================================================
# CONFIGURAÇÕES VERCEL E PROXY
# =========================================================
VERCEL_BLOB_TOKEN = os.getenv("VERCEL_BLOB_TOKEN")
WMS_UPLOAD_URL = os.getenv("WMS_UPLOAD_URL")
PROXY_USER = os.getenv("PROXY_USER")
PROXY_PASS = os.getenv("PROXY_PASS")

# O proxy da rede intercepta o HTTPS; por isso os envios não validam o certificado (como antes).
VERIFICAR_SSL = os.getenv("VERIFICAR_SSL", "0") == "1"


def proxies_envio():
    """Proxy de saída para a internet (lido a cada envio, para pegar credenciais renovadas no .env)."""
    load_dotenv(override=True)
    return {"http": os.getenv("HTTP_PROXY"), "https": os.getenv("HTTPS_PROXY")}


# =========================================================
# CONFIGURAÇÕES DA API DJANGO
# =========================================================
API_BASE_URL = os.getenv("API_BASE_URL")
API_USER = os.getenv("API_USER")
API_PASSWORD = os.getenv("API_PASSWORD")

# =========================================================
# CONFIGURAÇÕES SINGRA
# =========================================================
NIP = os.getenv("SINGRA_NIP")
SENHA_NIP = os.getenv("SINGRA_SENHA")
CAM_SINGRA = os.getenv("SINGRA_CAM")

PROXIES_SINGRA = {
    "http": os.getenv("PROXY_HTTP"),
    "https": os.getenv("PROXY_HTTPS")
}

# Endereços internos dos servidores, separados por vírgula (ficam só no .env)
SERVIDORES_SINGRA = _lista("SINGRA_SERVIDORES")

PASTA_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PASTA_DOWNLOADS = os.path.join(os.path.expanduser('~'), 'Downloads')

# Pasta de rede onde o log também é gravado (opcional)
PASTA_LOGS_REDE = os.getenv("PASTA_LOGS_REDE", "")

# =========================================================
# CONFIGURAÇÕES WMS
# =========================================================
WMS_LOGIN_URL = os.getenv("WMS_LOGIN_URL")
WMS_RELATORIO_URL = os.getenv("WMS_RELATORIO_URL")
WMS_ESTOQUE_DETALHADO = os.getenv("WMS_ESTOQUE_DETALHADO")
USUARIO_WMS = os.getenv("WMS_USUARIO")
SENHA_WMS = os.getenv("WMS_SENHA")
