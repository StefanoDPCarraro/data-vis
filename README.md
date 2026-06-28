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

Por padrão, os dados grandes não entram no Git. Quem clonar o projeto precisa receber a pasta `data/processed/` por fora para rodar o app diretamente.

Arquivos principais esperados em `data/processed/`:

```text
composicao_distribuidora_ano.parquet
composicao_regiao_ano.parquet
composicao_uf_ano_light.parquet
consumo_mensal_classe.parquet
consumo_regiao_classe.parquet
consumo_uf_classe_light.parquet
dim_distribuidora.parquet
dim_tempo.parquet
samp_long.parquet
```

Tamanho aproximado dos dados locais:

```text
data/processed/*.parquet   159 MB
data/interim/*.parquet     180 MB
data/raw/*.csv             3.6 GB
```

O maior arquivo processado é:

```text
data/processed/samp_long.parquet   155 MB
```

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
