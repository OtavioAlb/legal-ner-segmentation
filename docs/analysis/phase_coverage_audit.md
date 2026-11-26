# Auditoria de frequência potencial, densidade e cobertura — Fases 1 e 2

## Objetivo
Comparar a composição dos 25 acórdãos da Fase 1 e 35 da Fase 2
sem subestimar o volume potencial de treinamento. O relatório conta
**consolidados + pendentes** em frequência, suporte por label e métricas
de cobertura, mas mantém status separado. Não converte pendências em gold.

Os registros normalizados sob quarentena são informados separadamente,
**sem somar as ocorrências de origem como novas anotações**.

## Números do snapshot já verificados
- Fase 1: 1.858 NER e 1.133 SEG = 2.991 consolidados.
- Fase 2: 1.063 NER e 216 SEG consolidados;
  578 NER e 193 SEG pendentes; total 1.641 NER e 409 SEG = 2.050.
- Total no snapshot: 5.041; 4.270 consolidados e 771 pendentes.
- Quarentena: 9 linhas normalizadas e 23 ocorrências nos três exports.

## Métricas adicionais
- Caracteres totais por fase e distribuição do comprimento dos documentos
  (mínimo, mediana, máximo e média).
- Spans NER/SEG por documento e por 10.000 caracteres.
- Cobertura de SEG: proporção de caracteres cobertos pela **união** dos
  intervalos [start:end); sobreposições não inflacionam a métrica.
- Distribuição do número de segmentos por acórdão.
- Frequência por label na Fase 1 e na Fase 2, separando
  consolidado, pendente, total potencial e documentos com suporte.
- Quarentena segregada por tipo de tarefa.

Limitação: cobertura percentual não equivale a completude, pois os segmentos
podem ser categorias seletivas, sobrepostas ou não exaustivas. Uma mesma região
pode mudar de label, desaparecer ou ser substituída na adjudicação.

## Execução (PowerShell)
```powershell
git fetch origin
git switch analysis/phase-coverage-and-label-frequency
git pull --ff-only
python -m pytest tests/unit/test_phase_coverage_audit.py -v
python -m pytest -q

python -m legal_nlp.datasets.phase_coverage_audit `
  --snapshot "data/processed/diagnostic_2026_11_16_quarantine" `
  --output "data/processed/diagnostic_2026_11_16_quarantine/phase_coverage_audit.json"
```

### Resumo por fase
```powershell
$r = Get-Content "data/processed/diagnostic_2026_11_16_quarantine/phase_coverage_audit.json" -Raw | ConvertFrom-Json
$r.by_phase.phase_1
$r.by_phase.phase_2
$r.quarantine
```

### Frequências das labels (potencial)
```powershell
$r.labels |
  Sort-Object task,label |
  Select-Object task,label,phase_1_potential,phase_2_potential,total_potential_in_snapshot,phase_2_pending,phase_1_documents_support,phase_2_documents_support |
  Format-Table -AutoSize
```

### Labels com menos de 10 ocorrências totais
```powershell
$r.labels |
  Where-Object { $_.total_potential_in_snapshot -lt 10 } |
  Sort-Object total_potential_in_snapshot |
  Select-Object task,label,total_potential_in_snapshot,phase_1_potential,phase_2_potential
```

## Interpretação para a modelagem
- Frequência é apenas um indicador preliminar de suporte de classe;
  não garante quantidade suficiente **por processo ou por fold**.
- A fase 2 tem menos segmentos por documento; usar cobertura e densidade
  por caracteres antes de atribuir a diferença à metodologia de anotação.
- Classes com suporte muito baixo exigem análise específica de viabilidade,
  eventual avaliação hierárquica e comunicação de resultados com incerteza.
  **Não** eliminar ou agregar labels automaticamente.
- Distribuir treino/teste apenas após validação do vínculo por processo;
  não congelar splits usando `idacordao` como se fosse `process_id`.
- Não aprovar nenhuma região pendente ou em quarentena por inferência.
