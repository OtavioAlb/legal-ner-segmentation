# Auditoria Fase 2 — Excel único e decisões divergentes

O módulo `legal_nlp.phase2_audit_v2` lê três exportações Label Studio e gera **um único arquivo XLSX**, contendo nove abas:
`Resumo`, `Motivos_pendencia`, `Revisao_originais`, `Revisao_novas`, `Consolidados`, `Divergencia_checkbox`, `Duplicatas_exatas`, `Por_acordao` e `Instrucoes`.

### Regras

- A anotação original é imutável. A identidade é `(idacordao, region_id)`. Campos originais são mantidos como `label_original`, `start_original`, `end_original`.
- Colunas na ordem: **original completo** (incluindo ID e nome do anotador), **projeto 11 completo**, **projeto 17 completo**, resultado da auditoria. Após ID do avaliador aparece nome do avaliador.
- Se a região tem mesma geometria `(label,start,end)` nos dois projetos mas decisões normalizadas diferentes, é `DIVERGENCIA_CHECKBOX`, removida de `Consolidados` e listada na aba própria. `correto_automatico` é normalizado a `correto` somente na comparação.
- Sem checkbox: `correto_automatico` se label e offsets se mantêm; `incorreto_automatico` se o label mudou (mesmo com offset alterado); `limite_impreciso_automatico` se apenas os offsets mudaram. A decisão explícita prevalece quando existe. Esses são diagnósticos estruturais, **não** prova semântica.
- Região com ID inexistente no original: `nova_regiao` (criação humana), agrupada para conferência quando tripla coincide; não entra nos consolidados.
- Substituição: exportação com `completed_by=10`, `updated_by=3` e choices explícitas tem nome do avaliador exibido como **substituição**; o ID exibido é 3. As outras seis tarefas ainda de Teresa não têm concordância consolidada.
- Divergências de geometria e ausências também não consolidam. Concordância de duas avaliações diferentes do original é registrada apenas como **proposta concordante**, sem alteração do original.
- Não equivale a adjudicação gold nem Cohen Kappa.

### Execução (PowerShell)

```powershell
git switch feature/phase2-deterministic-provenance-audit
git pull --ff-only
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m pip install artifact-tool
python -m pytest tests/test_phase2_audit_v2.py -v
python -m pytest -v

python -m legal_nlp.phase2_audit_v2 `
 --original "data/raw/phase_2/project-anotation-at-2026-09-23-13-29-8041568a.json" `
 --evaluation-11 "data/raw/phase_2/project-11-at-2026-11-13-12-23-262f541c.json" `
 --evaluation-17 "data/raw/phase_2/project-17-at-2026-11-13-12-25-dcc0282b.json" `
 --output "data/interim/phase_2/fase2_auditoria_deterministica_checkbox_2026-11-13.xlsx"
```

Os caminhos de entrada devem ser ajustados à posição real dos JSONs no computador. O pacote `artifact_tool` precisa estar instalado no ambiente para exportar XLSX; confira a disponibilidade do pacote conforme o ambiente. Os três JSONs permanecem intactos. **Não enviar dados judiciais ao repositório público.**

### Rodada de referência, exportações de 13/11/2026

- 35 documentos, 1.442 regiões originais.
- 1.056 concordâncias iguais ao original e 2 propostas coincidentes de alteração **sem divergência de checkbox**: 1.058 registros na aba Consolidados.
- 121 regiões com mesma geometria, mas decisões divergentes, isoladas em `Divergencia_checkbox`.
- 384 regiões originais não consolidadas, incluindo 121 isoladas; 556 propostas novas pendentes; 940 pendências totais.
- Seis acórdãos aguardam substituição da avaliação de Teresa.

Recontar diretamente com este código e as entradas mais recentes; nunca ajustar os resultados para corresponder à rodada de referência.

### Ajustes de apresentação de 13/11/2026

- A coluna redundante `projeto_11_checkbox_original` / `projeto_17_checkbox_original` foi retirada. Os valores explícitos e inferidos permanecem nas colunas `projeto_*_decisao`.
- A aba `Revisao_novas` agora tem **uma linha por ID de região nova e avaliador**, com `projeto_avaliacao`, `avaliador_id`, `avaliador_nome`, `region_id_nova`, `label`, `start`, `end`, `decisao` e `observacao`. Quando outro projeto propõe geometria idêntica, os IDs aparecem em `mesma_geometria_outro_projeto_ids`, sem confundir autoria.
- Na exportação de referência, há **635 registros individuais de novas regiões** contra **556 grupos geométricos distintos** na versão anterior. Há 134 registros individuais que têm correspondência geométrica no outro projeto; esses 134 registros não equivalem a 134 grupos distintos (67 grupos tinham propostas dos dois projetos). Os 1.058 consolidados originais e 121 conflitos de checkbox não mudaram.
- O total `pendencias_totais` na aba Resumo agora soma **registros individuais**, não grupos: 384 originais + 635 novas regiões = 1.019. Não comparar diretamente às 940 pendências da versão com novas agrupadas.


### Consolidação automática de novas regiões (13/11/2026)

Uma nova região pode ser consolidada automaticamente **uma única vez**, mantendo as duas propostas separadas, quando todos os critérios ocorrerem:

1. A região não possui o mesmo `region_id` no original e a tripla `(label,start,end)` não existe no original do acórdão.
2. Há exatamente uma nova proposta do projeto 11 e exatamente uma do projeto 17 com a mesma tripla no mesmo acórdão.
3. Os avaliadores efetivos são distintos e a substituição de Teresa já foi concluída na tarefa.
4. Em caso de duplicatas dentro de um projeto, coincidência com original ou ausência de substituição, **não consolidar**.

A região consolidada recebe `canonical_region_id = "new_" + SHA256(JSON([idacordao,label,start,end]))[:20]`. O ID canônico é determinístico e não substitui `projeto_11_region_id` e `projeto_17_region_id`, que preservam a autoria original. Os IDs de origem são reproduzidos também em `region_id_original_projeto_11` e `region_id_original_projeto_17` dentro de `Consolidados`. Não existe `region_id_original` para essas novas regiões.

A aba `Revisao_novas` continua apresentando uma linha por proposta e avaliador. Propostas aprovadas estruturalmente recebem status `CONSOLIDADA_NOVA` e o mesmo `canonical_region_id`. **Não é adjudicação humana nem prova de correção semântica**.

Contagens da rodada com os três JSONs (13/11/2026):
- Regiões originais consolidadas: **1.058**.
- Novas regiões consolidadas: **67** pares únicos (134 registros individuais de origem).
- Total na aba `Consolidados`: **1.125**.
- Novas propostas individuais: **635**, das quais **501** continuam pendentes.
- Originais pendentes: **384** (incluem 121 conflitos de checkbox isolados).
- Pendências totais por registros individuais: **885**.
- Seis acórdãos aguardando conclusão da substituição de Teresa.

Para conferir: o número de novas consolidadas na aba `Consolidados` deve ser exatamente metade dos registros `CONSOLIDADA_NOVA` da aba `Revisao_novas`; os dois IDs originais e o ID canônico devem permitir junção sem perda de autoria.
