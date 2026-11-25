# Inventário inicial de migração

Base de inspeção: branch `feature/phase2-deterministic-provenance-audit`, em 2026-11-25.
Inventário focado nos módulos **inspecionados**; não substitui varredura integral do repositório.

| Código legado | Evidência | Destino proposto | Cuidado |
| --- | --- | --- | --- |
| `ingestion.py` (~472 linhas) | ingestão Fase 1, CSV/XLSX, normalização de IDs | `io/`, `pipelines/phase1_ingestion.py` | não perder fontes inválidas ou correções completas |
| `audit.py` (~333) | auditoria Fase 1 | `annotations/validation.py` | preservar categorias e linhas de revisão |
| `sanitization.py` (~249) | saneamento Fase 1 | `preprocessing/sanitization.py` | não alterar precedência dos avaliadores |
| `logical_spans.py` (~197) | agrupamento lossless | `datasets/logical_spans.py` | não eliminar spans sobrepostos/diferentes labels |
| `document_dataset.py` (~272) | dataset e CV por documento | `datasets/corpus.py`, `datasets/splits.py` | verificar dependência por processo |
| `phase2_provenance_audit.py` (~206) | interpretação própria do export | `io/label_studio.py`, `annotations/provenance.py` | confrontar semânticas antes de unir loaders |
| `phase2_audit_v2.py` (~515) | load, extract, identity, decision, audit, XLSX | `io/` + `annotations/` + `pipelines/` | estado atual de adjudicação é referência |
| `phase2_checkbox_review.py` (~246) | inconsistências individuais + XLSX | `annotations/reviews/checkbox.py` | separar Tiago próprio / Teresa substituída |
| `cli.py` | comando original de ingestão | CLI de compatibilidade, depois subcomandos | manter `legal-nlp-ingest-phase1` |

## Repetições identificadas
- Leitura e escrita de JSONL reproduzidas em `audit.py`, `sanitization.py`, `logical_spans.py` e `document_dataset.py`.
- Carregamento/interpretação do Label Studio em auditorias de proveniência e consolidação.
- Identidade dos avaliadores reutilizada pela planilha de checkbox através de importação de `phase2_audit_v2`.
- Exportação de Excel acoplada às regras de auditoria.

## Critérios concretos de regressão
- Consistência de documentos originais e IDs por projeto; determinismo da ordem.
- Mesmos totais por tarefa (NER/SEG), concordâncias, pendências e novas regiões.
- Mesma classificação e atribuição por região e por avaliador.
- Mesmos spans canônicos e critérios de exclusão.
- Comparar saídas lógicas após normalizar somente campos voláteis e layout, **não** contagens, IDs, labels ou offsets.
- Dados reais não entram nos testes versionados.

## Pendências antes da migração de dados
- Recontar com o export efetivamente escolhido: o último processado nesta pesquisa foi 16/11/2026, mas podem existir exportações mais novas.
- Atualizar `docs/evaluation_protocol_60.md`, que ainda registra Fase 2 como não incorporada.
- Verificar os rótulos efetivos da taxonomia antes de congelar `corpus_v1` (o contrato atual documenta 54 ENT + 13 SEG).
- Auditar processo judicial como unidade de agrupamento e elegibilidade das regiões pendentes.
