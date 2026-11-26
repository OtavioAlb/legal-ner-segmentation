# Revisão local de seções completas — piloto Fase 1 (acórdão 300)

Interface **HTML totalmente offline**, gerada e aberta apenas no Windows
do pesquisador, com texto integral, regiões SEG (inclusive regiões que
não pertencem a grupos de sobreposição), grupos de sobreposição da
mesma label, anotadores, votos individuais e **comentários originais
dos avaliadores**. Não usa Streamlit, serviços web, downloads de CDN
ou conexão ao GitHub para visualizar dados judiciais.

**Importante:** o arquivo HTML contém texto do acórdão, identidade dos
anotadores e comentários pessoais. Ele é sensível e deve ficar sob
`data/processed/`, protegido e fora de commits. Os outputs NÃO são
gold nem treino e não alteram as fontes.

## Verificação da origem

Antes de gerar a página, o script executa novamente:
- comparação SHA-256 de `dados.csv` e
  `spans_consolidados_agrupado_atual.csv` com o manifesto de ingestão;
- verificação das relações `annotations → sanitized → logical_spans
  → document_spans → snapshot → harmonized`;
- conferência de cada linha e de cada opinião `concorda_*`,
  `comentario_*` do CSV efetivamente importado;
- verificação de todos os offsets e do texto integral do acórdão.

A correspondência com o CSV *utilizado* na ingestão não prova
que esse CSV é a exportação primária bruta do Doccano antes de
consolidações humanas anteriores.

## Testes e geração

```powershell
git fetch origin
git switch review/phase1-local-section-adjudication
git pull --ff-only

python -m pytest tests/unit/test_phase1_local_adjudication.py -v
python -m pytest -q

python -m legal_nlp.datasets.phase1_local_adjudication `
  --raw-texts "data/raw/phase_1/dados.csv" `
  --raw-annotations "data/raw/phase_1/spans_consolidados_agrupado_atual.csv" `
  --ingested "data/interim/phase_1" `
  --sanitized "data/interim/phase_1/sanitized" `
  --logical "data/interim/phase_1/logical_spans" `
  --document-spans "data/interim/phase_1/document_dataset/document_spans.jsonl" `
  --snapshot "data/processed/diagnostic_2026_11_16_quarantine" `
  --harmonized "data/processed/diagnostic_2026_11_16_votes_harmonized" `
  --taxonomy "configs/labels.json" `
  --document-id "phase_1:phase1:300" `
  --output "data/processed/diagnostic_2026_11_16_votes_harmonized/phase1_acordao_300_adjudicacao.html"

Start-Process "data/processed/diagnostic_2026_11_16_votes_harmonized/phase1_acordao_300_adjudicacao.html"
```

A página lista todas as regiões SEG do acórdão, permite filtrar
por família de sobreposição e destaca no texto o trecho selecionado.
Os votos, IDs de origem, nomes dos anotadores e comentários ficam
visíveis apenas na página local.

## Registrar proposta

1. Escolha a região-fonte relevante, leia seu texto, compare limites e
   anotações concorrentes. O formulário carrega os limites e label
   escolhidos, permitindo editar offsets para a proposta.
2. Indique se a proposta representa uma seção completa, um fragmento
   interno ou se deve permanecer pendente.
3. Informe uma justificativa de pelo menos 20 caracteres e assinale
   a confirmação explícita da análise humana.
4. Clique **Registrar proposta**. Para exportar, clique em
   **Exportar JSON de revisão**. O navegador salva o arquivo na pasta
   padrão de downloads (mova-o manualmente para um diretório local
   protegido sob `data/processed`, não versionado).

O JSON registra `document_id`, SHA-256 do texto, região selecionada
como origem, label, offsets propostos, decisão e justificativa;
`status=proposed_review_only_not_gold` e
`training_ready=false` são obrigatórios. Não existe botão de
"aprovar gold" nem atualização do corpus.

**Limitações do piloto:** esta interface permite registrar propostas,
mas não executa adjudicação automática, não fecha lacunas nem
verifica cobertura global, não decide hierarquias entre labels e não
resolve concorrentemente edições de vários avaliadores. Propostas
são baixadas pelo navegador, não persistidas em servidor; exporte-as
antes de fechar a aba. Offsets são indexados em caracteres Python; o HTML converte
explicitamente o texto para pontos de código Unicode ao destacar
e validar limites, evitando a divergência com unidades UTF-16
do JavaScript. Não promova o JSON
diretamente a dataset supervisionado.
