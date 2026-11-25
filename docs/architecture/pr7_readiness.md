# PR 7 — Auditoria de elegibilidade e vazamento do corpus

## Objetivo
Gerar um relatório de **prontidão**, sem alterar o snapshot diagnóstico criado pelo PR6 e sem construir partições, gold ou treinamento.

## Comando
```powershell
python -m legal_nlp.datasets.readiness `
  --snapshot data/processed/diagnostic_2026_11_16 `
  --output data/processed/diagnostic_2026_11_16/readiness.json
```

O comando pressupõe que o snapshot já foi produzido com os **exports realmente usados**, que os arquivos são locais e que `readiness.json` ainda não existe. O relatório não contém os trechos judiciais.

## Verificações
- Consistência das contagens do manifesto com os JSONL.
- Integridade dos SHA-256 de textos, unicidade de documentos e `idacordao`.
- Integridade `text[start:end]`, offsets, tarefa/rótulo e proveniência por região.
- Contagens de regiões pendentes, consolidadas e classes NER/SEG.
- Documentos sem `process_id` confiável — **`idacordao` não é chave de processo**.
- Presença de limites iguais com rótulos distintos: diagnóstico não destrutivo (não elimina spans multirrótulo).
- Flags `formal_gold_approval=false` e `splits_frozen=false` por design.

## Significado de `training_ready=false`
O snapshot de diagnóstico **não** autoriza supervisão final. Até sem pendências, são necessários:
1. Resolver/adjudicar regiões da Fase 2 e formalizar critérios de aceitação das duas fases.
2. Vincular decisões ao mesmo processo quando possível; tratar grupos ausentes sem afirmar independência processual.
3. Congelar elegibilidade, versão da taxonomia e conjunto de documentos.
4. Selecionar e registrar folds/teste **sem usar informação de desempenho dos modelos**.
5. Emitir posteriormente um artefato separado de corpus gold, com aprovação explícita e schema próprio.

## Limitações
- Esta entrega **não** verifica hashes dos exports históricos, porque somente o manifesto contém essas referências. A verificação dos próprios exports deve acontecer no local de origem.
- Detecção de mesmo texto é exata via SHA-256. Não detecta near-duplicates; análise de similaridade textual e de processo exige etapa própria.
- A política de elegibilidade de regiões ainda não é aplicada: o relatório apenas quantifica estados.
- Mesmo quando `process_id` estiver preenchido, sua origem e legitimidade devem ser verificadas antes de criar os splits.
- Não altera `docs/evaluation_protocol_60.md`, que conserva o desenho experimental planejado; os 60 documentos ainda não são um corpus gold consolidado.

## Testes
```powershell
git fetch origin
git switch refactor/corpus-readiness-pr7
git pull --ff-only
python -m pytest tests/integration/test_corpus_readiness.py -v
python -m pytest -q
```

Comparar contagens do relatório com `dataset_manifest.json` e relatórios anteriores. Nenhum dado judicial deve ser adicionado ao Git.
