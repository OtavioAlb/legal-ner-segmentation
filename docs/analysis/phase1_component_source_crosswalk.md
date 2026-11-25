# Fase 1 — cruzamento das famílias SEG com anotações-fonte verificadas

A cadeia original **já foi verificada com os arquivos efetivamente utilizados na ingestão**:

- `data/raw/phase_1/dados.csv` (SHA-256 = `5711e6fb2776afc5b30d1f94087e4ba4dd079b8e25252c2fb7a8c2942018e498`)
- `data/raw/phase_1/spans_consolidados_agrupado_atual.csv` (SHA-256 = `bcf0d56410d74a8f21917f67a97dee45e7df98ed936033b79af1cd7caffeb92b`)

A auditoria de rastreabilidade anterior confirmou **2.991 spans lógicos,
1.133 SEG antes da harmonização e 5.065 anotações-fonte**, incluindo
5.061 selecionadas a partir de campos de avaliação `reviewed_final`.
**Isso não prova que o arquivo de entrada de anotações seja a exportação
primária do Doccano:** seu nome indica possível consolidação anterior.

Este módulo reexecuta a verificação integral dos hashes originais e
reconstrói todas as famílias de sobreposição de mesma label na visão
harmonizada (não apenas as primeiras 100 da fila). Para cada região,
associa as linhas de origem, seus IDs, seleção do avaliador, offsets e
labels originais/revisados. Resume o total de anotações-fonte distintas
presentes nos componentes e entrega uma fila estratificada por acórdão.

A diferença entre `reviewed_final` e `original_confirmed_by_reviewers`
não deve ser interpretada como consenso ou alterações efetivas. O código
conta separadamente quando offsets/labels originais diferem dos revisados.

## Comandos PowerShell

```powershell
git fetch origin
git switch audit/phase1-component-source-crosswalk
git pull --ff-only

python -m pytest tests/unit/test_phase1_component_source_crosswalk.py -v
python -m pytest -q

python -m legal_nlp.datasets.phase1_component_source_crosswalk `
  --raw-texts "data/raw/phase_1/dados.csv" `
  --raw-annotations "data/raw/phase_1/spans_consolidados_agrupado_atual.csv" `
  --ingested "data/interim/phase_1" `
  --sanitized "data/interim/phase_1/sanitized" `
  --logical "data/interim/phase_1/logical_spans" `
  --document-spans "data/interim/phase_1/document_dataset/document_spans.jsonl" `
  --snapshot "data/processed/diagnostic_2026_11_16_quarantine" `
  --harmonized "data/processed/diagnostic_2026_11_16_votes_harmonized" `
  --taxonomy "configs/labels.json" `
  --near-tolerance 5 `
  --max-groups 100 `
  --max-per-document 4 `
  --output "data/processed/diagnostic_2026_11_16_votes_harmonized/phase1_component_source_crosswalk.json"
```

## Resultado agregado

```powershell
$r = Get-Content "data/processed/diagnostic_2026_11_16_votes_harmonized/phase1_component_source_crosswalk.json" -Raw | ConvertFrom-Json
$r.by_phase | ConvertTo-Json -Depth 5

$r.review_queue |
  Select-Object -First 25 document_id,label,number_of_regions,
    source_annotation_count,reviewed_final_source_rows,
    source_offset_revised_different,source_label_revised_different,
    near_boundary_pairs,strict_containment_pairs |
  Format-Table -AutoSize
```

Para conferir a proveniência de uma família selecionada **apenas localmente**:

```powershell
$r.review_queue[0].source_rows |
  Select-Object logical_span_id,annotation_id,source_row,
    selection_status,original_start,original_end,revised_start,revised_end |
  Format-Table -AutoSize
```

Não compartilhe `source_rows`, CSVs ou artefatos locais em repositórios
públicos. IDs/offsets de decisões e anotações devem permanecer no ambiente
controlado; o terminal inicial exibe apenas os totais.

A concordância real entre diferentes anotadores ainda exige conferir a
história anterior à geração do arquivo
`spans_consolidados_agrupado_atual.csv`. Esta etapa detecta quantas
anotações selecionadas contribuíram para cada família, mas **não**
adjudica spans nem decide quais limites são corretos.
