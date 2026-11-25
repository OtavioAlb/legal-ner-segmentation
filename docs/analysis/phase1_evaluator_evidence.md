# Evidência avaliativa das sobreposições SEG — Fase 1

## Princípio

O módulo verifica **novamente** os hashes dos CSVs de entrada e toda a
rastreabilidade de `ingestion → sanitization → logical_spans →
document_spans → snapshot → harmonized`, usando o PR #25/#26.
Além disso, **relê cada linha efetiva** do arquivo bruto de anotações
`spans_consolidados_agrupado_atual.csv`, confere todos os campos com
`annotations.jsonl.source_fields`, confere `concorda_*` e
`comentario_*` com `reviewer_opinions`, normaliza votos pela
função original `normalize_review_vote` e reconcilia as contagens.

Não se limita aos 100 grupos da fila: analisa todos os componentes
antes de gerar a amostra estratificada de até 100 grupos.

## Execução local

```powershell
git fetch origin
git switch audit/phase1-evaluator-adjudication
git pull --ff-only
python -m pytest tests/unit/test_phase1_evaluator_evidence.py -v
python -m pytest -q

python -m legal_nlp.datasets.phase1_evaluator_evidence `
  --raw-texts "data/raw/phase_1/dados.csv" `
  --raw-annotations "data/raw/phase_1/spans_consolidados_agrupado_atual.csv" `
  --ingested "data/interim/phase_1" `
  --sanitized "data/interim/phase_1/sanitized" `
  --logical "data/interim/phase_1/logical_spans" `
  --document-spans "data/interim/phase_1/document_dataset/document_spans.jsonl" `
  --snapshot "data/processed/diagnostic_2026_11_16_quarantine" `
  --harmonized "data/processed/diagnostic_2026_11_16_votes_harmonized" `
  --taxonomy "configs/labels.json" `
  --max-groups 100 --max-per-document 4 `
  --output "data/processed/diagnostic_2026_11_16_votes_harmonized/phase1_evaluator_evidence.json"
```

## Resumos a apresentar

```powershell
$r = Get-Content "data/processed/diagnostic_2026_11_16_votes_harmonized/phase1_evaluator_evidence.json" -Raw | ConvertFrom-Json
$r.summary | ConvertTo-Json -Depth 3

$r.review_queue |
  Select-Object -First 25 document_id,label,number_of_regions,
    source_annotation_count,evidence_category,
    @{n="avaliadores_mesmas_alternativas";e={$_.reviewer_aliases_supporting_multiple_geometries.Count}} |
  Format-Table -AutoSize

$r.review_queue |
  Where-Object { $_.document_id -eq "phase_1:phase1:300" -and $_.label -eq "SEG_RELATORIO" } |
  ForEach-Object { $_.candidates } |
  Select-Object logical_span_id,start,end,source_annotation_count,
    distinct_reviewers_agreeing,distinct_reviewers_disagreeing,
    reviewer_disagreement_on_same_geometry |
  Format-Table -AutoSize
```

## Interpretação dos indicadores

- `families_with_same_reviewer_supporting_alternatives` é a contagem de
  famílias em que um mesmo avaliador marcou **Sim** em mais de uma
  geometria lógica distinta. Isso **não comprova** contradição: as
  regiões podem representar subtrechos igualmente legítimos.
- `families_with_competing_positive_geometry` indica múltiplos
  limites distintos que receberam pelo menos um voto `Sim`;
  **não** representa decisão exclusiva.
- `families_with_negative_votes` indica pelo menos um `Não`,
  independentemente de revisão posterior.
- `evidence_category` é diagnóstico, com precedência para o
  caso de um avaliador aprovar múltiplas geometrias; não equivale
  a classificação de erro, consenso ou gold.
- `reviewer_aliases_supporting_multiple_geometries` usa códigos
  `R1`, `R2` **locais a cada família**; não correspondem a
  identidades persistentes entre grupos.
- Os contadores de votos por linhas-fonte podem incluir o mesmo
  avaliador em regiões diferentes ou múltiplas linhas da mesma
  geometria. `distinct_reviewers_agreeing` evita duplicá-los
  dentro de uma geometria, mas isso não transforma os votos em
  uma votação entre propostas mutuamente exclusivas.
- Somente os indicadores `comment_present` são exportados:
  **o conteúdo dos comentários continua nos arquivos originais
  locais**, disponível para revisão manual, sem publicação.
- `reviewed_final` representa a precedência do campo revisado
  no pipeline. Não prova adjudicação formal nem consenso.
- A fonte CSV utilizada é comprovada por SHA-256; sua origem
  anterior à consolidação ainda não foi demonstrada
  independentemente dos exports Doccano.

**Nenhum dado de anotação é corrigido, nenhum alvo gold é escolhido,
e nenhuma tarefa de treinamento é preparada automaticamente.**
