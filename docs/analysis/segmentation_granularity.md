# Auditoria de granularidade da segmentação — Fases 1 e 2

## Objetivo
Verificar se a diferença de densidade SEG entre as fases decorre de
segmentos mais longos, menos fragmentados, diferenças de cobertura ou
sobreposições. Não confundir essas hipóteses com erros comprovados.

**Fonte:** snapshot diagnóstico de 60 documentos + visão harmonizada dos votos,
ambos imutáveis. Inclui `consolidated` e `pending_review` como
**suporte potencial** sem promover pendências a gold. Não conta as nove
linhas normalizadas em quarentena como regiões disponíveis.

O relatório `segmentation_granularity.json` fornece:
- por fase: número de segmentos, comprimento médio/mediano/P90, distribuição
  de segmentos por documento, cobertura dos caracteres pela união dos
  intervalos, componentes contíguos, pares de overlaps iguais, aninhados e
  com labels distintas;
- por label SEG (incluindo labels com 0): frequência consolidada/pendente,
  suporte por acórdão, número de spans por documento com suporte,
  comprimento em caracteres, cobertura do texto, componentes conectados,
  pares de sobreposições dentro da mesma label e razões Fase 2/Fase 1;
- por documento: cobertura, quantidade de spans, pendências, blocos contíguos
  e sobreposições, para identificar casos fora do padrão.

## Execução PowerShell
```powershell
git fetch origin
git switch analysis/segmentation-granularity
git pull --ff-only
python -m pytest tests/unit/test_segmentation_granularity.py -v
python -m pytest -q

python -m legal_nlp.datasets.segmentation_granularity `
  --snapshot "data/processed/diagnostic_2026_11_16_quarantine" `
  --harmonized "data/processed/diagnostic_2026_11_16_votes_harmonized" `
  --taxonomy "configs/labels.json" `
  --output "data/processed/diagnostic_2026_11_16_votes_harmonized/segmentation_granularity.json"
```

## Resumo: comparação por label
```powershell
$r = Get-Content "data/processed/diagnostic_2026_11_16_votes_harmonized/segmentation_granularity.json" -Raw | ConvertFrom-Json

$r.by_label |
  Select-Object label,
    @{n="F1_spans";e={$_.phase_1.occurrences}},
    @{n="F2_spans";e={$_.phase_2.occurrences}},
    @{n="F2_pendentes";e={$_.phase_2.pending}},
    @{n="F1_docs";e={$_.phase_1.documents_with_support}},
    @{n="F2_docs";e={$_.phase_2.documents_with_support}},
    @{n="F1_mediana_caracteres";e={$_.phase_1.span_characters.median}},
    @{n="F2_mediana_caracteres";e={$_.phase_2.span_characters.median}},
    @{n="F1_blocos_por_doc_com_suporte";e={[math]::Round($_.phase_1.spans_per_supporting_document,2)}},
    @{n="F2_blocos_por_doc_com_suporte";e={[math]::Round($_.phase_2.spans_per_supporting_document,2)}},
    @{n="F1_cobertura_pct";e={[math]::Round(100*$_.phase_1.coverage_fraction_of_phase_characters,2)}},
    @{n="F2_cobertura_pct";e={[math]::Round(100*$_.phase_2.coverage_fraction_of_phase_characters,2)}} |
  Format-Table -AutoSize
```

## Resumo por fase
```powershell
$r.by_phase | ConvertTo-Json -Depth 6
```

## Documentos Fase 2 com menor cobertura
```powershell
$r.by_document |
  Where-Object { $_.phase -eq "phase_2" } |
  Sort-Object seg_coverage_fraction |
  Select-Object -First 12 document_id,characters,seg_potential,seg_pending,
    seg_union_components,seg_cross_label_overlapping_pairs,
    @{n="cobertura_pct";e={[math]::Round(100*$_.seg_coverage_fraction,2)}} |
  Format-Table -AutoSize
```

### Limitações metodológicas
- Cobertura de cada label divide seus caracteres únicos pelo total dos
  caracteres da fase. **Não** somar coberturas das labels: spans podem se
  sobrepor; a cobertura total usa a união de todos os intervalos SEG.
- `union_components` mede blocos contíguos, com spans adjacentes
  fundidos; não é um número de seções semanticamente independentes.
- Pares de sobreposição são diagnósticos geométricos: sobreposição pode
  ser legítima, inclusive entre segmentos de categorias diferentes.
- Comprimento, cobertura e suporte não demonstram omissão ou erro de
  anotação isoladamente. Precisamos confrontá-los com o protocolo.
- `SEG_DECISAO_VOTO_*` tem suporte zero na visão derivada porque foi
  mapeada para `ENT_DECISAO_VOTO_*`, não porque foi excluída da
  taxonomia histórica.
- Nenhum split por processo e nenhum gold é produzido por esta etapa.
