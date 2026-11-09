# Refinamento dos 35 alertas estruturais da Fase 2

Etapa **somente diagnóstica**, executada **depois** de
`phase2_auto_review` e `phase2_new_region_comments`.
Não elimina anotações, não atribui escolhas e não promove regiões a gold.

Execute no repositório (PowerShell):

```powershell
python -m legal_nlp.phase2_structural_alerts `
  --evaluations "data/interim/phase_2/automatic_review_2026-11-09/evaluations_filtered_automatic.json" `
  --triage "data/interim/phase_2/new_region_comments_2026-11-09/new_regions_triage.jsonl" `
  --output "data/interim/phase_2/refined_alerts"
```

Relatórios privados sob `data/` (nunca versionar):
- `structural_alerts_summary.json`
- `structural_alerts_refined.jsonl`
- `structural_alerts_refined.csv`

Classificação principal, categorias exclusivas, por ordem de precedência:
1. `copia_exata_do_original`: igualdade da assinatura original com outro ID.
2. `duplicacao_entre_novas_regioes`: rótulo e offsets iguais em IDs novos.
3. `coincidencia_ner_seg`: offsets iguais e famílias NER/SEG distintas; potencialmente válido.
4. `rotulo_alternativo_mesma_tarefa`: offsets iguais mas rótulos distintos na mesma família.
5. `ajuste_de_limite_possivel`: forte sobreposição de mesmo rótulo; exige inspeção.
Casos ambíguos ou mistos permanecem destacados. Todas as evidências são preservadas.

A auditoria de 2026-11-09 encontrou 35 alertas: 3 cópias de original,
8 duplicações entre novas regiões, 11 coincidências NER/SEG,
11 rótulos alternativos e 2 possíveis ajustes de limites.
21 alertas têm julgamento explícito associado a uma região original;
2 têm julgamento em outra região nova coincidente; 6 possuem comentário.

**Importante:** um voto `Certo` pode ser estruturalmente inconsistente com
uma alteração de rótulo na mesma região. A rotina registra o fato, mas
não interpreta o voto como confirmação automática da alteração.
Mesmos offsets NER/SEG não são prova de duplicação.
Dados judiciais, comentários e relatórios por região nunca devem
ser enviados para este repositório público.
