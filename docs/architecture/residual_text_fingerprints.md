# Diagnóstico das divergências textuais residuais da Fase 2

## Contexto
A análise local retornou 4.988 ocorrências nos três projetos do Label Studio:
3.834 exatas, 1.131 compatíveis com escapes literais e **23 `other_mismatch`**.
As 23 ocorrências pertencem a **nove pares distintos (idacordao, region_id)**,
repetidos entre os exports original, 11 e 17.

A tolerância de dez caracteres em `span_diagnostics.py` pertence à
comparação geométrica **entre spans**; não deve ser aplicada à equivalência
entre `value.text` e o slice do documento.

## Solução adicionada
`datasets/residual_text_fingerprints.py` lê os **três exports originais**
e avalia apenas `other_mismatch`, agrupando registros repetidos pelo par
`(idacordao, region_id)` **sem eliminar** os registros individuais dos projetos.

Para cada projeto e região, o relatório descreve:
- Hashes SHA-256 das duas representações; comprimentos e diferença de comprimento.
- Primeira posição diferente nos dois textos.
- Operações `replace`, `insert`, `delete`, com offsets e comprimentos.
- Equivalência hipotética após NFC, NFKC, remoção de espaços ou HTML unescape.
- Label, offsets, projeto e checkbox, sem trechos judiciais.

**Essas verificações são diagnósticas:** nenhuma equivalência adicional
é aceita pelo corpus, nenhum offset é alterado, nenhuma decisão de checkbox
é recalculada e nenhuma região é automaticamente consolidada.

## Execução (PowerShell)
```powershell
git fetch origin
git switch fix/phase2-residual-text-fingerprints
git pull --ff-only
python -m pytest tests/unit/test_residual_text_fingerprints.py -v
python -m pytest -q

python -m legal_nlp.datasets.residual_text_fingerprints `
  --original "data/raw/phase_2/project-anotation-at-2026-09-23-13-29-8041568a.json" `
  --evaluation-11 "data/raw/phase_2/project-11-at-2026-11-16-19-26-8e88e5ca.json" `
  --evaluation-17 "data/raw/phase_2/project-17-at-2026-11-16-19-26-e84e7244.json" `
  --output "data/interim/phase_2/residual_text_fingerprints.json"
```

A saída deve permanecer em `data/interim` (ignorado no Git). Não sobrescreve
relatório existente nem copia conteúdo do acórdão.

## Conferência resumida
```powershell
$r = Get-Content "data/interim/phase_2/residual_text_fingerprints.json" -Raw | ConvertFrom-Json
$r.occurrences
$r.unique_regions_by_document_and_region_id
$r.regions | ForEach-Object {
  $reg = $_
  $reg.projects | Select-Object @{n="idacordao";e={$reg.idacordao}},
    @{n="region_id";e={$reg.region_id}}, project, label,
    @{n="diff";e={$_.fingerprint.length_difference}},
    @{n="nfc";e={$_.fingerprint.unicode_nfc_equivalent}},
    @{n="nfkc";e={$_.fingerprint.unicode_nfkc_equivalent}},
    @{n="spaces";e={$_.fingerprint.whitespace_insensitive_equivalent}},
    @{n="html";e={$_.fingerprint.html_entity_equivalent}},
    @{n="ops";e={$_.fingerprint.edit_operation_counts | ConvertTo-Json -Compress}}
} | Format-Table -AutoSize
```

**Condição para avançar:** compreender as nove regiões com evidência suficiente
e aprovar separadamente qualquer futura regra de equivalência. Até lá o gate
estrito de `versioned_corpus` continua bloqueando mismatch não reconhecido.
