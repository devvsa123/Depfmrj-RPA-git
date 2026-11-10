"""
Testes do envio ao GitHub (utils/envio.py) contra uma API do GitHub simulada em memória.

Rodar na raiz do repositório:  python -m unittest discover -s tests -v
Não precisa de rede, de token nem do .env.
"""
import base64
import hashlib
import json
import os
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import envio  # noqa: E402


def sha_git(b):
    return hashlib.sha1(b"blob %d\0" % len(b) + b).hexdigest()


class Resposta:
    def __init__(self, status, corpo=None):
        self.status_code = status
        self._corpo = corpo if corpo is not None else {}
        self.text = json.dumps(self._corpo)

    def json(self):
        return self._corpo


class GitHubFalso:
    """Só o que o envio.py usa da API Git Data: blobs, árvores (com base_tree), commits e a ref da branch."""

    def __init__(self):
        self.blobs = {}      # sha -> bytes
        self.arvores = {}    # sha -> {caminho: sha do blob}  (já "achatado", como no recursive=1)
        self.commits = {}    # sha -> sha da árvore
        self.refs = {}       # "main" -> sha do commit
        self.n_commits = 0
        self.gancho_commit = None  # função chamada logo depois de criar um commit (simula outro robô gravando)

    # --- leitura direta para as asserções
    def arquivos(self):
        return dict(self.arvores[self.commits[self.refs["main"]]]) if "main" in self.refs else {}

    def conteudo(self, caminho):
        return self.blobs[self.arquivos()[caminho]]

    def meta(self):
        return json.loads(self.conteudo("atualizado.json").decode("utf-8"))

    def grava_como_outro_robo(self, caminho, conteudo):
        """Atualiza a branch por fora do envio.py (como faz o Controle de Estoque em dados_controle/)."""
        sha = self._novo_blob(conteudo)
        base = self.arquivos()
        base[caminho] = sha
        self._commit_de(base, f"outro robo {self.n_commits}")

    # --- API
    def _novo_blob(self, conteudo):
        sha = sha_git(conteudo)
        self.blobs[sha] = conteudo
        return sha

    def _commit_de(self, arquivos, mensagem):
        arvore = hashlib.sha1(json.dumps(arquivos, sort_keys=True).encode()).hexdigest()
        self.arvores[arvore] = dict(arquivos)
        self.n_commits += 1
        commit = hashlib.sha1(f"{mensagem}|{arvore}|{self.n_commits}".encode()).hexdigest()
        self.commits[commit] = arvore
        self.refs["main"] = commit
        return commit

    def requisicao(self, metodo, url, headers=None, json=None, **kw):
        rota = url.split("/repos/", 1)[1].split("/", 2)[2]  # tira "dono/repo"
        rota = "/" + rota
        corpo = json
        if metodo == "GET" and rota == "/git/ref/heads/main":
            return Resposta(200, {"object": {"sha": self.refs["main"]}}) if "main" in self.refs else Resposta(404)
        if metodo == "GET" and rota.startswith("/git/commits/"):
            return Resposta(200, {"tree": {"sha": self.commits[rota.rsplit("/", 1)[1]]}})
        if metodo == "GET" and rota.startswith("/git/trees/"):
            sha = rota.split("/")[3].split("?")[0]
            return Resposta(200, {"tree": [{"path": p, "type": "blob", "sha": s} for p, s in self.arvores[sha].items()]})
        if metodo == "GET" and rota.startswith("/git/blobs/"):
            conteudo = self.blobs[rota.rsplit("/", 1)[1]]
            return Resposta(200, {"content": base64.b64encode(conteudo).decode(), "encoding": "base64"})
        if metodo == "POST" and rota == "/git/blobs":
            return Resposta(201, {"sha": self._novo_blob(base64.b64decode(corpo["content"]))})
        if metodo == "POST" and rota == "/git/trees":
            base = dict(self.arvores[corpo["base_tree"]]) if corpo.get("base_tree") else {}
            for e in corpo["tree"]:
                if "sha" in e:
                    if e["sha"] not in self.blobs:  # o GitHub responde 422 se a árvore aponta para um objeto que não existe
                        return Resposta(422, {"message": f"tree.sha {e['sha']} does not exist"})
                    base[e["path"]] = e["sha"]
                else:
                    base[e["path"]] = self._novo_blob(e["content"].encode("utf-8"))
            arvore = hashlib.sha1(json_dumps(base).encode()).hexdigest()
            self.arvores[arvore] = base
            return Resposta(201, {"sha": arvore})
        if metodo == "POST" and rota == "/git/commits":
            self.n_commits += 1
            commit = hashlib.sha1(f"{corpo['message']}|{corpo['tree']}|{self.n_commits}".encode()).hexdigest()
            self.commits[commit] = corpo["tree"]
            if self.gancho_commit:
                gancho, self.gancho_commit = self.gancho_commit, None
                gancho()
            return Resposta(201, {"sha": commit})
        if metodo == "PATCH" and rota == "/git/refs/heads/main":
            self.refs["main"] = corpo["sha"]
            return Resposta(200, {})
        if metodo == "POST" and rota == "/git/refs":
            self.refs["main"] = corpo["sha"]
            return Resposta(201, {})
        raise AssertionError(f"rota não simulada: {metodo} {rota}")


def json_dumps(o):
    return json.dumps(o, sort_keys=True)


class RelogioFalso(datetime):
    """datetime.now() avança 5 minutos a cada chamada, para os testes distinguirem 'antes' de 'depois'."""
    _t = datetime(2026, 11, 10, 10, 0, 0, tzinfo=timezone.utc)

    @classmethod
    def now(cls, tz=None):
        cls._t += timedelta(minutes=5)
        return cls._t


class BaseEnvio(unittest.TestCase):
    def setUp(self):
        self.gh = GitHubFalso()
        self.log = []
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        RelogioFalso._t = datetime(2026, 11, 10, 10, 0, 0, tzinfo=timezone.utc)
        patches = [
            mock.patch.object(envio.requests, "request", side_effect=self.gh.requisicao),
            mock.patch.object(envio, "registrar_log", side_effect=self.log.append),
            mock.patch.object(envio, "proxies_envio", return_value={}),
            mock.patch.object(envio, "GITHUB_STORAGE_TOKEN", "token-de-teste"),
            mock.patch.object(envio, "GITHUB_STORAGE_REPO", "dono/planilhas"),
            mock.patch.object(envio, "GITHUB_STORAGE_BRANCH", "main"),
            mock.patch.object(envio, "GITHUB_PASTA_WMS", "dados_wms"),
            mock.patch.object(envio, "GITHUB_PASTA_INTERFACE", "dados_interface"),
            mock.patch.object(envio, "ARQUIVO_TRAVA_GITHUB", os.path.join(self.tmp.name, "trava.lock")),
            mock.patch.object(envio, "datetime", RelogioFalso),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def arquivo(self, nome, conteudo):
        caminho = os.path.join(self.tmp.name, nome)
        with open(caminho, "wb") as f:
            f.write(conteudo)
        return caminho

    def envia_wms(self, versao):
        return envio.enviar(
            {"planilha_estoque.xls": self.arquivo("planilha_estoque.xls", f"wms-estoque-v{versao}".encode()),
             "controle-estoque.xlsx": self.arquivo("controle-estoque.xlsx", f"wms-controle-v{versao}".encode())},
            ["github"], "WMS", "dados_wms")

    def envia_singra(self, csv, par=None):
        return envio.enviar({"planilha_rms_unificada.csv": self.arquivo("planilha_rms_unificada.csv", csv)},
                            ["github"], "SINGRA", "dados_singra", par=par)

    def texto_do_log(self):
        return "\n".join(self.log)


class TestParWmsSingra(BaseEnvio):
    def test_par_usa_o_wms_do_inicio_do_ciclo_e_nao_o_do_fim(self):
        self.envia_wms(1)
        par = envio.capturar_wms_para_par()          # Singra começa a extrair aqui
        self.envia_wms(2)                            # durante a extração o WMS é atualizado duas vezes
        self.envia_wms(3)
        self.assertTrue(self.envia_singra(b"singra-A", par))

        a = self.gh.arquivos()
        self.assertEqual(self.gh.blobs[a["dados_interface/planilha_estoque.xls"]], b"wms-estoque-v1")
        self.assertEqual(self.gh.blobs[a["dados_interface/controle-estoque.xlsx"]], b"wms-controle-v1")
        self.assertEqual(self.gh.blobs[a["dados_interface/planilha_rms_unificada.csv"]], b"singra-A")
        # o WMS "ao vivo" e o CSV do Singra continuam como sempre
        self.assertEqual(self.gh.blobs[a["dados_wms/planilha_estoque.xls"]], b"wms-estoque-v3")
        self.assertEqual(self.gh.blobs[a["dados_singra/planilha_rms_unificada.csv"]], b"singra-A")

    def test_wms_seguinte_nao_mexe_no_par(self):
        self.envia_wms(1)
        par = envio.capturar_wms_para_par()
        self.envia_singra(b"singra-A", par)
        antes = {k: v for k, v in self.gh.arquivos().items() if k.startswith("dados_interface/")}
        self.envia_wms(2)
        self.envia_wms(3)
        depois = {k: v for k, v in self.gh.arquivos().items() if k.startswith("dados_interface/")}
        self.assertEqual(antes, depois)
        self.assertEqual(self.gh.conteudo("dados_wms/planilha_estoque.xls"), b"wms-estoque-v3")

    def test_singra_nao_desfaz_o_wms_ao_vivo(self):
        self.envia_wms(1)
        par = envio.capturar_wms_para_par()
        self.envia_wms(2)
        self.envia_singra(b"singra-A", par)
        # o commit do Singra herdou o WMS mais novo em dados_wms/ (só o par ficou com o v1)
        self.assertEqual(self.gh.conteudo("dados_wms/planilha_estoque.xls"), b"wms-estoque-v2")

    def test_nao_reenvia_dados_do_wms_para_montar_o_par(self):
        self.envia_wms(1)
        par = envio.capturar_wms_para_par()
        self.envia_wms(2)
        n_blobs = len(self.gh.blobs)
        self.envia_singra(b"singra-A", par)
        # só entrou 1 blob novo (o CSV, que também é referenciado pelo par) + o atualizado.json
        self.assertEqual(len(self.gh.blobs) - n_blobs, 2)

    def test_csv_igual_mas_wms_novo_atualiza_so_o_par(self):
        self.envia_wms(1)
        self.envia_singra(b"singra-A", envio.capturar_wms_para_par())
        self.envia_wms(2)
        commits = self.gh.n_commits
        par2 = envio.capturar_wms_para_par()         # próximo ciclo do Singra: CSV idêntico
        self.assertTrue(self.envia_singra(b"singra-A", par2))
        self.assertGreater(self.gh.n_commits, commits, "o par precisa ser atualizado mesmo com o CSV idêntico")
        self.assertEqual(self.gh.conteudo("dados_interface/planilha_estoque.xls"), b"wms-estoque-v2")
        self.assertIn("par da interface atualizado", self.texto_do_log())
        # o CSV não mudou, então a hora dele em dados_singra/ não pode andar
        meta = self.gh.meta()
        self.assertLess(meta["planilha_rms_unificada.csv"]["atualizadoEm"], meta["dados_interface/planilha_rms_unificada.csv"]["atualizadoEm"])

    def test_csv_igual_e_wms_igual_nao_gera_commit(self):
        self.envia_wms(1)
        par = envio.capturar_wms_para_par()
        self.envia_singra(b"singra-A", par)
        commits = self.gh.n_commits
        self.log.clear()
        self.assertTrue(self.envia_singra(b"singra-A", envio.capturar_wms_para_par()))
        self.assertEqual(self.gh.n_commits, commits)
        self.assertIn("nada mudou", self.texto_do_log())

    def test_atualizado_json_do_par(self):
        self.envia_wms(1)
        hora_wms_v1 = self.gh.meta()["planilha_estoque.xls"]["atualizadoEm"]
        par = envio.capturar_wms_para_par()
        self.envia_wms(2)
        self.envia_singra(b"singra-A", par)
        meta = self.gh.meta()
        # entradas antigas intactas e com a mesma forma de sempre
        for nome in ("planilha_estoque.xls", "controle-estoque.xlsx", "planilha_rms_unificada.csv"):
            self.assertEqual(set(meta[nome]), {"atualizadoEm", "bytes", "origem", "caminho"})
        # o par: o WMS tem a hora do arquivo congelado (v1), não a do v2
        p_wms = meta["dados_interface/planilha_estoque.xls"]
        self.assertEqual(p_wms["atualizadoEm"], hora_wms_v1)
        self.assertLess(p_wms["atualizadoEm"], meta["planilha_estoque.xls"]["atualizadoEm"])
        self.assertEqual(p_wms["origem"], "WMS")
        self.assertEqual(p_wms["caminho"], "dados_interface/planilha_estoque.xls")
        p_singra = meta["dados_interface/planilha_rms_unificada.csv"]
        self.assertEqual(p_singra["origem"], "SINGRA")
        self.assertEqual(p_singra["bytes"], len(b"singra-A"))

    def test_wms_congelado_que_sumiu_do_github_mantem_o_par_antigo(self):
        self.envia_wms(1)
        self.envia_singra(b"singra-A", envio.capturar_wms_para_par())
        self.envia_wms(2)
        par = envio.capturar_wms_para_par()
        self.envia_wms(3)
        for sha in par["wms"].values():              # o GitHub limpou os objetos soltos do v2
            self.gh.blobs.pop(sha["sha"], None)
        self.assertTrue(self.envia_singra(b"singra-B", par))
        # o CSV novo foi enviado normalmente; o par ficou inteiro como estava (v1 + singra-A), consistente
        self.assertEqual(self.gh.conteudo("dados_singra/planilha_rms_unificada.csv"), b"singra-B")
        self.assertEqual(self.gh.conteudo("dados_interface/planilha_estoque.xls"), b"wms-estoque-v1")
        self.assertEqual(self.gh.conteudo("dados_interface/planilha_rms_unificada.csv"), b"singra-A")
        self.assertIn("não foi atualizado neste ciclo", self.texto_do_log())

    def test_sem_par_o_singra_funciona_como_antes(self):
        self.envia_wms(1)
        self.assertTrue(self.envia_singra(b"singra-A", None))
        self.assertNotIn("dados_interface/planilha_estoque.xls", self.gh.arquivos())
        self.assertEqual(self.gh.conteudo("dados_singra/planilha_rms_unificada.csv"), b"singra-A")

    def test_par_desligado_por_configuracao(self):
        self.envia_wms(1)
        with mock.patch.object(envio, "GITHUB_PASTA_INTERFACE", ""):
            self.assertIsNone(envio.capturar_wms_para_par())
            self.assertTrue(self.envia_singra(b"singra-A", {"capturadoEm": "x", "wms": {"planilha_estoque.xls": {"sha": "0" * 40}}}))
        self.assertFalse([k for k in self.gh.arquivos() if k.startswith("dados_interface")])

    def test_wms_ainda_nao_esta_no_github(self):
        self.assertIsNone(envio.capturar_wms_para_par())  # repositório vazio

    def test_outros_arquivos_da_branch_sao_preservados(self):
        self.envia_wms(1)
        self.gh.grava_como_outro_robo("dados_controle/estoque.json", b"{}")
        self.envia_singra(b"singra-A", envio.capturar_wms_para_par())
        self.assertEqual(self.gh.conteudo("dados_controle/estoque.json"), b"{}")


class TestCorridaEntreRobos(BaseEnvio):
    def test_branch_mudou_no_meio_do_envio_refaz_em_cima_da_nova(self):
        self.envia_wms(1)
        par = envio.capturar_wms_para_par()
        self.gh.gancho_commit = lambda: self.gh.grava_como_outro_robo("dados_controle/estoque.json", b"novo")
        self.assertTrue(self.envia_singra(b"singra-A", par))
        self.assertIn("a branch mudou durante o envio", self.texto_do_log())
        # nada foi perdido: o que o outro gravou e o que o Singra enviou estão na branch
        self.assertEqual(self.gh.conteudo("dados_controle/estoque.json"), b"novo")
        self.assertEqual(self.gh.conteudo("dados_singra/planilha_rms_unificada.csv"), b"singra-A")
        self.assertEqual(self.gh.conteudo("dados_interface/planilha_estoque.xls"), b"wms-estoque-v1")


class TestTrava(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.caminho = os.path.join(self.tmp.name, "trava.lock")

    def test_segundo_envio_espera_o_primeiro(self):
        dentro = threading.Event()
        liberar = threading.Event()

        def segura():
            with envio._trava_envio(caminho=self.caminho):
                dentro.set()
                liberar.wait(5)

        t = threading.Thread(target=segura)
        t.start()
        self.assertTrue(dentro.wait(5))
        with self.assertRaises(envio.ErroEnvio):      # desiste depois de esperar o limite
            with envio._trava_envio(espera_max=1, caminho=self.caminho):
                self.fail("não podia entrar com o outro envio em andamento")
        liberar.set()
        t.join()
        with envio._trava_envio(espera_max=1, caminho=self.caminho):  # liberada: entra
            pass

    def test_quem_espera_entra_quando_o_primeiro_termina(self):
        ordem = []
        dentro = threading.Event()

        def primeiro():
            with envio._trava_envio(caminho=self.caminho):
                dentro.set()
                threading.Event().wait(1.0)
                ordem.append("primeiro")

        t = threading.Thread(target=primeiro)
        t.start()
        dentro.wait(5)
        with envio._trava_envio(espera_max=10, caminho=self.caminho):
            ordem.append("segundo")
        t.join()
        self.assertEqual(ordem, ["primeiro", "segundo"])


if __name__ == "__main__":
    unittest.main()
