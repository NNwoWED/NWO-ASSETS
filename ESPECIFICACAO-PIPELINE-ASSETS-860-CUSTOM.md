# Especificacao do Pipeline de Assets Tibia 8.60 Custom

## 1. Finalidade

Esta é a especificação ativa dos arquivos presentes em `NWO MAPS`. Ela adapta
os princípios de segurança da especificação 10.41 ao cliente efetivamente
encontrado na pasta.

O perfil é:

```text
tibia-860-v2-custom-extended
```

A inspeção permanece estritamente read-only. Os comandos de escrita versionam a
baseline antes de modificar os arquivos oficiais em `assets/`. A ferramenta:

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
- cria `860.rar`, `items.rar` sem XML e `world.zip` contendo somente o OTBM;
- testa os arquivos compactados antes de permitir qualquer substituição;
- importa PNGs RGBA em Client IDs de itens existentes;
- acrescenta sprites, troca apenas a aparência DAT alvo e atualiza o SpriteHash OTB;
- edita flags booleanas DAT e os 28 bits funcionais OTB por manifesto declarativo;
- inspeciona uma coordenada OTBM e resolve a pilha Server ID/Client ID;
- reabre os binários preparados e faz uma troca transacional no local;
- restaura DAT, SPR e OTB anteriores se a validação final falhar.

Os backups ficam em `versions/AAAAMMDD-HHMMSS-microssegundos/`. Arquivos XML,
OTFI, OTBM e OTML não são modificados pela importação de itens.

## 2. Baseline comprovada

| Arquivo | Bytes | SHA-256 |
| --- | ---: | --- |
| `assets/860/Tibia.dat` | 4.369.101 | `B4C7A5D5EA0D020AA9226259E74463C316C8E89CF52CC1989C05858B9873B886` |
| `assets/860/Tibia.spr` | 430.525.239 | `40FB175894C16FB6319D875612BE202D8B440B9F3CE2E787548C35660C77CC1A` |
| `assets/860/Tibia.otfi` | 185 | `7743548835944BC799CB871A4E5DEF84F7AF76815031871B9CE74B5EC0E8ADD3` |
| `assets/items/items.otb` | 1.003.370 | `CA39F2A67BA0F40E1225886982E6B63E69481303D35A48EF965407D088A2A2B5` |
| `assets/world/mapanovo.otbm` | 78.697.168 | `3F1396A9C7F1817A406897B42D163C25A73CE55E86B072E92416356C96FD3650` |

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
4       2        maxItemId = 24522
6       2        maxOutfitId = 2289
8       2        maxEffectId = 3363
10      2        maxMissileId = 219
```

Contagens:

```text
items     = 24522 - 100 + 1 = 24423
outfits   = 2289
effects   = 3363
missiles  = 219
total     = 30294 registros
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
- o parse termina exatamente no byte 4.369.101.

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

- 878.146 referências totais de sprite;
- 250.037 Sprite IDs não zero distintos;
- 313.854 referências sentinela `0`;
- Sprite IDs usados entre `1..252143`;
- maior grupo observado: 4000 sprites.

## 5. SPR

Layout:

```text
uint32 signature = 0x4C220594
uint32 spriteCount = 252143
uint32 offsets[252143]
sprite blocks...
```

A tabela termina no offset `1008580`.

Baseline observada:

- 252.143 offsets não zero;
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

- 25.308 nós de item;
- Server IDs contínuos `100..25407`;
- Client IDs até `24522`;
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

Existe uma única variante canônica do mapa:

- `assets/world/mapanovo.otbm`.

Ela declara:

```text
OTBM map version = 2
width = 3000
height = 3000
items version = 3.20
```

A versão de items coincide com o `items.otb`.

A CLI percorre todos os bytes da árvore OTBM. Foram observados 10.062.435 nós em
`mapanovo.otbm`; a árvore está balanceada.

Os arquivos auxiliares `itemsExport.xml`, `new.xml` e `randomization.xml` foram
removidos da baseline oficial. Permanecem `items.otb`, `items.xml` e
`force use.txt` em `assets/items/`.

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
nwoassets create-version [ROOT]
nwoassets import-items [ROOT] MANIFEST.csv [--deep-spr]
nwoassets edit-item-properties [ROOT] MANIFEST.csv [--deep-spr]
nwoassets inspect-map-position [ROOT] X Y Z
```

Todos aceitam:

```text
-o ARQUIVO.json
```

Exit codes:

- `0`: inspeção executada e, em `validate`, checks aprovados;
- `1`: validação concluída com erros;
- `2`: arquivo inválido, perfil desconhecido ou erro de I/O.

## 9. Versionamento e importador

`create-version` exige a estrutura `assets/860`, `assets/items` e `assets/world`.
Ele usa `rar.exe` para criar e testar `860.rar` e `items.rar`; todos os XMLs são
excluídos de `items.rar`. `world.zip` recebe exclusivamente o OTBM canônico, que é
reaberto e comparado por SHA-256. Um `version.json` registra fontes e arquivos.

`import-items` recebe um CSV UTF-8 com `sequence,client_id,source_path`. A sequência
deve começar em 1 e ser contínua; Client IDs e caminhos não podem se repetir. O PNG
deve ser RGBA 8-bit, não entrelaçado, possuir dimensões múltiplas de 32 e
medir no máximo 224×224. Esse limite mantém o `exactSize` no `uint8` do DAT. O lote:

1. normaliza alpha zero e magenta opaco como transparência;
2. separa tiles de 32×32 na ordem bottom-right-first usada pela aparência DAT;
3. codifica RLE RGBA e acrescenta novos Sprite IDs no final do SPR;
4. substitui somente a aparência dos Client IDs declarados, com `exactSize`
   igual à maior dimensão em pixels, conforme o Object Builder;
5. calcula o MD5 visual compatível com `ItemEditor/PluginInterface/Item.cs`;
6. atualiza todos os nós OTB mapeados ao Client ID, preservando relações N:1;
7. cria e testa a versão compactada antes de gerar arquivos temporários;
8. reabre DAT, SPR e OTB preparados e valida pixels, hashes, contagens e mapeamentos;
9. troca os três binários no local e executa a validação integrada;
10. restaura automaticamente os três originais se o commit ou a validação falhar.

Antes de cada lote, o algoritmo de `SpriteHash` precisa coincidir com uma amostra
determinística de 64 itens da baseline. A fase atual aceita somente Client IDs de
itens existentes (`100..24522`) e cria aparência estática com uma camada e um frame.
Criação de novos Client IDs, animações, outfits, effects e missiles continua fora
do escopo. Não existe mais pasta de staging; temporários atômicos ao lado dos
binários oficiais são apagados depois do commit ou da reversão.

### 9.1 Editor de propriedades

`edit-item-properties` usa as colunas `sequence`, `server_id`, `client_id`,
`dat_add_flags`, `dat_remove_flags`, `otb_add_flags` e `otb_remove_flags`. O Client
ID é opcional no formato, mas deve ser informado quando conhecido para validar o
mapeamento N:1 do OTB. Múltiplas flags são separadas por `|`.

No DAT, somente flags sem payload podem ser adicionadas ou removidas. Os chunks de
propriedades com payload e toda a aparência do item são preservados byte a byte.
No OTB, o editor altera somente a máscara `uint32` do nó identificado pelo Server
ID; grupo, atributos, filhos e mapeamento para Client ID permanecem iguais.

A operação cria a versão compactada obrigatória, prepara DAT e OTB ao lado dos
oficiais, reabre ambos, executa a validação integrada e usa rollback automático.
SPR, OTFI e OTBM não fazem parte do lote e devem permanecer com o mesmo SHA-256.

### 9.2 Inspetor de posição

`inspect-map-position` percorre a árvore de forma streaming e não grava o OTBM.
O relatório enumera a pilha a partir de 1, identifica itens inline e filhos,
decodifica `action_id`, `unique_id` e `count` quando presentes, e enriquece cada
Server ID com Client ID, grupo, máscara OTB e flags DAT.

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
- `https://github.com/ottools/ItemEditor/blob/master/Source/PluginInterface/Item.cs`
- `https://github.com/ottools/ItemEditor/blob/master/Source/PluginInterface/Sprite.cs`
