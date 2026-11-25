# Auditoria de proveniência para revisão de sobreposições SEG

## Motivação

O diagnóstico da visão harmonizada encontrou na Fase 1 **1.086 pares
de segmentos com a mesma label** e 870 com labels diferentes. Na Fase 2,
encontrou 98.841 caracteres sem SEG (23,3% do texto). Essa auditoria
produz filas de inspeção, não correções automáticas.

## Execução local (PowerShell)

```powershell
git fetch origin
git switch analysis/segmentation-provenance-review
git pull --ff-only
python -m pytest tests/unit/test_segmentation_provenance_review.py -v
python -m pytest -q

python -m legal_nlp.datasets.segmentation_provenance_review `
  --snapshot "data/processed/diagnostic_2026_11_16_quarantine" `
  --harmonized "data/processed/diagnostic_2026_11_16_votes_harmonized" `
  --taxonomy "configs/labels.json" `
  --min-gap 150 `
  --top-pairs 100 `
  --top-gaps 100 `
  --output "data/processed/diagnostic_2026_11_16_votes_harmonized/segmentation_provenance_review.json"
```

O arquivo de saída deve ser tratado como artefato local de auditoria.
Ele contém IDs, offsets, rótulos, status e impressões digitais
SHA-256 dos objetos de proveniência (não os objetos originais, nomes,
comentários ou o conteúdo judicial). **Os hashes não são prova de
anotadores distintos nem de duplicação**, apenas rastros verificáveis
quando comparados à origem local.

## Resultados para enviar ao projeto

```powershell
$r = Get-Content "data/processed/diagnostic_2026_11_16_votes_harmonized/segmentation_provenance_review.json" -Raw | ConvertFrom-Json

$r.phase_metrics | Format-Table -AutoSize

$r.overlap_category_counts |
  Sort-Object phase,category,geometry |
  Format-Table -AutoSize

$r.overlap_review_queue |
  Where-Object { $_.phase -eq "phase_1" -and $_.category -eq "same_label" } |
  Select-Object -First 20 document_id,geometry,overlap_characters,
    @{n="label";e={$_.region_a.label}},
    @{n="regiao_A";e={$_.region_a.region_id}},
    @{n="A_start";e={$_.region_a.start}},
    @{n="A_end";e={$_.region_a.end}},
    @{n="regiao_B";e={$_.region_b.region_id}},
    @{n="B_start";e={$_.region_b.start}},
    @{n="B_end";e={$_.region_b.end}} |
  Format-Table -AutoSize

$r.gap_review_queue |
  Where-Object { $_.phase -eq "phase_2" } |
  Select-Object -First 15 document_id,start,end,characters,
    seg_spans_in_document,seg_pending_in_document |
  Format-Table -AutoSize
```

## Interpretação
- `same_label + identical`: mesmo rótulo e offsets idênticos;
  **não** pressupor duas anotações independentes; conferir proveniência.
- `same_label + strict_containment`: uma região integralmente dentro
  de outra da mesma categoria; avaliar se é redundância ou hierarquia.
- `same_label + partial_overlap`: possível imprecisão de limites,
  mas também pode ser convenção de anotação.
- `cross_label`: avaliar se as seções têm relação hierárquica
  (ex.: provas dentro da fundamentação) antes de excluir overlaps.
- `gap_review_queue`: intervalo sem nenhuma label SEG; lacuna não
  equivale automaticamente a ausência de anotação obrigatória.
- `source_status=consolidated` significa consolidação diagnóstica,
  não aprovação gold.
- A fila é ordenada para priorizar sobreposições da **mesma label da
  Fase 1** e lacunas longas da **Fase 2**.
- `--top-pairs` e `--top-gaps` limitam somente a fila; as contagens
  agregadas cobrem todos os pares e lacunas.

**Não alterar automaticamente** o corpus ou a taxonomia. Após inspeção
manual, registrar decisões de protocolo para orientar BILOU, spans e
modelagem hierárquica.
