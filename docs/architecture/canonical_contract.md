# Contratos canônicos — versão de proposta 0.1

O código em `legal_nlp.core.contracts` introduz tipos mínimos **sem alterar pipelines atuais**.

## Entidades
- `Document`: id estável da decisão, texto preservado, fonte; hash SHA-256 calculado do texto UTF-8.
- `Span`: id da região, id do documento, tarefa `NER` ou `SEG`, label, `start`, `end` exclusivo e texto selecionado. Não restringe sobreposição com outros spans.
- `AnnotationRecord`: span + identificadores de origem e de autor, estado canônico de adjudicação e indicação de revisão.
- `AdjudicationStatus`: `consolidated`, `pending_review`, `rejected`, `excluded_invalid`.

## Invariantes
- Offsets são índices de caracteres Python sobre o texto **exato** do documento canônico.
- `start >= 0`; `end > start`; o texto do span, quando fornecido, deve corresponder ao intervalo. A validação frente ao documento integral fica na etapa de ingestão/saneamento, pois spans inválidos de fontes originais **não podem ser apagados**.
- Não usar `region_id` isoladamente como chave global: a identidade completa inclui documento e fonte/projeto, e propostas novas usam proveniência própria.
- `adjudication_status` é distinto de checkbox, de diagnóstico de auditoria e de elegibilidade para treino.
- Não converter automaticamente avaliações sem checkbox em decisões humanas explícitas.
- Preservar o rótulo original quando a taxonomia precisar de mapeamento; não declarar casos ambíguos como resolvidos.
- BIO/BILOU é derivado em `datasets/` com regras explícitas para conflitos/overlaps; não é persistido como verdade canônica.

## Limites desta primeira implementação
Os contratos são deliberadamente **mínimos**. Resolver a estrutura completa de `provenance`, a taxonomia de motivos e os formatos persistidos será parte do PR de corpus unificado, com versionamento de esquema e migração testada.

Nenhum dado real acompanha estes contratos no Git.
