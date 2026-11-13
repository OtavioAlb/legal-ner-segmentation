# Auditoria determinística de proveniência — Fase 2

## Escopo e salvaguardas

Esta etapa **não produz gold standard nem decide qual anotação está correta**. Reconstrói a trilha de cada região a partir de três exportações brutas do Label Studio: projeto original 6, avaliação 11 e avaliação 17. A auditoria considera o par `(idacordao, region_id)` como identidade da região. Mesma label e mesmos offsets, mas IDs diferentes, **não** são tratados como a mesma anotação. Uma avaliação ausente nunca equivale a aprovação.

Executar localmente, com dados privados fora do Git:

```powershell
python -m legal_nlp.phase2_provenance_audit `
  --original "data/raw/phase_2/original.json" `
  --evaluation-11 "data/raw/phase_2/evaluation_11.json" `
  --evaluation-17 "data/raw/phase_2/evaluation_17.json" `
  --output "data/interim/phase_2/provenance_audit"
```

Saídas locais (não commitar):
- `phase2_audit.jsonl`: evidências originais e das avaliações lado a lado, escolhas explícitas, comentários, flags, IDs e indicação de adjudicação pendente.
- `phase2_audit.csv`: versão tabular para inspeção humana, com texto original e comentários.
- `phase2_new_candidate_groups.jsonl`: agrupamentos **apenas diagnósticos** de propostas novas pela chave exata `(acordao, task, start, end, label)`, preservando todos os IDs de origem.
- `phase2_audit_summary.json`: contagens reprodutíveis e motivos.

## Interpretação

`NEW_IN_REVIEW` significa que **não existe o mesmo region_id no documento original**; não significa anotação aprovada, anotação correta ou ocorrência semanticamente inexistente no original. `ORIGINAL_NO_FLAGS` significa somente ausência de flags segundo as regras atuais, **não** aceitação humana da entidade. `EXPLICIT_NEGATIVE_11/17` sobrepõe-se à aparente igualdade de rótulo/offset e impede que a evidência seja interpretada como concordância. Os campos `adjudicated` são sempre `false` nesta etapa.

O caso de regressão `idacordao=16062822`, `region_id=kQcIH4ot0Y`: nova proposta em 11, escolha explícita `Incorreto`, comentário de ajuste de limites e ausente em 17. O teste usa apenas dados sintéticos, sem texto judicial.

**Limitações:** não resolve o conteúdo dos comentários, não corrige offsets, não deduz correspondência por similaridade, não infere aprovação quando faltam checkboxes e não faz reconciliação semântica de regiões novas. A divergência com planilhas anteriores deve ser investigada, não normalizada para um número esperado.

Reproduzir e conferir as diferenças antes de qualquer novo consolidado. A branch não altera a Fase 1, as 67 classes, o dataset supervisionado ou `main`.
