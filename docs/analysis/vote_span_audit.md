# Auditoria de uso das labels de votos na Fase 2

## Configuração original confirmada
No XML de anotação do Label Studio entregue pelo pesquisador, estão definidas
`ENT_DECISAO_VOTO_VENCEDOR`, `ENT_DECISAO_VOTO_VENCIDO`,
`SEG_JURISPRUDENCIA_VOTO_VENCEDOR` e
`SEG_JURISPRUDENCIA_VOTO_VENCIDO`.

As labels `SEG_DECISAO_VOTO_VENCEDOR` e
`SEG_DECISAO_VOTO_VENCIDO` não aparecem no XML original; foram
adicionadas ao contrato canônico 1.1.0 por decisão explícita posterior.

## Pergunta
Os spans `ENT_DECISAO_VOTO_*` na Fase 2 representam fragmentos de
conteúdo típicos de entidade ou trechos estruturais que se comportam como
segmentos?

## Análise implementada
`legal_nlp.datasets.vote_span_audit` calcula, para as seis labels alvo:
- Frequência por fase, separando consolidado e pendente.
- Comprimento em caracteres e palavras, mín./mediana/média/p90/máximo.
- Posição percentual no documento e fração de seu comprimento total.
- Sobreposição e contenção por segmentos SEG do mesmo documento.
- Registros detalhados de geometria, sem trechos textuais.
- Ocorrências **diretamente nos três exports originais do Label Studio**,
  inclusive para labels com zero ocorrências no snapshot.
- Votos em linhas normalizadas de quarentena, separados do snapshot.

## Comandos
```powershell
git fetch origin
git switch analysis/phase2-vote-span-behavior
git pull --ff-only
python -m pytest tests/unit/test_vote_span_audit.py -v
python -m pytest -q

python -m legal_nlp.datasets.vote_span_audit `
  --snapshot "data/processed/diagnostic_2026_11_16_quarantine" `
  --original "data/raw/phase_2/project-anotation-at-2026-09-23-13-29-8041568a.json" `
  --evaluation-11 "data/raw/phase_2/project-11-at-2026-11-16-19-26-8e88e5ca.json" `
  --evaluation-17 "data/raw/phase_2/project-17-at-2026-11-16-19-26-e84e7244.json" `
  --output "data/processed/diagnostic_2026_11_16_quarantine/vote_span_audit.json"
```

### Sumário
```powershell
$r = Get-Content "data/processed/diagnostic_2026_11_16_quarantine/vote_span_audit.json" -Raw | ConvertFrom-Json
$r.label_statistics |
  Select-Object phase,label,occurrences,consolidated,pending_review,documents_with_label,
    @{n="median_chars";e={$_.character_lengths.median}},
    @{n="p90_chars";e={$_.character_lengths.p90}},
    @{n="median_words";e={$_.word_counts.median}},
    @{n="median_doc_fraction";e={$_.document_fraction.median}} |
  Format-Table -AutoSize

$r.phase2_raw_label_counts.original
$r.phase2_raw_label_counts.'11'
$r.phase2_raw_label_counts.'17'
```

A interpretação de NER versus segmentação requer olhar o tamanho e a
geometria dos spans. Não converter labels com base apenas em seu prefixo;
não aprovar a equivalência entre ENT_DECISAO e SEG_DECISAO sem evidência.

Zero uso de `SEG_JURISPRUDENCIA_VOTO_VENCIDO` no snapshot não indica
ausência no schema original, nem confirma ausência de votos vencidos nos acórdãos.
