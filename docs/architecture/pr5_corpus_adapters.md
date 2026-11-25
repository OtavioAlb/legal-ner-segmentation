# PR 5 — Adaptadores diagnósticos para o corpus canônico

## Objetivo
Começar a interoperabilidade entre a Fase 1 (document_spans.jsonl) e a Fase 2 (auditoria v2) em uma **representação de spans comparável**, preservando estados e proveniência. Esta entrega não congela corpus, não gera folds e **não declara gold**.

## O que foi implementado
- `datasets/corpus_adapters.py::phase1_records`: adapta registros previamente saneados e agrupados da Fase 1, mantendo proveniência e offsets.
- `phase2_records`: adapta regiões originais e propostas novas com estados `consolidated` / `pending_review`. Pares de novas propostas consolidadas são representados **uma vez**, pelo ID canônico.
- `resolve_text`: confronta spans da Fase 2 com o texto imutável e verifica limite e correspondência textual, sem reparo implícito.
- `corpus_summary`: contagem descritiva e marca `training_ready=false` explicitamente.
- `tests/unit/test_corpus_adapters.py`: fixtures sintéticas, classificação de pendências, dupla contagem e conflitos de texto.

## Limites e requisitos
- Somente visão diagnóstica em memória; não produz JSONL persistido, partições, etiquetas BIO/BILOU nem material supervisionado.
- Regiões pendentes da Fase 2 continuam pendentes. Uma concordância estrutural na auditoria não substitui uma etapa formal de aprovação do corpus.
- A Fase 1 só é aceita como entrada por `document_spans.jsonl` produzido após as validações existentes.
- Não reconstruir trechos de revisões aceitas pelo texto do checkbox: validar `start:end` contra o documento original.
- O contrato comum de IDs entre fases, os hashes de documentos, a versão da taxonomia e a vinculação por processo judicial ainda precisam ser resolvidos antes do corpus definitivo.
- As estruturas em `core/contracts.py` não são instanciadas diretamente nesses adaptadores para não descartar registros pendentes ou tecnicamente inválidos no limite de ingestão.

## Critérios de aceite
```powershell
git fetch origin
git switch refactor/corpus-adapters-pr5
git pull --ff-only
python -m pytest tests/unit/test_corpus_adapters.py -v
python -m pytest -q
```

Comparar com a mesma versão dos dados locais: contagens por fase, NER/SEG, original/novo, consolidado/pendente e IDs. Não registrar dados judiciais no Git.

## Próxima entrega
Pipeline versionado para `documents.jsonl`, `annotations.jsonl`, manifesto de hashes e diagnóstico de conflitos, após validação do contrato de identidade entre fases. Splits somente quando o conjunto de documentos/processos e a política de elegibilidade forem fechados.
