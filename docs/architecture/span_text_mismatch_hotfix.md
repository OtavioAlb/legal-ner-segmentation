# Hotfix — Diagnóstico exaustivo de divergências de texto nos spans da Fase 2

## Problema observado em execução real
`ValueError: Span-text mismatch in 14498623/OZQWnOfz12` ao executar `legal_nlp.datasets.versioned_corpus`.

O gate de integridade bloqueou corretamente o snapshot. A causa específica desse span **não foi confirmada**: o traceback não contém as strings nem seus offsets. Auditorias anteriores identificaram escapes literais como um problema frequente; é uma hipótese a verificar, não uma correção automática.

## Ferramenta adicionada
`legal_nlp.datasets.span_text_diagnostics` lê diretamente as regiões `labels` dos exports **original, projeto 11 e projeto 17**, comparando o `value.text` com `data.acordao[start:end]` do documento original.

Por padrão, o JSON de diagnóstico registra:
- acórdão, ID da região, projeto, label, start/end e escolha de checkbox;
- comprimento do texto exportado e do trecho esperado;
- categoria: `exact`, `literal_backslash_escapes_in_span`, `newline_style_difference`, `edge_whitespace`, `case_difference`, `other_mismatch`, `invalid_offsets`, `reference_excerpt_unavailable`.

O relatório **não inclui conteúdo do acórdão** salvo com `--include-excerpts`. Esse flag produz trechos curtos representados com `repr`; o JSON deve ficar exclusivamente em `data/interim/` ou `data/processed/` ignorado no Git, e não deve ser compartilhado publicamente.

## Execução
```powershell
python -m legal_nlp.datasets.span_text_diagnostics `
  --original "data/raw/phase_2/project-anotation-at-2026-09-23-13-29-8041568a.json" `
  --evaluation-11 "data/raw/phase_2/project-11-at-2026-11-16-19-26-8e88e5ca.json" `
  --evaluation-17 "data/raw/phase_2/project-17-at-2026-11-16-19-26-e84e7244.json" `
  --output "data/interim/phase_2/span_text_diagnostics.json"
```

O diretório de saída deve existir; para não sobrescrever evidências, o comando falha se o relatório já existir.

Para localizar o item citado sem imprimir trechos:
```powershell
$r = Get-Content "data/interim/phase_2/span_text_diagnostics.json" -Raw | ConvertFrom-Json
$r.categories
$r.findings | Where-Object { $_.idacordao -eq "14498623" -and $_.region_id -eq "OZQWnOfz12" } | Format-List
```

## Critérios de aceite
- Mantém a rejeição estrita do snapshot em caso de inconsistência textual.
- Nenhum span, offset, label ou decisão humana é alterado.
- Nenhuma conversão implícita de escapes `\\n`, `\\t` ou CRLF é aplicada aos dados.
- O erro do adaptador passa a informar metadados úteis e apontar o comando de diagnóstico, sem expor texto judicial.
- Testes sintéticos verificam escapes literais, CRLF, leitura dos três projetos, imutabilidade dos exports e privacidade por padrão.

Após analisar as categorias reais, decidir separadamente se o problema exige corrigir o export, atualizar a interpretação do texto de origem ou documentar uma política de reparo **explícita e auditável**. Não avançar com treino/splits antes disso.
