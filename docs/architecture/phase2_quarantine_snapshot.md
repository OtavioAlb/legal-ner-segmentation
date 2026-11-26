# PR — Snapshot diagnóstico com quarentena conservadora de regiões

## Evidência de entrada
- Os 35 textos integrais são **byte-equivalentes após leitura UTF-8** entre os três projetos (SHA-256 igual).
- Em 4.988 ocorrências de spans, 3.834 coincidem exatamente, 1.131 coincidem após interpretação verificada de escapes literais, e 23 apresentam diferenças textuais residuais.
- As 23 ocorrências correspondem a nove pares `(idacordao, region_id)`, não necessariamente nove registros normalizados.

## Mudança
`legal_nlp.datasets.versioned_corpus` passa a inspecionar **todas as regiões fonte dos três projetos**, mesmo quando a linha consolidada anteriormente não trazia `value.text`.

Por padrão, uma inconsistência não resolvida interrompe o pipeline **antes de criar a pasta de saída**. Com `--quarantine-unresolved`, o pipeline produz um snapshot estritamente diagnóstico que:
- Conserva somente candidatos normalizados cujos IDs de origem não tenham divergência textual não resolvida em qualquer projeto.
- Produz `quarantine.jsonl` com registros normalizados afetados, IDs, proveniência, status estrutural anterior, e uma ocorrência por export problemático; nenhum trecho textual é copiado para esse arquivo.
- Preserva os três exports originais, intactos, como fontes de evidência referenciadas pelos hashes no manifesto.
- Mantém `training_ready=false`, `splits_frozen=false` e adiciona as contagens de quarentena ao manifesto.
- Em `datasets.readiness`, a condição `source_text_quarantine_empty` bloqueia a prontidão enquanto houver itens em quarentena.

**Cuidado com as contagens:** `quarantine_record_count` contém tanto linhas normalizadas segregadas quanto ocorrências individuais nos exports. Portanto, esse total não deve ser interpretado como número de regiões distintas, nem automaticamente igual a 23 ou 9.

A segregação é conservadora: se a mesma região apresenta incompatibilidade textual em qualquer export, a correspondente linha normalizada é segregada, independentemente de checkbox/label concordantes. Nenhum checkbox ou status humano é reescrito ou aprovado.

## Execução local

Primeiro, valide os testes:
```powershell
git fetch origin
git switch feat/phase2-quarantine-snapshot
git pull --ff-only
python -m pytest tests/integration/test_phase2_quarantine_snapshot.py -v
python -m pytest -q
```

Depois execute em um **novo** diretório, com os exports já utilizados:
```powershell
python -m legal_nlp.datasets.versioned_corpus `
  --phase1-document-spans "data/interim/phase_1/document_dataset/document_spans.jsonl" `
  --phase2-original "data/raw/phase_2/project-anotation-at-2026-09-23-13-29-8041568a.json" `
  --phase2-review-11 "data/raw/phase_2/project-11-at-2026-11-16-19-26-8e88e5ca.json" `
  --phase2-review-17 "data/raw/phase_2/project-17-at-2026-11-16-19-26-e84e7244.json" `
  --labels "configs/labels.json" `
  --output "data/processed/diagnostic_2026_11_16_quarantine" `
  --version "diagnostic_2026_11_16_quarantine" `
  --quarantine-unresolved
```

E execute a auditoria de prontidão:
```powershell
python -m legal_nlp.datasets.readiness `
  --snapshot "data/processed/diagnostic_2026_11_16_quarantine" `
  --output "data/processed/diagnostic_2026_11_16_quarantine/readiness.json"
```

## Limites
- Não aprova região para treinamento. Concordância estrutural continua distinta de adjudicação definitiva.
- Não corrige os nove pares discrepantes, nem elimina as divergências de checkbox.
- Se um registro normalizado não estiver entre os IDs fonte problemáticos, ainda se submete às regras originais de `resolve_text`, taxonomia, documento e offsets.
- Uma eventual falha de outro gate legítimo continua interrompendo o snapshot; a flag não autoriza ignorar erros.
- Não faz merge na `main`. Todos os outputs privados permanecem em `data/processed/` ignorado pelo Git.
