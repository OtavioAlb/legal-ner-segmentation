# Arquitetura-alvo — Legal NER & Segmentation (ADR provisória)

**Status:** proposta de migração incremental; não altera adjudicação, dados nem treino.

## Decisões aprovadas
1. Pacote Python organizado por responsabilidade funcional.
2. **Spans de caracteres** como fonte de verdade; BIO/BILOU são visões derivadas e reversíveis, sob política explícita para sobreposições.
3. Pipelines Python acionados por CLI e configurados por YAML.
4. Migração incremental, com comandos legados e testes de equivalência até sua substituição.
5. Experimentos nomeados por arquitetura, não por sequência NER01/SEG02; preservar IDs históricos como metadados.
6. Comparação dos **três encoders configurados** em uma execução de orquestração, sem exigir carregamento simultâneo; orçamento e splits comparáveis.
7. Optuna para HPO e MLflow para registro de trials, folds, artefatos, versões, tempo e hardware.
8. Preferência de dispositivo TPU > CUDA > CPU, sujeita a **compatibilidade verificada**; fallback em falha de execução somente com checkpoint compatível e retomada controlada. Treino integral em CPU deve exigir confirmação/configuração explícita.

## Fluxo de dependências

```text
pipelines -> io, annotations, preprocessing, datasets, models, training, evaluation, tracking
io -> core
annotations -> core, io
preprocessing -> core
datasets -> core, preprocessing
models -> core
training -> models, datasets
evaluation -> core, datasets
tracking -> core (metadados)
```

Evitar que `core` dependa de Label Studio, MLflow, Transformers, PyTorch ou Excel.
Distinguir `annotations/reviews` (avaliação **humana**) de `evaluation` (métricas dos **modelos**).

## Pacotes-alvo, criados sob demanda
- `core/`: contratos imutáveis, IDs, estados.
- `io/`: Label Studio, Doccano, CSV, XLSX, JSONL.
- `annotations/`: proveniência, identidade, regras de checkbox, auditoria geométrica, novas regiões, adjudicação.
- `preprocessing/`: texto e alinhamento de tokens, janelamento.
- `datasets/`: corpus canônico, elegibilidade, splits, exportação NER/SEG e BIO/BILOU.
- `models/ner/`, `models/segmentation/`: famílias de arquiteturas.
- `training/`, `optimization/`, `tracking/`, `evaluation/`, `inference/`: execução, Optuna, MLflow, métricas e predição.
- `pipelines/`: orquestração; regras de negócio devem residir nos pacotes especializados.

## Segurança, reprodutibilidade e critérios de migração
- Os dados judiciais e relatórios contendo trechos ficam exclusivamente em `data/` ignorado pelo Git.
- `dataset_manifest.json` deve registrar hashes dos insumos, versão da taxonomia, regras de consolidação, commit, documentos, estados e elegibilidade.
- Preservar `idacordao`, IDs de regiões e identidades de origem/efetiva; substituições de Tiago para Teresa não devem ser confundidas com avaliações próprias.
- Nenhuma pendência vira gold automaticamente. Sobreposições de spans são permitidas.
- Um PR de refatoração só pode ser aprovado após comparar saídas determinísticas anteriores e posteriores sobre **os mesmos** exports e políticas, com testes sintéticos versionados e regressão local com dados privados.
- A divisão por documento/processo é compartilhada entre NER e segmentação. Teste final congelado não participa de HPO.
- Não alterar `main` nem fazer merge sem autorização.

## Plano de entregas
1. Inventário, documentação de contratos e testes sintéticos (este PR).
2. Extração de I/O e normalização compartilhados, wrappers legados.
3. Auditorias e adjudicação sem mudança de semântica.
4. Corpus unificado, manifestos, controle de elegibilidade e splits.
5. Configuração de experimentos por arquitetura, registry de encoders e treinamento CPU/CUDA.
6. Optuna + MLflow + comparação de três encoders sob orçamento equivalente.
7. Prova de compatibilidade TPU no Colab e fallback seguro para GPU.
