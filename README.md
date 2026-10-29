# Depfmrj-RPA-git

Robôs que extraem as planilhas do WMS e do Singra e as publicam para os sistemas do depósito.

> Este repositório é **público**: nada de senhas, tokens, endereços internos ou planilhas aqui.
> Tudo isso fica no arquivo `.env` da máquina do robô (modelo em `.env.example`).

## Robôs

| Arquivo | O que faz |
| --- | --- |
| `main.py` | Ciclo completo a cada 20 min: Singra e, se der certo, WMS |
| `main_wms.py` | Só o WMS, a cada 5 min |
| `main_singra.py` | Só o Singra, a cada 20 min |

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
