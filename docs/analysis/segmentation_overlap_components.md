# Grupos de segmentos sobrepostos por acórdão e label

## Problema

A Fase 1 apresenta 1.086 **pares** de regiões SEG com a mesma label sobrepostos,
mas um par não é uma unidade de revisão independente. Uma família de 5 regiões
pode gerar até 10 pares. Este módulo agrega regiões em **componentes conectados**
por sobreposição positiva de offsets, sempre dentro de um único acórdão e label.

Intervalos contíguos sem interseção, por exemplo `[0,5)` e `[5,10)`,
não formam um componente. A relação de sobreposição é transitiva para
fins de agrupamento: A sobrepõe B, B sobrepõe C, mesmo que A não sobreponha C.

## Medidas

- `overlap_components`: famílias independentes por acórdão e label.
- `regions_in_components`: número de spans que participam de famílias.
- `overlapping_pairs_in_components`: valida a contagem anterior de pares
  de **mesma label** (F1 esperada: 1.086; F2: 90).
- `near_boundary_pairs`: ambos os limites diferem em até N caracteres
  (padrão 5); candidatos a revisão de fronteira, **não** duplicatas comprovadas.
- `strict_containment_pairs`, `identical_pairs`,
  `partial_overlap_pairs`: tipos geométricos mutuamente exclusivos.
- `distinct_boundaries`: geometrias diferentes na mesma família.
- `distinct_lineage_fingerprints`: hashes de proveniência distintos,
  sem inferir número de anotadores nem consenso.
- `review_queue`: até 100 famílias por padrão, com no máximo três por
  acórdão, ordenadas em rodadas por documento. A ordenação é diagnóstica.

## Comandos PowerShell

```powershell
git fetch origin
git switch analysis/segmentation-overlap-components
git pull --ff-only
python -m pytest tests/unit/test_segmentation_overlap_components.py -v
python -m pytest -q

python -m legal_nlp.datasets.segmentation_overlap_components `
  --snapshot "data/processed/diagnostic_2026_11_16_quarantine" `
  --harmonized "data/processed/diagnostic_2026_11_16_votes_harmonized" `
  --taxonomy "configs/labels.json" `
  --near-tolerance 5 `
  --max-groups 100 `
  --max-per-document 3 `
  --output "data/processed/diagnostic_2026_11_16_votes_harmonized/segmentation_overlap_components.json"
```

## Consulta 1 — Totais por fase

```powershell
$r = Get-Content "data/processed/diagnostic_2026_11_16_votes_harmonized/segmentation_overlap_components.json" -Raw | ConvertFrom-Json
$r.by_phase | ConvertTo-Json -Depth 5
```

## Consulta 2 — Concentração por label

```powershell
$r.by_label |
  Sort-Object phase, @{Expression="overlapping_pairs";Descending=$true} |
  Select-Object phase,label,components,documents,regions,
    overlapping_pairs,near_boundary_pairs |
  Format-Table -AutoSize
```

## Consulta 3 — Famílias para revisão, distribuídas por acórdão

```powershell
$r.review_queue |
  Where-Object { $_.phase -eq "phase_1" } |
  Select-Object -First 25 document_id,label,number_of_regions,
    distinct_boundaries,near_boundary_pairs,strict_containment_pairs,
    partial_overlap_pairs,overlapping_pairs,
    envelope_start,envelope_end |
  Format-Table -AutoSize
```

## Consulta 4 — Família com o maior número de regiões

```powershell
$g = $r.review_queue |
  Sort-Object number_of_regions -Descending |
  Select-Object -First 1

$g | Select-Object document_id,label,number_of_regions,
  envelope_start,envelope_end | Format-List

$g.regions |
  Select-Object region_id,start,end,length,status,source_status,
    lineage_sha256 |
  Format-Table -AutoSize
```

## Regras de curadoria

Nenhum componente é adjudicado automaticamente. Família com limites quase iguais
não implica repetição de anotação; diferenças de offset podem representar
orientações ou decisões de revisão diferentes. Famílias com contenção podem
ser hierárquicas ou redundantes. O diagnóstico precisa ser confrontado
com as anotações fonte e o protocolo antes de preparar targets.

O módulo não publica textos judiciais, nomes ou emails de anotadores,
não modifica o snapshot, não altera labels nem cria gold/splits.
O relatório local inclui IDs de documentos e região, offsets e fingerprints;
não publicá-lo sem revisão de privacidade.
