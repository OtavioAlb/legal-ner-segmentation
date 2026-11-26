# PR 2 — Extração compartilhada de leitura e decisões da Fase 2

## Alterações
- `io/label_studio.py`: extrai sem modificações semânticas as funções `load`, `annotation`, `extract` da auditoria v2.
- `annotations/identity.py`: extrai `NAMES` e `identity`, preservando substituições Teresa/Tiago.
- `annotations/decisions.py`: extrai `geometry` e `decision`.
- `phase2_audit_v2.py`: reexporta **os mesmos nomes públicos**, mantendo CLI e demais funções.
- `phase2_checkbox_review.py`: passa a depender dos módulos compartilhados, sem importar a auditoria geral.
- `tests/unit/test_phase2_shared_compatibility.py`: verifica compatibilidade de import, parsing, identidade, texto de observações e decisões.

## Delimitação intencional
`phase2_provenance_audit.py` mantém seu próprio parser nesta entrega. A auditoria de proveniência tem contratos e critérios de validação específicos. Unificá-los sem comparar os casos de borda poderia alterar saídas silenciosamente. Esse merge será um PR separado após fixtures de equivalência.

## Critérios de aceite
1. `pytest -q` passa integralmente (incluindo todos os testes legados).
2. `pytest tests/unit/test_phase2_shared_compatibility.py -v` passa.
3. Com os **mesmos três exports**, os resultados da auditoria v2 e da planilha checkbox permanecem idênticos às versões anteriores (contagens, linhas, labels, offsets, status, avaliadores e hashes de entrada).
4. Nenhum dado judicial é commitado; nenhuma alteração de `main`.
5. Não alterar a regra de concordância ou adjudicação nesta etapa.

## Como reproduzir
```powershell
git fetch origin
git switch refactor/phase2-shared-pr2
python -m pip install -e ".[dev]"
python -m pytest tests/unit/test_phase2_shared_compatibility.py -v
python -m pytest -q
```
