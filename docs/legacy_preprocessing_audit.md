# Auditoria do pré-processamento legado e política da Fase 1

Status: diagnóstico e proposta de implementação; **não define o gold standard**.

## Insumos considerados

- `src.zip`: projeto Python anterior, incluindo `src/pipeline/preprocessing.py`, `src/pipeline/dataset_builder.py` e `src/utils/consolidate_data.py`.
- `raw.zip`: `dados.csv`, `spans_consolidados_agrupado_atual.csv` e `spans_consolidados_oficial.xlsx`.
- Configuração de rótulos Label Studio: 54 `ENT_*` e 11 `SEG_*`.

## Regras do sistema anterior

1. `_filter_ent_spans` (`preprocessing.py`) mantinha exclusivamente `ENT_*` com ID e offsets revisados preenchidos; `SEG_*` não entrava no treinamento.
2. `_normalize_labels` utilizava dicionário restrito à nomenclatura antiga. Não transplantar mapeamentos de `ENT_NORMA_*` para `ENT_NORM_*` sem rever o esquema atual.
3. `_resolve_duplicates` eliminava duplicatas por documento, rótulo e offsets e descartava informações dos revisores. Embora houvesse menção a *majority vote*, nenhuma votação foi implementada nesse método.
4. `_normalize_for_comparison` tolerava caixa, acentuação e espaços. Em seguida, `_trim_spans` ajustava as fronteiras de algumas anotações (espaço, ponto e vírgula), modificando offsets.
5. `_resolve_overlaps` removia o maior span em cada conflito adjacente; não preservava aninhamentos legítimos nem divergências anotador–anotador.
6. `_filter_rare_entities` removia rótulos com frequência abaixo de um limiar global (padrão 10), com risco de exclusão de categorias relevantes.
7. O agrupamento por documento no `dataset_builder.py` é conceitualmente reaproveitável; a avaliação de um modelo final no próprio conjunto usado para retreinamento não é estimativa válida de generalização.
8. O script `src/utils/consolidate_data.py` associava colunas de pareceres de sete abas pela **posição da linha**, não por uma chave imutável da anotação.

**Conclusão:** os códigos legados são referência histórica. Não executar as regras de exclusão, fallback, trim e overlap na camada de ingestão.

## Evidências da Fase 1

No relatório anterior do usuário havia 25 documentos e 5.295 linhas anotadas. A auditoria apontava 537 registros com ao menos um problema e 599 ocorrências técnicas: 328 rótulos desconhecidos, 150 offsets inválidos, 70 documentos desconhecidos, 50 divergências de texto e um rótulo ausente. Esses números refletem o **importador anterior à separação estrita dos campos revisados**; deverão mudar após reexecução.

Também havia 57 candidatos documentais únicos por coincidência exata de texto/offset dentre 70 linhas sem ID. Essas são **sugestões**, não vínculos aprovados.

## Regras implementadas na nova branch

- Importação sem perdas das linhas: `source_fields`, `fields_original`, `fields_revised`, `field_selection_source` e pareceres individuais são preservados **apenas localmente**.
- Se a coluna revisada existe mas está vazia, o respectivo valor selecionado permanece vazio. O original não é recuperado automaticamente. Isso **não significa rejeição definitiva**; a decisão fica pendente.
- `review_state` diferencia `revised_complete`, `revised_incomplete`, `revised_all_empty` e `no_complete_review_schema`; `review_flags` aponta divergências de preenchimento.
- A auditoria categoriza desconhecidos sem trocar seus rótulos: alias conhecido, possível alias lexical, classes legadas de ENT/SEG, rótulos compostos/texto livre e não resolvidos.
- Divergências de spans são separadas em diferenças de caixa, espaços de borda, normalização Unicode e demais diferenças, sem ajustar fronteiras.
- Offsets inválidos são discriminados por razão; documentos sem chave recebem candidatos apenas por correspondência literal exata de trecho e offsets.
- Pareceres dos sete avaliadores são agrupados como `agree`, `disagree`, `not_recorded` e `other_not_interpreted`, **sem adjudicação automática**.

## Decisões pendentes de autorização

1. O tratamento semântico de `SEG_DECISAO_VOTO_VENCEDOR` e `SEG_DECISAO_VOTO_VENCIDO`, ausentes da taxonomia de 11 segmentos atual.
2. O significado de revisões inteiramente vazias, parciais e com pareceres contraditórios.
3. A aceitação/recusa de aliases sugeridos, principalmente valores compostos ou texto livre indevidamente inseridos em coluna de rótulo.
4. A resolução documentada de vínculos órfãos e fronteiras de spans, com evidências.
5. A política futura para spans aninhados e representações NER/SEG no treinamento.

**Não efetuar:** merge, exclusão de dados, adjudicação por maioria, supressão por frequência ou treinamento de modelos nesta etapa.
