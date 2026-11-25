# Visão derivada: harmonização dos rótulos de decisão de voto

## Decisão
Para a modelagem, usar como rótulos canônicos de **extração de resultado decisório**:
- `ENT_DECISAO_VOTO_VENCEDOR`
- `ENT_DECISAO_VOTO_VENCIDO`

As respectivas labels de decisão da Fase 1 são `SEG_DECISAO_VOTO_VENCEDOR` e `SEG_DECISAO_VOTO_VENCIDO`, e passam a ser mapeadas para ENT **somente numa visão derivada**, com rótulo e tarefa originais preservados. Não alterar a anotação dos exports.

As labels `SEG_JURISPRUDENCIA_VOTO_VENCEDOR` e `SEG_JURISPRUDENCIA_VOTO_VENCIDO` permanecem segmentos, sem migração nem remoção, inclusive quando não têm ocorrências na Fase 2.

## Evidência anterior
- Fase 1: 151 SEG_DECISAO_VOTO_VENCEDOR, 27 SEG_DECISAO_VOTO_VENCIDO.
- Fase 2: 85 ENT_DECISAO_VOTO_VENCEDOR, 1 ENT_DECISAO_VOTO_VENCIDO (inclui pendentes).
- Mediana do voto vencedor: 51 caracteres (Fase 1 SEG) vs 43 (Fase 2 ENT).
- Classificação proposta como *extração de trecho decisório*, não como segmentação da estrutura do voto.
- A equivalência semântica foi adotada para planejamento; verificar spans extensos na adjudicação final e não promover pendências como gold.

## Escopo técnico
`datasets.vote_harmonization` produz um dataset diagnóstico derivado, **não altera**
`documents.jsonl`, `annotations.jsonl`, `quarantine.jsonl` nem os exports.
Mantém `source_label`, `source_task`, offsets, texto, status e proveniência em cada
registro. O manifesto retém hashes dos arquivos-fonte, contagens de mudanças
e a informação `training_ready=false`.

A visão não reclassifica automaticamente labels originais da Fase 2, nem
as classes de jurisprudência e fundamentação. A quarentena permanece separada.

## Totais previstos para o snapshot atual
Assumindo que os 178 spans de decisão da Fase 1 sobrevivam sem alterações:
- Fase 1: NER 2.036; SEG 955; total 2.991.
- Fase 2: NER 1.641; SEG 409; total 2.050.
- Total: NER 3.677; SEG 1.364; total 5.041.

As 771 anotações pendentes continuam no cenário **potencial**, e não em gold.
Os nove registros normalizados em quarentena não integram a contagem derivada.

## PowerShell
```powershell
git fetch origin
git switch feat/vote-label-harmonization-view
git pull --ff-only
python -m pytest tests/unit/test_vote_harmonization.py -v
python -m pytest -q

python -m legal_nlp.datasets.vote_harmonization `
  --snapshot "data/processed/diagnostic_2026_11_16_quarantine" `
  --output "data/processed/diagnostic_2026_11_16_votes_harmonized"
```

Saídas: `annotations_harmonized.jsonl` e `harmonization_manifest.json`.
Para consultar sem exibir texto judicial:
```powershell
$m = Get-Content "data/processed/diagnostic_2026_11_16_votes_harmonized/harmonization_manifest.json" -Raw | ConvertFrom-Json
$m.mapped_count
$m.transitions | Format-Table
$m.counts | Format-Table phase,task,status,count
```

Não realizar splits nem treinar até resolver pendências e validar agrupamento por processo.
