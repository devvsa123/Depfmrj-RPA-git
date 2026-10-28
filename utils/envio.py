"""
Envio das planilhas para a nuvem.

- GitHub: grava no repositório PRIVADO de armazenamento (GITHUB_STORAGE_REPO). Cada envio substitui a versão
  anterior sem guardar histórico (commit sem pai + atualização forçada da branch), para o repositório não
  crescer 10 MB a cada ciclo. Junto vai o "atualizado.json" com a hora de cada arquivo.
- Vercel Blob: o envio de antes. Agora só envia quando o arquivo mudou desde o último envio, porque cada
  envio gasta uma "operação avançada" da cota mensal do Blob.

Os dois só enviam o que mudou: arquivo igual ao último não gasta nada.
"""
import base64
import hashlib
import json
import os
from datetime import datetime, timezone

import requests

from config.settings import (
    GITHUB_API_URL,
    GITHUB_STORAGE_BRANCH,
    GITHUB_STORAGE_REPO,
    GITHUB_STORAGE_TOKEN,
    PASTA_RAIZ,
    VERCEL_BLOB_TOKEN,
    VERIFICAR_SSL,
    proxies_envio,
)
from utils.logger import registrar_log

ARQUIVO_META = "atualizado.json"
ARQUIVO_ULTIMOS_ENVIOS_VERCEL = os.path.join(PASTA_RAIZ, ".ultimos_envios_vercel.json")


class ErroEnvio(Exception):
    pass


def enviar(arquivos, destinos, origem):
    """
    Envia {nome_no_destino: caminho_local} para cada destino ("github" e/ou "vercel").
    Devolve True só se todos os destinos deram certo.
    """
    ok = True
    for destino in destinos:
        try:
            if destino == "github":
                enviar_github(arquivos, origem)
            elif destino == "vercel":
                enviar_vercel(arquivos, origem)
            else:
                raise ErroEnvio(f"destino desconhecido: {destino}")
        except Exception as e:
            registrar_log(f"  ❌ [{origem}] Falha ao enviar para {destino}: {e}")
            ok = False
    return ok


# ---------------------------------------------------------------- GitHub

def _sha_git(conteudo):
    """Mesmo identificador que o git dá ao arquivo: permite saber se ele já está lá sem baixá-lo."""
    return hashlib.sha1(b"blob %d\0" % len(conteudo) + conteudo).hexdigest()


def _github(metodo, caminho, corpo=None, aceitar=(200, 201)):
    r = requests.request(
        metodo,
        f"{GITHUB_API_URL}/repos/{GITHUB_STORAGE_REPO}{caminho}",
        headers={
            "Authorization": f"Bearer {GITHUB_STORAGE_TOKEN}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        json=corpo,
        proxies=proxies_envio(),
        verify=VERIFICAR_SSL,
        timeout=180,
    )
    if r.status_code not in aceitar:
        raise ErroEnvio(f"GitHub {metodo} {caminho}: {r.status_code} - {r.text[:300]}")
    return r


def _estado_branch():
    """(sha do commit atual, sha da árvore, {arquivo: sha}) da branch; tudo None/vazio se ela ainda não existe."""
    r = _github("GET", f"/git/ref/heads/{GITHUB_STORAGE_BRANCH}", aceitar=(200, 404, 409))
    if r.status_code != 200:  # 404 = branch não existe; 409 = repositório vazio
        return None, None, {}
    commit = r.json()["object"]["sha"]
    arvore = _github("GET", f"/git/commits/{commit}").json()["tree"]["sha"]
    itens = _github("GET", f"/git/trees/{arvore}").json()["tree"]
    return commit, arvore, {i["path"]: i["sha"] for i in itens if i["type"] == "blob"}


def _ler_meta(arquivos_atuais):
    sha = arquivos_atuais.get(ARQUIVO_META)
    if not sha:
        return {}
    try:
        b = _github("GET", f"/git/blobs/{sha}").json()
        return json.loads(base64.b64decode(b["content"]).decode("utf-8"))
    except Exception:
        return {}


def enviar_github(arquivos, origem):
    if not GITHUB_STORAGE_TOKEN:
        raise ErroEnvio("GITHUB_STORAGE_TOKEN não está no .env")

    conteudos = {}
    for nome, caminho in arquivos.items():
        with open(caminho, "rb") as f:
            conteudos[nome] = f.read()

    # Duas tentativas: se outro robô atualizar a branch no meio do envio, refaz em cima da versão dele
    for tentativa in range(2):
        commit_atual, arvore_atual, atuais = _estado_branch()
        mudaram = {n: c for n, c in conteudos.items() if atuais.get(n) != _sha_git(c)}
        if not mudaram:
            registrar_log(f"  ⏭️ [{origem}] GitHub: nada mudou desde o último envio ({', '.join(conteudos)}).")
            return

        agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
        meta = _ler_meta(atuais)
        entradas = []
        for nome, conteudo in mudaram.items():
            blob = _github("POST", "/git/blobs", {"content": base64.b64encode(conteudo).decode("ascii"), "encoding": "base64"}).json()
            entradas.append({"path": nome, "mode": "100644", "type": "blob", "sha": blob["sha"]})
            meta[nome] = {"atualizadoEm": agora, "bytes": len(conteudo), "origem": origem}
        entradas.append({"path": ARQUIVO_META, "mode": "100644", "type": "blob",
                         "content": json.dumps(meta, ensure_ascii=False, indent=2, sort_keys=True)})

        corpo_arvore = {"tree": entradas}
        if arvore_atual:
            corpo_arvore["base_tree"] = arvore_atual  # mantém os arquivos que este robô não mexe
        arvore = _github("POST", "/git/trees", corpo_arvore).json()["sha"]
        # commit SEM pai: a branch passa a ter só esta versão (o histórico não acumula)
        commit = _github("POST", "/git/commits", {
            "message": f"{origem}: {', '.join(mudaram)} ({agora})", "tree": arvore, "parents": [],
        }).json()["sha"]

        # confere se ninguém atualizou a branch enquanto este envio era montado
        commit_agora, _, _ = _estado_branch()
        if commit_agora != commit_atual and tentativa == 0:
            registrar_log(f"  🔁 [{origem}] GitHub: a branch mudou durante o envio; refazendo em cima da versão nova.")
            continue

        if commit_atual:
            _github("PATCH", f"/git/refs/heads/{GITHUB_STORAGE_BRANCH}", {"sha": commit, "force": True})
        else:
            _github("POST", "/git/refs", {"ref": f"refs/heads/{GITHUB_STORAGE_BRANCH}", "sha": commit})
        mb = sum(len(c) for c in mudaram.values()) / 1e6
        registrar_log(f"  ✅ [{origem}] GitHub: enviado {', '.join(mudaram)} ({mb:.1f} MB).")
        return


# ---------------------------------------------------------------- Vercel Blob

def _ler_ultimos_envios():
    try:
        with open(ARQUIVO_ULTIMOS_ENVIOS_VERCEL, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def enviar_vercel(arquivos, origem):
    if not VERCEL_BLOB_TOKEN:
        raise ErroEnvio("VERCEL_BLOB_TOKEN não está no .env")
    ultimos = _ler_ultimos_envios()
    for nome, caminho in arquivos.items():
        with open(caminho, "rb") as f:
            conteudo = f.read()
        hash_atual = hashlib.sha256(conteudo).hexdigest()
        if ultimos.get(nome) == hash_atual:
            registrar_log(f"  ⏭️ [{origem}] Vercel: {nome} igual ao último envio, não reenviado.")
            continue
        resposta = requests.put(
            f"https://blob.vercel-storage.com/{nome}",
            headers={"Authorization": f"Bearer {VERCEL_BLOB_TOKEN}", "x-add-random-suffix": "false"},
            data=conteudo,
            proxies=proxies_envio(),
            timeout=120,
            verify=VERIFICAR_SSL,
        )
        if resposta.status_code != 200:
            raise ErroEnvio(f"Vercel {nome}: {resposta.status_code} - {resposta.text[:300]}")
        ultimos[nome] = hash_atual
        with open(ARQUIVO_ULTIMOS_ENVIOS_VERCEL, "w", encoding="utf-8") as f:
            json.dump(ultimos, f)
        registrar_log(f"  ✅ [{origem}] Vercel: {nome} enviado.")
