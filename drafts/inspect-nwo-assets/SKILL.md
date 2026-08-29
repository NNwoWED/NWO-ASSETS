---
name: inspect-nwo-assets
description: Diagnosticar, inventariar e explicar falhas nos assets do NWO Maps (DAT, SPR, OTB, OTBM, XML e OTML) usando a CLI nwoassets em modo somente leitura. Usar ao verificar perfil/assinaturas, integridade estrutural, relações de IDs, variantes de mapa, configuração textual ou exit codes; não usar para editar, converter, instalar, sincronizar ou publicar assets.
---

# Inspect NWO Assets

## Preservar o checkout

1. Trabalhar na raiz do `nwo-maps`.
2. Registrar `git status --short` antes e depois.
3. Tratar toda mudança preexistente como pertencente ao usuário.
4. Executar a CLI sem instalar: `python3 -m nwoassets ...`.
5. Direcionar `-o` somente a um diretório scratch autorizado. Sem `-o`, a inspeção não escreve.
6. Abortar se o pedido exigir alterar DAT, SPR, OTB, OTBM, XML, OTML, baseline ou mapas.

## Selecionar o menor diagnóstico

- Inventário e hashes: `python3 -m nwoassets scan ROOT`
- OTFI, DAT, SPR e OTB: `python3 -m nwoassets inspect-client ROOT`
- Validação completa do RLE do SPR: adicionar `--deep-spr`
- OTBM, mapas em ZIP e XMLs de `world/`: `python3 -m nwoassets inspect-world ROOT`
- XML e OTML: `python3 -m nwoassets inspect-configs ROOT`
- Diagnóstico integrado: `python3 -m nwoassets validate ROOT`

Usar `--deep-spr` para investigar corrupção de payload, validar baseline/release ou explicar divergência no SPR. Avisar que o processamento percorre todos os sprites.

## Interpretar o resultado

1. Confirmar `profile.key == tibia-860-v2-custom-extended`.
2. Confirmar que OTFI e assinaturas combinam antes de interpretar DAT/SPR.
3. Separar sempre:
   - **Client ID:** objeto/aparência lógica no DAT;
   - **Sprite ID:** imagem física 1-based no SPR; `0` no DAT é sentinela vazia;
   - **Server ID:** item no OTB, mapeado explicitamente para um Client ID.
4. Não assumir `Server ID == Client ID`: esta baseline possui relações N:1 e registros deprecated sem Client ID.
5. Tratar a flag DAT `0x22` apenas como extensão local sem payload deste perfil, observada em quatro itens. Nunca generalizar para outro DAT ou outra versão.
6. Relatar cada OTBM por caminho e hash. Não inferir equivalência entre mapas por nome, dimensões, versão ou contagem de nós.
7. Tratar XML fragmentário como fragmento; o wrapper da CLI existe apenas em memória. Tratar OTML como texto próprio, não XML.

Ler [formatos-e-ids.md](references/formatos-e-ids.md) ao explicar campos, limites do perfil ou a referência 10.41. Ler [troubleshooting.md](references/troubleshooting.md) quando houver falha, alerta ou pedido de reprodução.

## Classificar saída e falhas

- Exit `0`: inspeção executada; em `validate`, checks aprovados.
- Exit `1`: `validate` concluiu, mas ao menos um check reprovou.
- Exit `2`: formato/perfil/entrada/I/O impediu a inspeção.

Não concluir integridade apenas pelo exit code de `scan`, `inspect-client`, `inspect-world` ou `inspect-configs`; examinar `passed`, `checks`, `errors` e `warnings` quando presentes. Não silenciar erros nem trocar perfil para forçar o parse.

## Entregar o diagnóstico

Registrar:

- comando e raiz inspecionada;
- exit code;
- perfil e assinaturas;
- achados por formato, com caminhos;
- erros, alertas e limite da conclusão;
- diferença do `git status --short` antes/depois.

Se o pedido evoluir para escrita, instalação ou sincronização da skill, parar e exigir gate explícito do CEO. Esta skill não autoriza writers, mutação de assets, escolha de mapa canônico, promoção de baseline ou release.

## Verificar

Executar o menor conjunto proporcional:

```bash
python3 -m unittest discover -v
python3 -m nwoassets validate .
```

Adicionar `python3 -m nwoassets inspect-client . --deep-spr` quando a conclusão depender do payload SPR. Repetir `git status --short` e confirmar que somente artefatos previamente autorizados mudaram.
