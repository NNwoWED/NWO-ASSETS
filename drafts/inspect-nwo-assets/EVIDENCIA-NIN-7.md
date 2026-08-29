# NIN-7 — Evidência do draft `inspect-nwo-assets`

Data: 2026-07-30  
Escopo: draft somente leitura; nenhuma instalação ou sincronização executada.

## Entregáveis

- `SKILL.md`: seleção do menor comando, leitura dos exit codes, preservação do checkout e critérios de abortar.
- `agents/openai.yaml`: metadata de interface.
- `references/formatos-e-ids.md`: perfil 8.60 ativo, Client/Sprite/Server IDs, flag local `0x22`, OTBM e limites da referência 10.41.
- `references/troubleshooting.md`: triagem por formato e reproduções negativas seguras.

## Verificação

| Cenário | Resultado |
| --- | --- |
| Validação estrutural `quick_validate.py` | aprovado — `Skill is valid!` |
| `python3 -m unittest discover -v` | aprovado — 7/7 |
| `python3 -m nwoassets validate .` | exit 0; `passed: true`; zero erros |
| Assinaturas DAT/SPR misturadas | teste aprovado; `ProfileError` esperado |
| Leitura binária além do limite | teste aprovado; `FormatError` esperado |
| Raiz inexistente via CLI | exit 2 esperado |

A validação integrada confirmou `tibia-860-v2-custom-extended`, três variantes de mapa e apenas os alertas conhecidos: `items/new.xml` fragmentário e variantes distintas. Não foi executado `--deep-spr` nesta etapa porque os cenários da skill não alteram o parser e a baseline profunda já foi aprovada na revisão 2 da NIN-5.

O ambiente não continha PyYAML, dependência do validador estrutural. Para executar o validador sem instalar dependências no projeto, foi fornecido temporariamente em `PYTHONPATH` um módulo mínimo no próprio diretório do draft, suficiente apenas para ler os dois campos escalares do frontmatter; ele foi removido imediatamente após o resultado. O artefato final não contém esse helper.

## Integridade do checkout

Os nove caminhos modificados antes da execução foram preservados:

- `860/.gitattributes`
- `860/Tibia.spr`
- `items/force use.txt`
- `items/items.xml`
- `items/itemsExport.xml`
- `items/new.xml`
- `items/randomization.xml`
- `reports/validation-final.json`
- `world/mapanovo-areas.xml`

Durante a execução apareceu também `skills/triage-nwo-map-variants/`, artefato de outro ticket/agente no workspace compartilhado; não foi criado nem alterado pela NIN-7. As únicas adições desta implementação estão em `drafts/inspect-nwo-assets/`.

## Guardrails revisáveis

- A skill é somente leitura e executa a CLI sem instalar o pacote.
- A flag `0x22` fica restrita aos quatro itens comprovados do DAT ativo.
- Nenhuma equivalência entre mapas é inferida.
- A especificação 10.41 é histórica e não autoriza interpretar/escrever a baseline 8.60.
- Instalação, sincronização, writers, mutação de assets, escolha canônica e release exigem autorização posterior.
