# PR 3 — JSONL compartilhado e compatibilidade dos pipelines da Fase 1

## Escopo
Centralizar as rotinas repetidas de serialização JSON Lines encontradas nos pipelines da Fase 1, sem modificar decisões de anotação, lógica de classificação, contagens, IDs, offsets, agrupamentos de spans ou formato persistido.

## Implementação
- `src/legal_nlp/io/jsonl.py`: `read_jsonl()` e `write_jsonl()`.
- `audit.py`, `sanitization.py`, `logical_spans.py`, `document_dataset.py`, `reviewer_priority.py`: aliases legados `_read_jsonl` e `_write_jsonl` apontam para as funções compartilhadas.
- `span_diagnostics.py`: alias legado `_write_jsonl` aponta para o mesmo writer. A leitura inline deste módulo permanece intacta neste PR.
- `tests/unit/test_shared_jsonl.py`: verifica aliases, bytes UTF-8, Unicode, ordenação das chaves, LF, linhas em branco e erro explícito em JSON inválido.

## Contrato de serialização
- Entrada UTF-8 e leitura de linhas não vazias.
- Saída UTF-8, `ensure_ascii=False`, `sort_keys=True`, quebra de linha `\\n`, um objeto por linha.
- Falhas de parse não são suprimidas.
- Não cria diretórios pais implicitamente.
- Nenhum novo formato de dados ou transformação semântica.
- Não faz merge entre o parser de proveniência da Fase 2 e o parser de auditoria v2 neste PR.

## Validação local
```powershell
git fetch origin
git switch refactor/jsonl-io-pr3
git pull --ff-only
python -m pytest tests/unit/test_shared_jsonl.py -v
python -m pytest -q
```

### Regressão sobre dados privados
Usar os **mesmos inputs e configs** antes e depois da refatoração. Reexecutar os pipelines da Fase 1 em pastas distintas e comparar SHA-256 dos arquivos JSONL resultantes, além dos sumários, contagens e decisões.

A saída byte a byte deve permanecer idêntica em JSONL. Não adicionar textos judiciais ou dados pessoais ao Git público.

## Dependências
Branch base: `refactor/phase2-shared-pr2`; pressupõe PR1 e PR2 ainda em revisão. Não fazer merge em `main` sem aprovação.
