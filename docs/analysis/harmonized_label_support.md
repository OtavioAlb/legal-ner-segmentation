# Auditoria da visão harmonizada: suporte por label

## Objetivo
Comparar as **67 labels da taxonomia** e não só as que tiveram ocorrências,
contando spans consolidados e pendentes no cenário potencial. Nenhum pendente
é promovido a gold, nenhuma label rara é removida e nenhum split é gerado.

O relatório é derivado dos hashes do snapshot e da visão harmonizada
(`annotations_harmonized.jsonl`), portanto a mudança de
`SEG_DECISAO_VOTO_*` da Fase 1 para `ENT_DECISAO_VOTO_*` é refletida
na contagem. A nomenclatura original, texto, status, offsets e proveniência
são validados antes da contagem. Os nove registros normalizados isolados
e as 23 ocorrências da fonte em quarentena não entram nos totais.

## Comandos PowerShell
```powershell
git fetch origin
git switch analysis/harmonized-label-support
git pull --ff-only
python -m pytest tests/unit/test_harmonized_label_support.py -v
python -m pytest -q

python -m legal_nlp.datasets.harmonized_label_support `
  --snapshot "data/processed/diagnostic_2026_11_16_quarantine" `
  --harmonized "data/processed/diagnostic_2026_11_16_votes_harmonized" `
  --taxonomy "configs/labels.json" `
  --output "data/processed/diagnostic_2026_11_16_votes_harmonized/label_support_audit.json"
```

## Exibir frequência em todas as labels
```powershell
$r = Get-Content "data/processed/diagnostic_2026_11_16_votes_harmonized/label_support_audit.json" -Raw | ConvertFrom-Json

$r.labels | Sort-Object task,label |
  Select-Object task,label,total_potential,total_consolidated,total_pending_review,
    documents_with_support_total,phase_presence,descriptive_support_band |
  Format-Table -AutoSize

$r.task_diagnostics | ConvertTo-Json -Depth 6
```

## Comparar fases e pendências
```powershell
$r.labels | Sort-Object task,label |
  Select-Object task,label,
    @{n="F1";e={$_.phase_1.potential}},
    @{n="F2";e={$_.phase_2.potential}},
    @{n="F2_pendente";e={$_.phase_2.pending_review}},
    @{n="F1_docs";e={$_.phase_1.documents_with_support}},
    @{n="F2_docs";e={$_.phase_2.documents_with_support}},
    @{n="F1_10k";e={[math]::Round($_.phase_1.potential_per_10000_characters,2)}},
    @{n="F2_10k";e={[math]::Round($_.phase_2.potential_per_10000_characters,2)}} |
  Format-Table -AutoSize
```

## Interpretação e decisões de modelagem
- `zero_support`: label definida, sem ocorrências **nesta visão**;
  não confundir com label inexistente no Label Studio.
- `1-4`, `5-9`, `10-29`, `30-99`, `100+`: faixas apenas
  descritivas, **não** limiares de exclusão nem garantia de desempenho.
- Presença de uma label em só uma fase é um indicador de revisão de
  orientação anotativa, cobertura e composição documental.
- Suporte por **documento** é fundamental; milhares de spans concentrados
  em um pequeno número de processos não garantem avaliação robusta.
- Baselines NER01/SEG01 com encoder Transformer, classificação BILOU
  derivada de offsets, somente após verificação de sobreposições e de
  agrupamento por processo. Avaliar o processamento de janelas para
  acórdãos longos; não presumir exclusividade de spans.
- NER02/SEG02 podem explorar modelagem direta de spans; NER03/NER04 e
  SEG03 devem ser definidos após diagnósticos das classes e erros dos
  primeiros experimentos.
- Status gold, seleção final de modelos, splits e treinamento permanecem
  bloqueados até adjudicação e aprovação formal.
