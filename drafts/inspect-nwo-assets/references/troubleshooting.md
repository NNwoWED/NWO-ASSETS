# Troubleshooting e reproduções seguras

Todas as reproduções abaixo operam em cópias dentro de um diretório scratch. Nunca truncar ou editar o checkout.

## Perfil ou assinatura incompatível — exit 2

Sintoma: `erro:` menciona perfil desconhecido, assinaturas incompatíveis ou versão não suportada.

Diagnóstico:

1. Executar `python3 -m nwoassets inspect-client ROOT`.
2. Conferir DAT signature, SPR signature e OTFI como conjunto.
3. Não renomear a pasta nem substituir uma assinatura isolada para “forçar” o perfil.

Reprodução mínima coberta pela suíte:

```bash
python3 -m unittest tests.test_formats.ProfileTests.test_rejects_mixed_signatures -v
```

## Arquivo binário truncado — exit 2

Para uma reprodução controlada, copiar a estrutura necessária para um scratch e truncar somente a cópia do arquivo sob investigação. Executar o subcomando correspondente e esperar exit `2`, sem alegar qual formato falhou até ler stderr. Para grandes SPR/OTBM, preferir fixtures unitárias ou cópias reflink quando disponíveis. Nunca executar `truncate` contra um caminho do checkout.

O teste de bounds fornece uma reprodução mínima de leitura binária truncada:

```bash
python3 -m unittest tests.test_formats.BinaryReaderTests.test_little_endian_and_bounds -v
```

## Validate reprovado — exit 1

Sintoma: a inspeção termina e gera JSON, mas `passed` é `false`.

Ler `errors` e cada entrada de `checks`; não converter automaticamente em “arquivo ilegível”. Exit 1 representa inconsistência detectada após parse, enquanto exit 2 representa impedimento de formato/perfil/I-O.

## XML fragmentário

`fragment: true` pode ser esperado para `items/new.xml`. Confirmar caminho, encoding, raízes e tags. Não persistir o wrapper usado em memória e não reformatar o arquivo.

Erro de XML fora de um fragmento conhecido deve ser relatado com caminho e parser; não assumir que Latin-1, UTF-8 ou múltiplas raízes são intercambiáveis.

## OTML com mojibake ou estrutura inesperada

Executar `inspect-configs`, observar encoding, `mojibake_marker_count` e seções de topo. A inspeção é textual e não prova semântica de jogo. Não passar OTML a parser XML nem normalizar encoding como parte do diagnóstico.

## SPR: offsets válidos, payload suspeito

O modo normal não percorre todo RLE. Executar:

```bash
python3 -m nwoassets inspect-client ROOT --deep-spr
```

Relatar truncamentos, RLE inválido, payload vazio e divergências de color key. Um header/tabela válido não prova payload válido.

## OTB: IDs ou atributos

Relatar separadamente:

- versão CSD;
- nós e grupos;
- Server IDs duplicados/lacunas;
- Client IDs duplicados;
- atributos desconhecidos ou malformados.

Client IDs duplicados no OTB podem representar relações N:1; não “corrigir” para identidade.

## OTBM: variantes

Comparar caminho, SHA-256, versão, dimensões, versão de items, balanço da árvore e contagem de nós. Mesmo resultados iguais nesses campos não autorizam declarar os mapas equivalentes. A escolha canônica é decisão explícita de produto/release.

## Evidência de não mutação

Capturar antes e depois:

```bash
git status --short
```

Comparar a lista exata, sem limpar ou restaurar mudanças preexistentes. Se `-o` for necessário, usar scratch e registrar o destino.
