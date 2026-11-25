# Auditoria de sobreposições e lacunas após harmonização (Fases 1 e 2)

## Objetivo e limites

Identificar os pares de labels SEG que mais se sobrepõem, distinguir
contensão/limites idênticos/sobreposição parcial, mapear lacunas na
cobertura da Fase 2 e priorizar revisão manual sem assumir que
sobreposições ou lacunas são erros.

Entrada: snapshot `diagnostic_2026_11_16_quarantine`, visão
`diagnostic_2026_11_16_votes_harmonized` e `configs/labels.json`.
As 178 regiões de decisão mapeadas para ENT não contam como SEG.
As 771 pendências permanecem no cenário potencial, com proveniência
inalterada. Quarentena não compõe os spans analisados.

## Executar

```powershell
git fetch origin
git switch analysis/segmentation-overlap-gaps
git pull --ff-only
python -m pytest tests/unit/test_segmentation_overlap_gaps.py -v
python -m pytest -q

python -m legal_nlp.datasets.segmentation_overlap_gaps `
  --snapshot "data/processed/diagnostic_2026_11_16_quarantine" `
  --harmonized "data/processed/diagnostic_2026_11_16_votes_harmonized" `
  --taxonomy "configs/labels.json" `
  --min-gap 150 `
  --top-n 40 `
  --output "data/processed/diagnostic_2026_11_16_votes_harmonized/segmentation_overlap_gaps.json"
```

O relatório não inclui trechos judiciais, apenas IDs, offsets, contagens
e métricas agregadas. Preserva integralmente os arquivos-fonte.

## Resultados prioritários

```powershell
$r = Get-Content "data/processed/diagnostic_2026_11_16_votes_harmonized/segmentation_overlap_gaps.json" -Raw | ConvertFrom-Json

# Matriz de pares de labels sobrepostos: 25 linhas mais frequentes
$r.overlap_matrix |
  Sort-Object pair_count -Descending |
  Select-Object -First 25 phase,label_a,label_b,pair_count,
    documents_with_pair,both_consolidated,at_least_one_pending |
  Format-Table -AutoSize

# Decomposição da geometria por fase
$r.by_phase | ConvertTo-Json -Depth 5

# Maiores lacunas da Fase 2 por acórdão (sem texto)
$r.top_uncovered_intervals |
  Where-Object { $_.phase -eq "phase_2" } |
  Select-Object document_id,start,end,characters,
    @{n="posicao_inicio_pct";e={[math]::Round(100*$_.relative_start,1)}} |
  Format-Table -AutoSize

# Documentos mais descobertos da Fase 2
$r.all_document_metrics |
  Where-Object { $_.phase -eq "phase_2" } |
  Sort-Object uncovered_fraction -Descending |
  Select-Object -First 15 document_id,seg_spans,pending_seg_spans,
    uncovered_characters,uncovered_gaps_total,longest_uncovered_gap,
    @{n="pct_sem_SEG";e={[math]::Round(100*$_.uncovered_fraction,1)}} |
  Format-Table -AutoSize
```

## Interpretação

- `pair_count` conta **pares de regiões distintas**, não erros. Uma
  mesma região pode produzir vários pares.
- `both_consolidated` e `at_least_one_pending` qualificam os pares;
  consolidação técnica não é necessariamente gold formal.
- `strict_containment` é uma região integralmente dentro de outra,
  sem os mesmos limites; `identical` é coincidência de offsets,
  `partial_overlap` é interseção sem contenção.
- `overlap_characters_pairwise_sum` **não** é união de caracteres:
  múltiplos pares podem contabilizar os mesmos caracteres.
- `top_uncovered_intervals` ordena lacunas de ambas as fases; com
  `--top-n 40` pode haver menos de 40 lacunas da Fase 2. Para
  varrer todas as lacunas, aumente `--top-n` e mantenha o filtro.
- O relatório `all_document_metrics` e os intervalos `[start,end)`
  permitem inspeção posterior no texto original local, sem publicar
  textos judiciais no GitHub.
- Ausência de SEG não implica necessariamente anotação faltante; depende
  do protocolo e de quais seções se esperava cobrir.
- A comparação não resolve automaticamente os conflitos para BILOU,
  nem determina uma arquitetura antes da adjudicação.
