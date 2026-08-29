---
name: validate-nwo-assets
description: Executar validação integrada e somente leitura da baseline de assets do Ninja World Online, incluindo DAT, SPR, OTB, OTBM, XML e OTML. Usar quando pedirem para validar o nwo-maps, conferir a integridade do cliente e do mundo, gerar evidência de baseline ou executar um gate técnico antes de release de conteúdo.
---

# Validate NWO Assets

Validar sem editar, corrigir, extrair ou reformatar assets. Tratar o checkout como
entrada imutável e gravar toda saída em scratch.

## Fluxo obrigatório

1. Confirmar com o solicitante qual é a raiz do `nwo-maps`.
2. Ler [references/baseline-860.md](references/baseline-860.md) antes de interpretar
   assinaturas, perfil ou avisos.
3. Abortar se a raiz não existir, não contiver `nwoassets/` ou não for um checkout
   Git. Não tentar reparar a entrada.
4. Executar:

   ```bash
   scripts/run-validation.sh <raiz>
   ```

5. Em gate de release ou quando houver pedido explícito de inspeção integral do
   SPR, acrescentar `--deep-spr`. Informar que essa opção percorre todos os blocos
   RLE e pode ser significativamente mais lenta.
6. Preservar o relatório no caminho de scratch informado pelo runner. Anexá-lo ao
   issue quando a validação fizer parte de uma decisão ou gate.
7. Reportar separadamente:
   - código de saída;
   - `passed`, erros e avisos;
   - perfil e assinaturas detectadas;
   - resultado dos testes;
   - prova de que o status Git permaneceu idêntico.

## Códigos e decisão

- `0`: testes e validação passaram; o status Git permaneceu idêntico.
- `1`: a CLI concluiu e encontrou erro de validação.
- `2`: raiz, formato, perfil, I/O ou pré-condição inválida.
- `3`: o runner detectou alteração no status Git.

Não converter aviso em aprovação de produto. Três variantes de mapa, XML tratado
como fragmento ou qualquer divergência de procedência exigem decisão explícita.

## Limites e abort conditions

- Nunca escrever relatório, cache ou bytecode no checkout.
- Nunca alterar DAT, SPR, OTB, OTBM, XML ou OTML.
- Nunca escolher automaticamente a variante canônica do mapa.
- Nunca misturar assinaturas 8.60 e 10.41 nem tentar adivinhar um perfil.
- Abortar e escalar se o status Git mudar, mesmo quando a validação passar.
- Abortar e reportar o stderr original se testes ou CLI retornarem código não zero.
- Não instalar, sincronizar ou publicar esta skill sem gate executivo específico.

Usar `--skip-tests` somente quando o solicitante pedir explicitamente uma
revalidação rápida e houver evidência recente dos mesmos testes no mesmo commit.
