# Evidência — NIN-6 validate-nwo-assets

Data: 2026-07-30  
Escopo: draft somente leitura, sem instalação ou sincronização.

## Estrutura

- `quick_validate.py`: `Skill is valid!`
- `bash -n`: runner e harness aprovados.
- Frontmatter contém somente `name` e `description`.
- Recursos: runner determinístico, referência da baseline e harness de cenários.

O ambiente não possuía o módulo PyYAML. O `quick_validate.py` foi executado com
um adaptador efêmero de `yaml.safe_load` limitado ao frontmatter simples desta
skill; nenhum arquivo foi criado para o adaptador.

## Testes do runner

Comando:

```text
drafts/validate-nwo-assets/scripts/test-run-validation.sh /workspaces/nwo-maps
```

Resultado:

```text
PASS missing-root (2)
PASS mixed-signature (2)
PASS nonzero-command (7)
PASS baseline-success (0)
PASS git-status-stable
```

O cenário de assinatura mista combinou DAT `0x4C2C7993` com SPR `0x53835077` e
foi rejeitado como perfil desconhecido, com código `2`. O cenário de comando não
zero propagou o código sintético `7`.

## Forward-test independente

Um agente sem o contexto da implementação usou a skill com o pedido:

```text
validar /workspaces/nwo-maps sem alterar o checkout
```

Resultado:

- exit code `0`;
- `passed: true`;
- `errors: 0`;
- `warnings: 2`;
- testes aprovados;
- `git_status_unchanged: true`;
- perfil `tibia-860-v2-custom-extended`;
- DAT `0x4C2C7993`, 30.123 registros;
- SPR `0x4C220594`, 245.380 sprites;
- OTB `OTB 3.20.20-8.60`, 25.144 nós.

Avisos preservados, sem convertê-los em aprovação:

1. `items/new.xml` tratado como fragmento;
2. três variantes distintas de mapa.

Relatório bruto do forward-test:
`$PAPERCLIP_RUN_SCRATCH_DIR/validate-nwo-assets.KwKis7/validation.json`.

## Imutabilidade e limites

O runner comparou snapshots NUL-delimited de
`git status --porcelain=v1 --untracked-files=all` antes e depois. O harness e o
forward-test confirmaram igualdade byte a byte. O checkout já possuía alterações
preexistentes; nenhuma foi tocada.

O draft não contém writer, não altera DAT/SPR/OTB/OTBM/XML/OTML, grava saída
apenas em scratch por padrão e bloqueia instalação/sincronização até novo gate
executivo.
