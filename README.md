# Visualização ANEEL/SAMP

Dashboard em Streamlit para visualizar consumo de energia elétrica no Brasil com dados ANEEL/SAMP.

## Requisitos

- Python 3.12+
- Ambiente virtual recomendado

## Instalação

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Rodar o app

```bash
.venv/bin/streamlit run app.py
```

Depois abra o endereço mostrado no terminal, geralmente:

```text
http://localhost:8501
```

## Dados necessários

O app usa os arquivos já processados em:

```text
data/processed/
data/external/
```

Os dados brutos em `data/raw/` e os arquivos processados grandes não devem ser enviados ao Git.

## Aviso importante

Para apresentação, use apenas o app. Não rode rebuild pesado antes de apresentar:

```bash
# Evite rodar sem necessidade
.venv/bin/python -m src.data.build_geography --rebuild-regional-aggregates --apply-to-samp-long
```

Esse comando pode ser pesado porque reprocessa o dataset principal.

## Páginas

- Visão Geral
- Série Temporal
- Eventos Históricos
- Composição por Classe
- Comparativo Regional
- Mapa por UF

## Observação metodológica

As visualizações usam `consumo_mwh`. A dimensão geográfica foi completada por curadoria manual pragmática para viabilizar o comparativo regional e o mapa por UF.
