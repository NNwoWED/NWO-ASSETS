# Especificacao do Pipeline de Assets Tibia 8.60 Custom

## 1. Finalidade

Esta é a especificação ativa dos arquivos presentes em `NWO MAPS`. Ela adapta
os princípios de segurança da especificação 10.41 ao cliente efetivamente
encontrado na pasta.

O perfil é:

```text
tibia-860-v2-custom-extended
```

A primeira fase implementada é estritamente read-only. Ela:

- inventaria e calcula SHA-256 de todos os arquivos;
- detecta o perfil pelas assinaturas DAT/SPR;
- lê e valida o OTFI;
- faz parse completo do DAT até o último byte;
- valida tabela, offsets e opcionalmente todos os blocos RLE do SPR;
- lê a árvore e os registros do `items.otb`;
- inspeciona headers OTBM, inclusive mapas dentro de ZIP;
- valida XMLs e reconhece fragmentos;
- cataloga OTML sem alterar encoding ou conteúdo;
- produz relatórios JSON e exit codes adequados.

Nenhum comando desta fase escreve em DAT, SPR, OTB ou OTBM.

## 2. Baseline comprovada

| Arquivo | Bytes | SHA-256 |
| --- | ---: | --- |
| `860/Tibia.dat` | 4.349.631 | `CB19DFE778C2DF4D89E8103B478AC4678AC8825DC6A62629A1A485B2AD46D4DA` |
| `860/Tibia.spr` | 419.687.836 | `A5F6D901DC4DF99060E5B020AA00DF6BCF0366547153C0BE090BCEA32D3FCFC6` |
| `860/Tibia.otfi` | 185 | `7743548835944BC799CB871A4E5DEF84F7AF76815031871B9CE74B5EC0E8ADD3` |
| `items/items.otb` | 996.516 | `1E150F1B8D66710AE79449165E0B237BB79E5CF37E8DE023B9F62ABDC650377E` |

Assinaturas e versões:

```text
DAT signature = 0x4C2C7993
SPR signature = 0x4C220594
Object Builder version = 8.60 v2
metadata layout = MetadataReader5, com extensão local documentada abaixo
OTB = 3.20.20-8.60
```

As assinaturas `0x5383504E` e `0x53835077` pertencem ao perfil 10.41 e devem ser
rejeitadas neste perfil.

## 3. OTFI ativo

```text
DatSpr
  extended: true
  transparency: true
  frame-durations: true
  frame-groups: true
  metadata-file: Tibia.dat
  sprites-file: Tibia.spr
  sprite-size: 32
  sprite-data-size: 4096
```

Embora a assinatura seja 8.60, os arquivos são customizados e usam:

- contagem SPR em `uint32`;
- Sprite IDs DAT em `uint32`;
- canal alpha no RLE;
- durações de frame;
- frame groups de outfits.

Por isso o diretório `860` ou a versão nominal não bastam para interpretar o
arquivo. O OTFI é obrigatório.

## 4. DAT

### 4.1 Header observado

```text
offset  tamanho  campo
0       4        signature = 0x4C2C7993
4       2        maxItemId = 24358
6       2        maxOutfitId = 2285
8       2        maxEffectId = 3363
10      2        maxMissileId = 216
```

Contagens:

```text
items     = 24358 - 100 + 1 = 24259
outfits   = 2285
effects   = 3363
missiles  = 216
total     = 30123 registros
```

As categorias são sequenciais, sem tabela de offsets.

### 4.2 Flags MetadataReader5

As flags padrão comprovadas são `0x00..0x21` e `0x27`, com `0xFF` como
terminador. Os payloads seguem `MetadataReader5` do Object Builder:

- `0x00`, `0x08`, `0x09`, `0x19`, `0x1C`, `0x1D`, `0x20`: `uint16`;
- `0x15`: dois `uint16`;
- `0x18`: dois `int16`;
- `0x21`: market structure variável;
- `0x27`: oito `int16`;
- as demais flags padrão não possuem payload.

### 4.3 Extensão local 0x22

Esta baseline usa a flag `0x22` quatro vezes, nos items `100`, `4812`, `4814` e
`20227`, sem payload, imediatamente antes de outra flag ou de `0xFF`.

Essa semântica não está no `MetadataReader5` oficial. A CLI a modela como
`custom_flag_22` somente dentro deste perfil. A evidência estrutural é que:

- o parse de todas as categorias permanece sincronizado;
- todos os campos de aparência são válidos;
- todas as referências cabem no SPR;
- o parse termina exatamente no byte 4.349.631.

Não generalizar essa regra para outro DAT 8.60.

### 4.4 Aparência

A estrutura segue as features OTFI:

```text
para outfits:
    uint8 frameGroupCount
    para cada grupo:
        uint8 frameGroupType

uint8 width
uint8 height
if width > 1 or height > 1:
    uint8 exactSize
uint8 layers
uint8 patternX
uint8 patternY
uint8 patternZ
uint8 frames
if frames > 1:
    uint8 animationMode
    int32 loopCount
    int8 startFrame
    repeat frames:
        uint32 minimumDuration
        uint32 maximumDuration
repeat produto-das-dimensoes:
    uint32 spriteId
```

O produto das dimensões não pode ultrapassar 4096.

Estado observado:

- 874.016 referências totais de sprite;
- 244.663 Sprite IDs não zero distintos;
- 314.374 referências sentinela `0`;
- Sprite IDs usados entre `1..245380`;
- maior grupo observado: 4000 sprites.

## 5. SPR

Layout:

```text
uint32 signature = 0x4C220594
uint32 spriteCount = 245380
uint32 offsets[245380]
sprite blocks...
```

A tabela termina no offset `981528`.

Baseline observada:

- 245.380 offsets não zero;
- nenhum offset compartilhado;
- nenhum offset fora do arquivo;
- nenhum payload de tamanho zero;
- nenhuma chave de cor divergente;
- nenhum bloco RLE truncado ou acima de 1024 pixels.

Cada pixel colorido possui RGBA porque `transparency: true`.

## 6. OTB

O header é:

```text
major = 3
minor = 20
build = 20
csd = OTB 3.20.20-8.60
```

Foram observados:

- 25.144 nós de item;
- Server IDs contínuos `100..25243`;
- Client IDs até `24358`;
- múltiplos Server IDs podem apontar para o mesmo Client ID;
- registros deprecated podem não possuir Client ID.

Portanto, a regra usada no projeto 10.41:

```text
Server ID == Client ID
```

não é válida para esta baseline e nunca deve ser aplicada globalmente.

Uma futura escrita OTB precisa preservar cada nó, flags, atributos, relações
N:1 e `SpriteHash`.

## 7. Mapas e configurações

Existem três variantes binariamente diferentes do mapa:

- `world/mapanovo.otbm`;
- `world/mapanovo 8.otbm`;
- `mapanovo.otbm` dentro de `world/mapanovo.zip`.

As três declaram:

```text
OTBM map version = 2
width = 3000
height = 3000
items version = 3.20
```

A versão de items coincide com o `items.otb`.

A CLI percorre todos os bytes das árvores OTBM. Foram observados 9.663.813 nós
em `mapanovo 8.otbm`, 9.663.814 em `mapanovo.otbm` e 9.663.813 na cópia do ZIP;
as três árvores estão balanceadas.

`items/new.xml` é um fragmento com múltiplas raízes, não um documento XML
standalone. A CLI o envolve apenas em memória para inspeção.

Os arquivos `.otml` são tratados como configuração textual própria. Não devem
ser passados para um parser XML.

## 8. CLI

Comandos implementados:

```text
nwoassets scan [ROOT]
nwoassets inspect-client [ROOT] [--deep-spr]
nwoassets inspect-world [ROOT]
nwoassets inspect-configs [ROOT]
nwoassets validate [ROOT] [--deep-spr]
```

Todos aceitam:

```text
-o ARQUIVO.json
```

Exit codes:

- `0`: inspeção executada e, em `validate`, checks aprovados;
- `1`: validação concluída com erros;
- `2`: arquivo inválido, perfil desconhecido ou erro de I/O.

## 9. Próxima fase: importação

Antes de habilitar escrita:

1. congelar fixtures/golden dos quatro arquivos;
2. criar writer DAT Metadata5 com a extensão local isolada;
3. fazer round-trip byte a byte sem mudanças;
4. implementar split e montagem de PNGs 32x32;
5. anexar blocos SPR sem modificar os existentes;
6. obter o `SpriteHash` pelo Item Editor/plugin usado por esta base;
7. preservar o mapeamento Server ID/Client ID existente;
8. escrever somente em staging;
9. reabrir e validar todos os temporários;
10. testar uma cópia do mapa real no RME.

Até esses critérios serem satisfeitos, a CLI deve continuar read-only.

## 10. Fontes de verdade

Ordem de autoridade:

1. arquivos locais que abrem no RME/cliente do projeto;
2. parse completo e checks binários desta CLI;
3. Object Builder, `versions.xml` e `MetadataReader5`;
4. fonte do RME;
5. documentação histórica 10.41, apenas para princípios comuns.

Referências:

- `https://github.com/punkice3407/ObjectBuilder`
- `https://github.com/OTAcademy/RME`
