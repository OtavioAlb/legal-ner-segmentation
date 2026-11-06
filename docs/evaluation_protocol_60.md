# Protocolo de avaliação — corpus planejado de 60 acórdãos

Status: **planejamento aprovado como orientação, ainda não executável em 60 documentos**.
Atualmente existem apenas 25 documentos da Fase 1; os 35 adicionais ainda
precisam ser incorporados, saneados e consolidados conforme o mesmo contrato.

## Objetivo e partição

Usar 60 acórdãos, tanto para NER quanto para segmentação por spans:

| Partição | Documentos | Composição planejada |
|---|---:|---|
| Desenvolvimento (treino + validação cruzada) | 48 (80%) | 25 atuais + 23 novos |
| Teste independente, congelado | 12 (20%) | 12 dos 35 novos |
| Total | 60 | 25 atuais + 35 novos |

Racional: os 25 atuais já orientaram decisões de ingestão, saneamento e
diagnóstico; o teste entre documentos novos reduz contaminação por decisões
tomadas durante o desenvolvimento. A representatividade dos 12 novos
documentos deverá ser examinada e documentada, principalmente se houver
diferenças relevantes entre fases de anotação.

## Seleção e congelamento

1. Ingerir, auditar e sanear os 35 documentos novos usando os mesmos
   critérios determinísticos. Correções completas dos avaliadores têm
   precedência sobre a anotação original correspondente.
2. Conciliar IDs de documentos, hashes de texto e, se disponível, identidade
   **do processo judicial** entre as duas fases. Acórdãos distintos do mesmo
   processo não devem ficar em partições separadas.
3. Selecionar 12 dos 35 novos para o teste **antes de analisar resultados de
   modelos nesses documentos**. Utilizar critério reprodutível e auditar a
   representatividade; registrar IDs, algoritmo, semente e versão do corpus.
   Não escolher a partição com base em melhor desempenho posterior.
4. Congelar a partição de teste. Não usá-la para escolher arquitetura,
   hiperparâmetros, limiares, regras de tratamento ou ajustes de anotação
   motivados pelo desempenho. Dados de teste só são usados na avaliação
   final com o protocolo previamente definido.
5. Usar os 48 documentos restantes para seleção e ajustes de modelos.
   Executar validação cruzada de cinco folds, com aproximadamente
   9–10 documentos de validação e 38–39 de treino por fold. Garantir que
   cada documento participe da validação exatamente uma vez e que os
   agrupamentos por processo, quando conhecidos, permaneçam indivisíveis.
6. Escolher o modelo com base apenas na validação. Retreinar no conjunto de
   desenvolvimento de 48 documentos e avaliar uma vez nos 12 de teste.

## Folds e rótulos raros

As atuais divisões de 25 documentos em 5 folds são **diagnósticas e
provisórias**, não a configuração definitiva de avaliação.

Com 60 acórdãos deve-se auditar classes por documento e por grupo de processo,
e então comparar uma partição por grupos aleatória/reprodutível com um método
de estratificação multilabel que respeite esses grupos. Classes presentes em
um único documento ou grupo não podem ter exemplos simultaneamente em treino
e validação do mesmo fold sem vazamento. Não fabricar instâncias, não forçar
estratificação impossível e não excluir classes raras para melhorar métricas.

As 67 classes da taxonomia permanecem; a contagem de classes supervisionadas
pode aumentar com os 35 novos documentos. Reportar classes ausentes no
treinamento ou na validação de cada fold e o suporte por classe.

## Unidades de avaliação e limitações

- Uma única partição de documentos/processos para ambas as tarefas NER e SEG.
- Supervisão e predição por **spans** (intervalos de caracteres, início inclusivo,
  fim exclusivo), não BIO. Preservar sobreposições, aninhamentos e múltiplos
  rótulos válidos.
- Métrica principal candidata: F1 por correspondência exata de
  (documento, início, fim, classe), informando micro e por classe; definir
  também antes dos experimentos o tratamento de classes com suporte zero.
- Reportar média e dispersão por fold; resultados de validação são usados para
  desenvolvimento, não substituem a estimativa do teste congelado.
- Documentos distintos não garantem processos distintos. **Não afirmar
  independência por processo até existir chave de agrupamento confiável.**
- Se um processo agrupar vários acórdãos e impossibilitar exatamente 48/12,
  priorizar a integridade do grupo e documentar a proporção resultante.
- Caso novos documentos e antigos provenham de distribuições diferentes,
  registrar essa limitação; teste composto exclusivamente de documentos
  novos pode caracterizar generalização para a Fase 2.

## Condição para implementação definitiva

Não produzir agora IDs sintéticos de teste nem congelar uma partição baseada
somente nos 25 documentos. A implementação de split definitivo começa após
a incorporação dos 35 novos e a auditoria de vínculo documental/processual.
