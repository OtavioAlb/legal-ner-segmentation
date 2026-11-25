# Correção controlada: equivalência de escapes literais no Label Studio

## Evidência observada nos exports reais
O diagnóstico independente registrou 4.988 ocorrências (não 4.988 regiões únicas):
- 3.834 correspondências exatas.
- 1.131 trechos que coincidem integralmente com `document[start:end]` ao interpretar sequências literais `\\n` e `\\t`.
- 23 outras divergências que **não** podem ser corrigidas por essa regra.

Exemplo identificado: `14498623 / OZQWnOfz12`, `SEG_FOLHA_ROSTO`, intervalo `[0:536)`, texto exportado de comprimento 543 e recorte original de comprimento 536. As decisões divergentes dos projetos 11 (Certo) e 17 (Limite impreciso) **continuam pendentes**; equivalência textual não elimina conflito de checkbox.

## Implementação
No `resolve_text`, aplicar nesta ordem:
1. `value.text == document[start:end]` → `text_equivalence=exact`.
2. `value.text` contém `\\n` ou `\\t` e sua interpretação coincide **exatamente** com o slice original completo → `verified_literal_backslash_escapes`. O trecho exportado não é descartado: persiste em `source_text_raw`. Mantêm-se os mesmos offsets, label, status e proveniência.
3. `value.text` ausente na visão consolidada → `source_excerpt_unavailable`; recuperar o slice imutável, **sem afirmar comparação com um trecho exportado**.
4. Qualquer outra discrepância → erro estrito, com instrução para diagnóstico.

O manifesto contabiliza as três situações. A normalização é **apenas da representação do trecho da anotação**, não da fonte da decisão, de seus offsets ou da política de adjudicação.

## Reexecução e pendências
Os 23 outros mismatches permanecem para inspeção. O snapshot poderá continuar falhando se algum deles pertencer às regiões representadas na visão normalizada. Isso é esperado.

Executar:
```powershell
git fetch origin
git switch fix/phase2-verified-escapes
git pull --ff-only
python -m pytest tests/unit/test_verified_escape_equivalence.py -v
python -m pytest -q

$r = Get-Content "data/interim/phase_2/span_text_diagnostics.json" -Raw | ConvertFrom-Json
$r.findings | Where-Object { $_.category -eq "other_mismatch" } |
    Select-Object idacordao,region_id,project,label,start,end,source_text_length,document_slice_length,checkbox |
    Format-Table -AutoSize
```

Para preservar evidências, executar o `versioned_corpus` com os mesmos inputs em um **novo** diretório/version, pois snapshots existentes não podem ser sobrescritos.

## Importante
- Correspondências formais não equivalem a gold supervisionado.
- Análise não implica que todas as 1.131 ocorrências representem erros distintos.
- Nenhum dado judicial deve ser inserido em commits ou PRs.
