# SEG: candidatos a seções completas — política conservadora

## Objetivo

A finalidade acordada é **identificar a extensão completa das seções
do acórdão**, não simplesmente maximizar a quantidade de trechos anotados.
Esta triagem examina as **187 famílias de sobreposição de mesma label
da Fase 1**, cujas avaliações e proveniência já foram verificadas
em etapas anteriores.

A análise **não define** que todas as 13 labels SEG têm o mesmo nível
estrutural. Podem existir seções principais e segmentos semânticos
internos. As relações entre labels diferentes são reservadas à análise
global do documento; esta auditoria é estritamente intralabel.

## Regras

1. Os arquivos CSV de texto e anotação da ingestão são novamente
   verificados por SHA-256 e cada linha de avaliações é confrontada
   com os registros originais.
2. Para toda família de mesma label, duas geometrias com votos positivos
   são classificadas conforme **limites quase iguais** (tolerância
   configurável), **contenção**, **sobreposição parcial** ou **disjunção**.
   A ordem de prioridade das relações evita dupla contagem de pares.
3. Uma região com voto positivo que **não está inteiramente contida**
   em outra região positivamente avaliada recebe
   `is_maximal_supported_interval=true`. Isso significa somente
   **candidata prioritária à inspeção**, e nunca seção completa
   confirmada ou target gold.
4. Geometrias rejeitadas não dominam as regiões com apoio; uma região
   ampla sem votos positivos não vence por extensão.
5. Nenhum resultado autoriza descartar fragmentos, fundir intervalos,
   corrigir offsets ou escolher uma anotação vencedora. Anotações com
   votos negativos continuam disponíveis e sinalizadas.
6. O relatório cobre **todas** as famílias, não apenas 100 da fila.
   Recusa evidência incompleta ou amostrada.

## Executar

```powershell
git fetch origin
git switch analysis/seg-complete-section-candidates
git pull --ff-only

python -m pytest tests/unit/test_seg_full_section_candidates.py -v
python -m pytest -q

python -m legal_nlp.datasets.seg_full_section_candidates `
  --raw-texts "data/raw/phase_1/dados.csv" `
  --raw-annotations "data/raw/phase_1/spans_consolidados_agrupado_atual.csv" `
  --ingested "data/interim/phase_1" `
  --sanitized "data/interim/phase_1/sanitized" `
  --logical "data/interim/phase_1/logical_spans" `
  --document-spans "data/interim/phase_1/document_dataset/document_spans.jsonl" `
  --snapshot "data/processed/diagnostic_2026_11_16_quarantine" `
  --harmonized "data/processed/diagnostic_2026_11_16_votes_harmonized" `
  --taxonomy "configs/labels.json" `
  --near-tolerance 5 `
  --output "data/processed/diagnostic_2026_11_16_votes_harmonized/seg_full_section_candidates.json"
```

## Consultar os agregados e o caso 300

```powershell
$r = Get-Content "data/processed/diagnostic_2026_11_16_votes_harmonized/seg_full_section_candidates.json" -Raw | ConvertFrom-Json
$r.summary | ConvertTo-Json -Depth 4

$g = $r.families |
  Where-Object { $_.document_id -eq "phase_1:phase1:300" -and
                 $_.label -eq "SEG_RELATORIO" } |
  Select-Object -First 1

$g.candidates | Select-Object logical_span_id,start,end,length,
  distinct_reviewers_agreeing,distinct_reviewers_disagreeing,
  is_maximal_supported_interval,review_notes | Format-Table -AutoSize

$g.pair_relations_among_positively_evaluated | ConvertTo-Json -Depth 3
```

## Critérios para a adjudicação futura

Para promover um candidato a target de treinamento, são necessárias:
- correspondência entre seus limites e as **seções completas no texto**;
- decisão explícita sobre segmentação estrutural versus trecho
  semântico interno, **por label**;
- avaliação das regiões concorrentes, comentários originais e votos
  negativos; e
- validação documental de que a escolha não deixa partes estruturais
  indevidamente descobertas ou sobrepõe outra seção de modo impróprio.

O script não cobre spans SEG isolados, interações entre labels
diferentes ou lacunas entre seções: essas análises integram a fase
posterior de consistência documental, antes da geração de targets.

**Fonte:** `spans_consolidados_agrupado_atual.csv` corresponde ao
SHA-256 registrado na ingestão, mas não foi demonstrado que é a
exportação primária não consolidada do Doccano.

**Restrições:** arquivos JSON de saída em `data/processed/` são
locais e não devem ser enviados a um PR; não modificar fontes,
não gerar gold e não mesclar PRs sem autorização.
