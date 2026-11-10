# Depfmrj-RPA-git

Robôs que extraem as planilhas do WMS e do Singra e as publicam para os sistemas do depósito.

> Este repositório é **público**: nada de senhas, tokens, endereços internos ou planilhas aqui.
> Tudo isso fica no arquivo `.env` da máquina do robô (modelo em `.env.example`).

## Robôs

| Arquivo | O que faz |
| --- | --- |
| `main.py` | Ciclo completo a cada 20 min: Singra e, se der certo, WMS |
| `main_wms.py` | Só o WMS, a cada 5 min |
| `main_singra.py` | Só o Singra, 20 min depois do fim de cada extração (~30 min no total) |

Planilhas geradas:

| Robô | Arquivo | Usado por |
| --- | --- | --- |
| WMS | `controle-estoque.xlsx` (estoque detalhado) | Controle de Estoque |
| WMS | `planilha_estoque.xls` (pedidos / RM) | Controle de Estoque |
| Singra | `planilha_rms_unificada.csv` | Dashboard |

## Para onde vão as planilhas

`DESTINO_WMS` e `DESTINO_SINGRA` no `.env` escolhem o destino de cada robô: `github`, `vercel` ou os dois (`github,vercel`).

- **github**: repositório **privado** `DepfmrjAbastecimento/planilhas` (`GITHUB_STORAGE_REPO`), com as planilhas do WMS em
  `dados_wms/` e a do Singra em `dados_singra/`. Cada envio substitui a versão anterior sem guardar histórico,
  para o repositório não crescer a cada ciclo. O arquivo `atualizado.json` registra a hora de cada planilha.
- **vercel**: Vercel Blob, como antes. Cada envio gasta 1 "operação avançada" da cota mensal (2.000 no plano Hobby).

Nos dois destinos o arquivo só é enviado se mudou desde o último envio.
`HORARIO_EXPEDIENTE` e `SO_DIAS_UTEIS` limitam o horário em que os robôs rodam.

### Par WMS x Singra (`dados_interface/`)

O WMS é enviado a cada 5 min e o Singra a cada ~30 min (20 min de espera **depois** de uma extração que leva ~12 min).
Telas que cruzam os dois sistemas, como a **Interface SINGRA x WMS** do dashboard, mostravam divergências falsas porque o
WMS estava mais novo que o Singra. Por isso o robô do Singra grava, a cada ciclo, o par `dados_interface/`:

| Arquivo | Conteúdo |
| --- | --- |
| `dados_interface/planilha_rms_unificada.csv` | O CSV do Singra deste ciclo |
| `dados_interface/planilha_estoque.xls`, `controle-estoque.xlsx` | O WMS que estava no GitHub **quando o Singra começou a extrair** |

Como funciona: no início do ciclo o robô lê da branch os SHAs dos arquivos do WMS (`capturar_wms_para_par`, não baixa nada).
No commit final, a árvore passa a apontar para esses mesmos blobs dentro de `dados_interface/`, então **não há reenvio de
dados** e o WMS "congelado" sobrevive às sobrescritas de `dados_wms/`. O `atualizado.json` ganha uma entrada por arquivo do par
(`dados_interface/<arquivo>`, no mesmo formato das demais) com a hora real de cada metade.

- O par é atualizado a cada ciclo do Singra, mesmo com o CSV idêntico (o WMS do início do ciclo é mais novo).
- Só vale com `DESTINO_SINGRA` incluindo `github`. `GITHUB_PASTA_INTERFACE` vazio desliga.
- Se o WMS fotografado sumir do GitHub antes do commit (raro), o par fica como estava e o log avisa.

### Um envio por vez

Os robôs do WMS e do Singra são processos separados que gravam na mesma branch. Uma trava de arquivo
(`.envio_github.lock`, na pasta do robô) faz um esperar o outro. Isso só vale para processos na **mesma máquina**; contra
gravações de outras máquinas (ex.: Controle de Estoque) continua a conferência da branch com nova tentativa.

## Testes

```
python -m unittest discover -s tests -v
```

Usam uma API do GitHub simulada em memória: não precisam de rede, token nem `.env`.

## Instalação (Windows)

```
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
playwright install msedge
copy .env.example .env   (e preencha)
python main.py
```

## Token do GitHub

Crie em GitHub → Settings → Developer settings → Personal access tokens → **Fine-grained tokens**:

- Criado logado na conta **DepfmrjAbastecimento**
- Repository access: **Only select repositories** → `planilhas`
- Permissions → Repository permissions → **Contents: Read and write**

Coloque o token em `GITHUB_STORAGE_TOKEN` no `.env` da máquina do robô.
