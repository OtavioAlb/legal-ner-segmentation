# PR 4 — Regras funcionais de revisão e adjudicação da Fase 2

## Escopo
Extrair **somente** as regras determinísticas para módulos independentes; manter `phase2_audit_v2.py` e `phase2_checkbox_review.py` com CLI e contratos públicos intactos.

## Módulos
- `annotations/reviews/checkbox.py`: divergência **individual** entre escolha explícita e o span do próprio avaliador; não consulta o outro avaliador.
- `annotations/reviews/geometry.py`: classificação **cruzada** das regiões originais com precedência: substituição pendente > divergência de geometria/ausência > checkbox divergente com geometria igual > concordância original > concordância da avaliação.
- `annotations/reviews/new_regions.py`: classificação de novas propostas com os mesmos status e a mesma ordem de precedência da auditoria legada, sem alterar o algoritmo de consolidação automática nem as identidades de origem.

## Compatibilidade
- `phase2_checkbox_review.divergence_problem` permanece importável e agora aponta diretamente para a função compartilhada.
- `phase2_audit_v2.audit` delega apenas a definição de status/motivo; preserva o agrupamento, a construção de linhas, as contagens, a exportação e a autoria Teresa/Tiago.
- `phase2_provenance_audit.py` segue independente, pois o seu modelo de decisão não é equivalente à auditoria v2 e não deve ser unificado sem uma migração de esquema aprovada.
- Nenhum texto judicial ou JSON real incluído no GitHub.

## Aceite
1. `python -m pytest tests/unit/test_phase2_review_rules.py -v` passa.
2. `python -m pytest -q` passa integralmente.
3. Reexecutar a auditoria e o review de checkbox **sobre os mesmos arquivos** nas branches PR3/PR4 e comparar, após normalização apenas de campos voláteis, todas as linhas e os indicadores, incluindo IDs, labels, offsets, diagnósticos e status.
4. A auditoria completa e as planilhas devem manter as mesmas contagens e classificações para inputs iguais.
5. Não fazer merge em `main` antes da validação dos PRs predecessores.

## Branches
Base: `refactor/jsonl-io-pr3`.
Trabalho: `refactor/phase2-review-rules-pr4`.
