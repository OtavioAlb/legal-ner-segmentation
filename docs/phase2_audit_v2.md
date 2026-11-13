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
