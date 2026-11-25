# Investigação final: caracteres das 9 regiões residuais

## Objetivo
Identificar com precisão os caracteres distintos entre o `value.text` exportado e o trecho `acordao[start:end]`, sem aplicar tolerância geométrica de dez caracteres, modificar anotações ou aprovar automaticamente equivalências adicionais.

## Implementação
Foi acrescentado `--include-codepoints` ao diagnóstico `legal_nlp.datasets.residual_text_fingerprints`. O relatório opcional inclui, por operação de edição, os intervalos e os codepoints Unicode alterados (por exemplo, `U+00C7`) e seus nomes. Não inclui contexto textual.

**Atenção:** codepoints de nomes próprios ainda podem revelar conteúdo sensível. Mantenha o JSON sob `data/interim/` ignorado pelo Git; não anexe nem faça commit desse arquivo. A versão sem `--include-codepoints` permanece a opção padrão.

## Execução
```powershell
git fetch origin
git switch fix/phase2-residual-char-investigation
git pull --ff-only
python -m pytest tests/unit/test_residual_char_investigation.py -v
python -m pytest -q

python -m legal_nlp.datasets.residual_text_fingerprints `
  --original "data/raw/phase_2/project-anotation-at-2026-09-23-13-29-8041568a.json" `
  --evaluation-11 "data/raw/phase_2/project-11-at-2026-11-16-19-26-8e88e5ca.json" `
  --evaluation-17 "data/raw/phase_2/project-17-at-2026-11-16-19-26-e84e7244.json" `
  --include-codepoints `
  --output "data/interim/phase_2/residual_text_codepoints.json"
```

### Resumo de uma ocorrência por região (sem trechos judiciais)
```powershell
$r = Get-Content "data/interim/phase_2/residual_text_codepoints.json" -Raw | ConvertFrom-Json
$r.regions | ForEach-Object {
    $region = $_
    $entry = $_.projects[0]
    [pscustomobject]@{
        idacordao = $region.idacordao
        region_id = $region.region_id
        projeto = $entry.project
        operacoes = ($entry.character_operations | ForEach-Object {
            $before = ($_.source_codepoints.codepoint -join ",")
            $after = ($_.document_codepoints.codepoint -join ",")
            "$($_.operation):$before=>$after"
        }) -join " | "
    }
} | Format-List
```

Para as 9 regiões, a investigação determinará se os caracteres diferem por códigos de formatação, entidades HTML, substituições de caracteres ou alteração de conteúdo. Nenhum status de adjudicação será modificado automaticamente, e o snapshot continuará bloqueando inconsistências não equivalentes.
