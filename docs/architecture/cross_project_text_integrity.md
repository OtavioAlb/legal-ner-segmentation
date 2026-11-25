# Integridade textual entre os três projetos do Label Studio

## Por quê
O diagnóstico das 23 divergências residuais foi calculado contra o texto
`data.acordao` do projeto original. Antes de classificar as nove regiões
como erro de anotação, verificar se os projetos 11 e 17 possuem **exatamente**
o mesmo conteúdo, em Unicode e quebras de linha, do projeto original.

## Comando PowerShell
```powershell
git fetch origin
git switch fix/phase2-cross-project-text-integrity
git pull --ff-only
python -m pytest tests/unit/test_cross_project_text_integrity.py -v
python -m pytest -q

python -m legal_nlp.datasets.cross_project_text_integrity `
  --original "data/raw/phase_2/project-anotation-at-2026-09-23-13-29-8041568a.json" `
  --evaluation-11 "data/raw/phase_2/project-11-at-2026-11-16-19-26-8e88e5ca.json" `
  --evaluation-17 "data/raw/phase_2/project-17-at-2026-11-16-19-26-e84e7244.json" `
  --output "data/interim/phase_2/cross_project_text_integrity.json"
```

O CLI imprime as contagens de documentos com texto idêntico e de documentos
com texto diferente, além dos IDs discrepantes. O JSON mantém hashes e
comprimentos por projeto, **sem o texto**. O comando não altera dados e
recusa sobrescrever relatórios.

## Interpretação
- Se os três hashes forem idênticos em cada acórdão, as divergências
  `value.text` versus `document[start:end]` são internas às regiões
  exportadas e não resultam de divergência do texto integral entre projetos.
- Se houver hashes diferentes, analisar versões de documento/projeto antes
  de atribuir erro às regiões ou confiar nos offsets entre exports.
- Hash idêntico **não** prova que a anotação ou o checkbox sejam corretos.
- Não usar tolerância geométrica de 10 caracteres nesta comparação.
