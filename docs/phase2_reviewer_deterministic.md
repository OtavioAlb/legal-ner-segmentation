# Classificação determinística de decisões ausentes — Fase 2

A auditoria considera `(idacordao, region_id)` para comparar cada avaliação ao original, sem inferir correção semântica.

## Execução local (PowerShell com .venv)

```powershell
python -m legal_nlp.phase2_reviewer_deterministic `
  --original "data/raw/phase_2/project-anotation-at-2026-09-23-13-29-8041568a.json" `
  --evaluation-11 "data/raw/phase_2/project-evaluation-1-at-2026-11-09-12-19-aa62bd8c.json" `
  --evaluation-17 "data/raw/phase_2/project-evaluation-2-at-2026-11-09-12-19-cf6d5b27.json" `
  --reviewer-id 10 `
  --output "data/interim/phase_2/teresa_deterministic"
python -m pytest tests/test_phase2_reviewer_deterministic.py -v
```

Se existir decisão explícita, ela prevalece. Na ausência dela: label igual e offsets iguais → `correto_automatico`; label diferente → `incorreto_automatico` (inclusive com offsets diferentes); label igual com offsets diferentes → `limite_impreciso_automatico`. Uma região existente apenas na avaliação é `nova_regiao` (criada manualmente), e a original ausente na avaliação é `nao_avaliada`. Sem campo extra de origem: o sufixo no status já identifica a decisão inferida.

Saídas locais (ignoradas pelo Git): `reviewer_deterministic_decisions.csv` e `reviewer_deterministic_summary.json`. Resumo inclui hashes SHA-256 dos inputs para reprodutibilidade.

## Execução nos exports de 09/11/2026

Os 10 acórdãos associados a `completed_by=10` (Teresa) produziram **350** `correto_automatico`, **0** `incorreto_automatico`, **0** `limite_impreciso_automatico`, **2** `nova_regiao`, **0** `nao_avaliada`. Projeto 11: 189 originais idênticos; projeto 17: 161 originais idênticos e duas regiões novas. Total: 352 registros. Ainda não é consolidação cruzada nem aprovação gold; essa deve ser outra etapa.

Nenhum dado judicial ou CSV com texto deve ser commitado no repositório público.
