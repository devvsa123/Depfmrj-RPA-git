"""
Envio das planilhas para a nuvem.

- GitHub: grava no repositório PRIVADO de armazenamento (GITHUB_STORAGE_REPO). Cada envio substitui a versão
  anterior sem guardar histórico (commit sem pai + atualização forçada da branch), para o repositório não
  crescer 10 MB a cada ciclo. Junto vai o "atualizado.json" com a hora de cada arquivo.
- Vercel Blob: o envio de antes. Agora só envia quando o arquivo mudou desde o último envio, porque cada
  envio gasta uma "operação avançada" da cota mensal do Blob.

Os dois só enviam o que mudou: arquivo igual ao último não gasta nada.

- Par WMS x Singra (pasta GITHUB_PASTA_INTERFACE, padrão "dados_interface"): o WMS é enviado a cada 5 min e o Singra a
  cada ~30 min, e as telas que cruzam os dois (Interface SINGRA x WMS) acusavam divergências que só existiam porque
  o WMS estava mais novo que o Singra. Por isso, quando o Singra COMEÇA a extrair, o robô guarda os SHAs dos arquivos
  do WMS que estão no GitHub (capturar_wms_para_par) e, no commit do Singra, grava na pasta do par o CSV novo junto com
  esses mesmos arquivos do WMS. Não há reenvio de dados: a árvore do commit só aponta para blobs que já existem.
- Um envio ao GitHub por vez nesta máquina (trava de arquivo): os dois robôs gravam na mesma branch.
"""
import base64
import contextlib
import hashlib
import json
import os
import time
from datetime import datetime, timezone

import requests

try:  # trava de arquivo: msvcrt no Windows (onde o robô roda), fcntl no resto
    import msvcrt
except ImportError:  # pragma: no cover - depende do sistema
    msvcrt = None
    import fcntl

from config.settings import (
    GITHUB_API_URL,
    GITHUB_PASTA_INTERFACE,
    GITHUB_PASTA_WMS,
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
ARQUIVO_TRAVA_GITHUB = os.path.join(PASTA_RAIZ, ".envio_github.lock")
# Arquivos do WMS que entram no par da interface (os mesmos que o robô do WMS publica em GITHUB_PASTA_WMS)
ARQUIVOS_WMS = ("planilha_estoque.xls", "controle-estoque.xlsx")


class ErroEnvio(Exception):
    def __init__(self, mensagem, status=None):
        super().__init__(mensagem)
        self.status = status  # código HTTP, quando o erro veio da API do GitHub


def enviar(arquivos, destinos, origem, pasta_github="", par=None):
    """
    Envia {nome_no_destino: caminho_local} para cada destino ("github" e/ou "vercel").
    No GitHub, os arquivos vão para `pasta_github` (vazio = raiz). Devolve True só se todos os destinos deram certo.
    `par` (só o Singra usa): resultado de capturar_wms_para_par(), para gravar o par WMS x Singra no mesmo commit.
    """
    ok = True
    for destino in destinos:
        try:
            if destino == "github":
                enviar_github(arquivos, origem, pasta_github, par)
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
        raise ErroEnvio(f"GitHub {metodo} {caminho}: {r.status_code} - {r.text[:300]}", status=r.status_code)
    return r


def _travar(arq):
    arq.seek(0)
    if msvcrt:
        msvcrt.locking(arq.fileno(), msvcrt.LK_NBLCK, 1)  # OSError se outro processo já travou
    else:
        fcntl.flock(arq, fcntl.LOCK_EX | fcntl.LOCK_NB)  # BlockingIOError (é um OSError) se já travado


def _destravar(arq):
    arq.seek(0)
    if msvcrt:
        msvcrt.locking(arq.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(arq, fcntl.LOCK_UN)


@contextlib.contextmanager
def _trava_envio(espera_max=600, caminho=None):
    """
    Um envio ao GitHub por vez nesta máquina. O WMS e o Singra rodam em processos separados e gravam na mesma
    branch; sem isto, um commit podia sobrescrever o outro (já houve 422 "Reference cannot be updated" no log).
    Quem chega depois espera; passados `espera_max` segundos desiste e o envio fica para o próximo ciclo.
    (Não protege contra gravações de OUTRA máquina: para isso continua a conferência da branch em enviar_github.)
    """
    arq = open(caminho or ARQUIVO_TRAVA_GITHUB, "a+b")
    try:
        if arq.tell() == 0 and os.path.getsize(arq.name) == 0:
            arq.write(b"0")  # o msvcrt trava um byte: o arquivo não pode estar vazio
            arq.flush()
        inicio = time.time()
        while True:
            try:
                _travar(arq)
                break
            except OSError:
                if time.time() - inicio > espera_max:
                    raise ErroEnvio(f"outro envio ao GitHub não terminou em {espera_max} s")
                time.sleep(0.5)
        try:
            yield
        finally:
            _destravar(arq)
    finally:
        arq.close()


def _estado_branch():
    """(sha do commit atual, sha da árvore, {arquivo: sha}) da branch; tudo None/vazio se ela ainda não existe."""
    r = _github("GET", f"/git/ref/heads/{GITHUB_STORAGE_BRANCH}", aceitar=(200, 404, 409))
    if r.status_code != 200:  # 404 = branch não existe; 409 = repositório vazio
        return None, None, {}
    commit = r.json()["object"]["sha"]
    arvore = _github("GET", f"/git/commits/{commit}").json()["tree"]["sha"]
    itens = _github("GET", f"/git/trees/{arvore}?recursive=1").json()["tree"]  # inclui o que está dentro das pastas
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


def capturar_wms_para_par():
    """
    "Fotografa" o WMS que está no GitHub agora: guarda só os SHAs (e a hora de cada arquivo), sem baixar nada.
    O robô do Singra chama isto ANTES de começar a extrair e entrega o resultado a enviar(..., par=...) no fim.
    Devolve None se o par está desligado, não há token ou o WMS ainda não está no GitHub.
    """
    if not GITHUB_PASTA_INTERFACE or not GITHUB_STORAGE_TOKEN:
        return None
    _, _, atuais = _estado_branch()
    meta = _ler_meta(atuais)
    wms = {}
    for nome in ARQUIVOS_WMS:
        sha = atuais.get(f"{GITHUB_PASTA_WMS}/{nome}" if GITHUB_PASTA_WMS else nome)
        if sha:
            info = meta.get(nome, {})
            wms[nome] = {"sha": sha, "atualizadoEm": info.get("atualizadoEm"), "bytes": info.get("bytes")}
    if not wms:
        return None
    return {"capturadoEm": datetime.now(timezone.utc).isoformat(timespec="seconds"), "wms": wms}


def enviar_github(arquivos, origem, pasta="", par=None):
    if not GITHUB_STORAGE_TOKEN:
        raise ErroEnvio("GITHUB_STORAGE_TOKEN (ou GITHUB_TOKEN) não está no .env")
    with _trava_envio():
        _enviar_github(arquivos, origem, pasta, par)


def _enviar_github(arquivos, origem, pasta, par):
    # chave = caminho no repositório (ex.: dados_wms/controle-estoque.xlsx)
    conteudos, nomes = {}, {}
    for nome, caminho in arquivos.items():
        destino = f"{pasta}/{nome}" if pasta else nome
        with open(caminho, "rb") as f:
            conteudos[destino] = f.read()
        nomes[destino] = nome

    incluir_par = bool(par and GITHUB_PASTA_INTERFACE)

    # Se outro robô ou o Controle de Estoque (que grava os JSONs em dados_controle/) atualizar a branch no meio
    # do envio, refaz em cima da versão nova, para não apagar o que foi gravado.
    for tentativa in range(3):
        commit_atual, arvore_atual, atuais = _estado_branch()
        mudaram = {n: c for n, c in conteudos.items() if atuais.get(n) != _sha_git(c)}

        # Par da interface: caminho no repositório -> SHA. O WMS vem do que foi fotografado no início do ciclo
        # (blob que já existe); o CSV do Singra é o que está sendo enviado agora.
        par_shas, par_wms, par_singra = {}, {}, {}
        if incluir_par:
            for nome, info in par["wms"].items():
                par_shas[f"{GITHUB_PASTA_INTERFACE}/{nome}"] = info["sha"]
                par_wms[f"{GITHUB_PASTA_INTERFACE}/{nome}"] = info
            for destino, conteudo in conteudos.items():
                par_shas[f"{GITHUB_PASTA_INTERFACE}/{nomes[destino]}"] = _sha_git(conteudo)
                par_singra[f"{GITHUB_PASTA_INTERFACE}/{nomes[destino]}"] = conteudo
        par_mudou = any(atuais.get(d) != sha for d, sha in par_shas.items())

        if not mudaram and not par_mudou:
            registrar_log(f"  ⏭️ [{origem}] GitHub: nada mudou desde o último envio ({', '.join(conteudos)}).")
            return

        agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
        meta = _ler_meta(atuais)
        entradas = []
        for nome, conteudo in mudaram.items():
            blob = _github("POST", "/git/blobs", {"content": base64.b64encode(conteudo).decode("ascii"), "encoding": "base64"}).json()
            entradas.append({"path": nome, "mode": "100644", "type": "blob", "sha": blob["sha"]})
            meta[nomes[nome]] = {"atualizadoEm": agora, "bytes": len(conteudo), "origem": origem, "caminho": nome}
        if par_mudou:
            for destino, sha in par_shas.items():
                if atuais.get(destino) != sha:
                    entradas.append({"path": destino, "mode": "100644", "type": "blob", "sha": sha})
                if destino in par_wms:  # mesma forma das outras entradas do atualizado.json
                    info = par_wms[destino]
                    meta[destino] = {"atualizadoEm": info.get("atualizadoEm") or par["capturadoEm"], "bytes": info.get("bytes"),
                                     "origem": "WMS", "caminho": destino, "capturadoEm": par["capturadoEm"]}
                else:
                    meta[destino] = {"atualizadoEm": agora, "bytes": len(par_singra[destino]), "origem": origem, "caminho": destino}
        entradas.append({"path": ARQUIVO_META, "mode": "100644", "type": "blob",
                         "content": json.dumps(meta, ensure_ascii=False, indent=2, sort_keys=True)})

        corpo_arvore = {"tree": entradas}
        if arvore_atual:
            corpo_arvore["base_tree"] = arvore_atual  # mantém os arquivos que este robô não mexe
        try:
            arvore = _github("POST", "/git/trees", corpo_arvore).json()["sha"]
        except ErroEnvio as e:
            if e.status == 422 and par_mudou and incluir_par:
                # O WMS fotografado no início do ciclo já não existe no GitHub (limpeza de objetos soltos): não dá para
                # parear. Deixa o par como está (consistente, só mais antigo) e envia o resto normalmente.
                registrar_log(f"  ⚠️ [{origem}] GitHub: o WMS do início do ciclo não está mais disponível; o par da interface "
                              f"não foi atualizado neste ciclo ({e}).")
                incluir_par = False
                continue
            raise
        # commit SEM pai: a branch passa a ter só esta versão (o histórico não acumula)
        mensagem_arquivos = list(mudaram) or [d for d in par_shas if d not in par_wms]
        commit = _github("POST", "/git/commits", {
            "message": f"{origem}: {', '.join(mensagem_arquivos)} ({agora})" + (" + par da interface" if par_mudou else ""),
            "tree": arvore, "parents": [],
        }).json()["sha"]

        # confere se ninguém atualizou a branch enquanto este envio era montado
        commit_agora, _, _ = _estado_branch()
        if commit_agora != commit_atual:
            if tentativa < 2:
                registrar_log(f"  🔁 [{origem}] GitHub: a branch mudou durante o envio; refazendo em cima da versão nova.")
                continue
            raise ErroEnvio("a branch mudou durante o envio 3 vezes seguidas; fica para o próximo ciclo")

        if commit_atual:
            _github("PATCH", f"/git/refs/heads/{GITHUB_STORAGE_BRANCH}", {"sha": commit, "force": True})
        else:
            _github("POST", "/git/refs", {"ref": f"refs/heads/{GITHUB_STORAGE_BRANCH}", "sha": commit})
        if mudaram:
            mb = sum(len(c) for c in mudaram.values()) / 1e6
            registrar_log(f"  ✅ [{origem}] GitHub ({GITHUB_STORAGE_REPO}): enviado {', '.join(mudaram)} ({mb:.1f} MB).")
        else:
            registrar_log(f"  ♻️ [{origem}] GitHub: {', '.join(conteudos)} igual ao último envio.")
        if par_mudou:
            hora = next((i.get("atualizadoEm") for i in par_wms.values() if i.get("atualizadoEm")), None)
            registrar_log(f"  🔗 [{origem}] GitHub: par da interface atualizado em {GITHUB_PASTA_INTERFACE}/ "
                          f"(WMS de {hora or par['capturadoEm']} + {origem} de {agora}).")
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
