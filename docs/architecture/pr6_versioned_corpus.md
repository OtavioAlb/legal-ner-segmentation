# PR 6 — Snapshot diagnóstico versionado das duas fases

## Objetivo
Produzir uma **versão imutável de diagnóstico**, combinando spans já saneados da Fase 1 com a auditoria determinística da Fase 2. Ainda **não** constituir gold/train/dev/test.

## Execução
```powershell
python -m legal_nlp.datasets.versioned_corpus `
  --phase1-document-spans data/interim/phase_1/document_dataset/document_spans.jsonl `
  --phase2-original data/raw/phase_2/project-anotation-at-2026-09-23-13-29-8041568a.json `
  --phase2-review-11 data/raw/phase_2/project-11-at-2026-11-16-19-26-8e88e5ca.json `
  --phase2-review-17 data/raw/phase_2/project-17-at-2026-11-16-19-26-e84e7244.json `
  --labels configs/labels.json `
  --output data/processed/diagnostic_2026_11_16 `
  --version diagnostic_2026_11_16
```

Os caminhos dos exports acima são exemplos da última versão identificada no projeto. Usar os arquivos efetivamente disponíveis e conferir datas/hashes antes de executar.

## Saídas locais, não versionadas no Git
- `documents.jsonl`: dados originais da decisão e SHA-256 do texto, identidade `phase_1:` ou `phase_2:`.
- `annotations.jsonl`: spans com status `consolidated` ou `pending_review`, proveniência, texto e offsets exatos.
- `dataset_manifest.json`: versão do esquema, hashes de **todos** os inputs, versão da taxonomia, contagens por fase/tarefa/status, métricas da auditoria original, e flags `training_ready=false`, `splits_frozen=false`.

## Gates fail-closed
- Recusa sobrescrever diretório de snapshot existente.
- Recusa duplicidade de `idacordao` entre as duas fases até conciliação manual, mesmo se outros IDs forem diferentes.
- Recusa dois documentos com mesmo texto/hash (identidade ambígua).
- Recusa checksum da Fase 1 divergente ou texto ausente.
- Recusa offsets inválidos, texto divergente e labels fora da taxonomia.
- As regiões pendentes **nunca** são promovidas automaticamente a gold. Novas propostas coincidentes já consolidadas são representadas uma vez, sem perder IDs originais.
- Não recorta, normaliza, deduplica ou remove spans sobrepostos.

## Limitações
- A auditoria da Fase 2 pode demandar substituições e adjudicações adicionais. Este snapshot reflete exatamente os exports fornecidos; não é a validação humana definitiva.
- Não deduz chave de processo judicial a partir de `idacordao`. Sem chave de processo, os splits finais ainda não são permitidos.
- Nenhum dado derivado contendo textos judiciais pode ser commitado em Git público.
- O sistema não executa backup remoto dos dados ou snapshots.
- Se houver falha de escrita durante a emissão de arquivos, a pasta parcial deverá ser removida manualmente, após inspeção, antes de tentar novamente.

## Testes
```powershell
git fetch origin
git switch refactor/versioned-corpus-pr6
git pull --ff-only
python -m pytest tests/integration/test_versioned_corpus.py -v
python -m pytest -q
```

Comparar no ambiente local contagens originais por documento, task, status, labels e IDs com os relatórios da Fase 2, e validar hashes dos inputs. Não use o snapshot como treino até aprovação explícita da política de elegibilidade e congelamento de partições.

## Histórico de PRs
Base desta entrega: `refactor/corpus-adapters-pr5`. `main` intacta.
