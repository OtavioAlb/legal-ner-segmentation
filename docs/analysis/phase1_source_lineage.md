# Auditoria da Fase 1: rastreamento a partir dos arquivos originais

**Regra de segurança:** esta auditoria não aceita apenas o snapshot como
evidência. Exige os dois arquivos originais (texto e anotações CSV/XLSX)
que deram entrada em `ingestion.py`. Antes de qualquer comparação,
confere o SHA-256 exato desses arquivos com `data/interim/phase_1/dataset_manifest.json`.

## Cadeia de fonte verificada pelo código

1. Arquivos `raw` de textos e anotações → hashes gravados pelo `ingestion.py`
2. `data/interim/phase_1/annotations.jsonl`: colunas originais,
   revisão, anotador, origem e decisão de seleção
3. `data/interim/phase_1/sanitized/sanitized_annotations.jsonl`:
   seleções elegíveis e offsets/labels finais
4. `data/interim/phase_1/logical_spans/logical_spans.jsonl`:
   agrupamento exato por `document_id,task,start,end,label`, com
   todas as fontes preservadas na lista `provenance`
5. `data/interim/phase_1/document_dataset/document_spans.jsonl`
6. `data/processed/diagnostic_2026_11_16_quarantine/{documents,annotations}.jsonl`
7. `data/processed/diagnostic_2026_11_16_votes_harmonized/annotations_harmonized.jsonl`

O script falha se houver: exportação original com hash divergente,
origem lógica ausente, contagem de região inconsistente,
origem de anotação sem justificativa de seleção, anotação sanitizada
não rastreável, mudança de offsets entre as camadas, mudança de texto
documental, diferença entre lista de provenance e anotação original.

**Importante:** a confirmação dos hashes dos CSVs prova que são os mesmos
arquivos declarados no manifesto de ingestão, não prova que a exportação
Doccano em si foi feita corretamente ou que todas as decisões
humanas são corretas. A auditoria não reexecuta a ingestão nem
classifica consenso de avaliadores a partir das contagens de voto.

## Encontrar os arquivos raw corretos, sem adivinhar nomes

```powershell
$manifest = Get-Content "data/interim/phase_1/dataset_manifest.json" -Raw | ConvertFrom-Json
$manifest.input_sha256 | Format-List

Get-ChildItem "data/raw" -Recurse -File |
  Where-Object { $_.Extension -in ".csv", ".xlsx" } |
  ForEach-Object {
    [pscustomobject]@{
      Arquivo = $_.FullName
      SHA256 = (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower()
    }
  } | Where-Object {
    $_.SHA256 -in @($manifest.input_sha256.texts, $manifest.input_sha256.annotations)
  } | Format-Table -AutoSize
```

**Não use caminhos escolhidos por nome apenas:** utilize as duas
correspondências exatas de SHA-256. Caso não apareçam, a fonte original
não foi localizada e a auditoria deve parar.

## Execução

Substitua os dois caminhos abaixo pelos caminhos exatos encontrados
pela comparação dos hashes:

```powershell
git fetch origin
git switch audit/phase1-original-source-lineage
git pull --ff-only
python -m pytest tests/unit/test_phase1_source_lineage.py -v
python -m pytest -q

python -m legal_nlp.datasets.phase1_source_lineage `
  --raw-texts "CAMINHO_EXATO_DO_CSV_OU_XLSX_DE_TEXTOS" `
  --raw-annotations "CAMINHO_EXATO_DO_CSV_OU_XLSX_DE_ANOTACOES" `
  --ingested "data/interim/phase_1" `
  --sanitized "data/interim/phase_1/sanitized" `
  --logical "data/interim/phase_1/logical_spans" `
  --document-spans "data/interim/phase_1/document_dataset/document_spans.jsonl" `
  --snapshot "data/processed/diagnostic_2026_11_16_quarantine" `
  --harmonized "data/processed/diagnostic_2026_11_16_votes_harmonized" `
  --taxonomy "configs/labels.json" `
  --output "data/processed/diagnostic_2026_11_16_votes_harmonized/phase1_source_lineage.json"
```

O arquivo detalhado tem `annotation_id`, `source_row`, offsets,
label original e revisada, status e contagem de votos: **mantenha local**.
O terminal exibe apenas totais de verificação.

Se alguma etapa não estiver disponível ou não corresponder, pare:
**não imputar proveniência** e não inferir que as sobreposições são
duplicatas ou que existe gold. Não alterar nenhuma anotação.
