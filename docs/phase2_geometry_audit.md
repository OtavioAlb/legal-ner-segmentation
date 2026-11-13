# Auditoria estrutural determinística da Fase 2

**Objetivo:** reproduzir as oito abas de auditoria com os três JSONs de Label Studio, sem editar arquivos originais nem tomar decisões semânticas de gold.

## Regra

1. Identificar regiões originais por `(idacordao, region_id)`. Repetições de `label/start/end` com ID distinto continuam sendo registros distintos.
2. Preservar as três informações originais (`label_original`, `start_original`, `end_original`) em todas as linhas.
3. Duas avaliações com a mesma tripla `(label,start,end)` e mesmo ID original: `CONCORDANCIA_ORIGINAL` se essa tripla é igual à original; `CONCORDANCIA_ALTERACAO` se for diferente. Neste último caso os valores coincidentes são armazenados somente em `label_proposta_concordante`, `start_proposta_concordante`, `end_proposta_concordante`. **Nunca reescrever o original.**
4. Checkboxes (`Certo`, `Incorreto`, `Limite impreciso`) e observações permanecem disponíveis, porém **não entram** no cálculo de concordância estrutural. Esta métrica não é concordância interavaliadores Cohen Kappa, adjudicação ou validação de qualidade.
5. Nova região: ID não presente nas anotações originais. Agrupar propostas exatas `(idacordao,label,start,end)` em `Revisao_novas`, mantendo todos os IDs de cada avaliador e sinalizando quando a mesma geometria já existe no original. Propostas novas **não** entram no gold.
6. Documentos ainda associados a Teresa (`completed_by=10`), sem substituição verificada, permanecem pendentes. Nas exportações de 13/11, quando `completed_by=10`, `updated_by=3` e existem choices, a tarefa é considerada substituída por Tiago; os metadados são preservados. Esta regra específica da versão deve ser revista caso o fluxo de edição do Label Studio mude.
7. A auditoria exige os mesmos `idacordao` nas três exportações, uma anotação ativa por tarefa e offsets válidos. Falhas devem interromper a execução.

## Execução em Windows PowerShell

Na branch `feature/phase2-deterministic-provenance-audit`:

```powershell
git pull --ff-only
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m pytest tests/test_phase2_geometry_audit.py -v
python -m pytest -v

python -m legal_nlp.phase2_geometry_audit `
  --original "data/raw/phase_2/project-anotation-at-2026-09-23-13-29-8041568a.json" `
  --evaluation-11 "data/raw/phase_2/project-11-at-2026-11-13-12-23-262f541c.json" `
  --evaluation-17 "data/raw/phase_2/project-17-at-2026-11-13-12-25-dcc0282b.json" `
  --output "data/interim/phase_2/geometry_audit_2026-11-13" `
  --xlsx
```

**Saídas locais**: `summary.json` (inclui hashes SHA-256), oito CSVs denominados por aba e `fase2_auditoria_geometria.xlsx`. A planilha Excel usa dependência opcional `openpyxl`, disponível no extra `.[dev]`. Sem `--xlsx`, apenas CSVs e JSON são necessários, sem dependências extras.

Não incluir JSONs, planilhas ou dados judiciais no GitHub público. A branch não efetua merges para `main`.

## Contagem de referência, exportações de 13/11/2026

Rodada local com os três arquivos de entrada disponíveis:

| Métrica | Valor |
|---|---:|
| Acórdãos | 35 |
| Regiões originais | 1442 |
| Concordância com original | 1176 |
| Concordância com alteração proposta pelos dois avaliadores | 3 |
| Originais pendentes | 263 |
| Candidatos novos distintos por geometria | 556 |
| Propostas novas coincidentes entre projetos | 67 |
| Acórdãos ainda aguardando Tiago | 6 |

Os números só são comparáveis quando os hashes da execução forem os mesmos. Os valores são **estruturais**, não gold. Não há garantia de concordância humana independente se um avaliador copiou spans ou se a edição tiver múltiplas autorias não discriminadas pelo export.

**SHA-256 de referência:**

- original: `022d20bc88d21107f046652fe08f84aac039bf39f1a3e2a12d41972db0951fdd`
- projeto 11: `166b7cb85473d0242380802e674ea2d430dd96fcfa807941ddb5487e68db599f`
- projeto 17: `87ccadbbcd93252d66a9babd752c8f312fce123211021b6d0f96fd850f17aa2b`
