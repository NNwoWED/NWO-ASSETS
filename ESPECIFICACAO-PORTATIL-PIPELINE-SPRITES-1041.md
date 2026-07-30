# Especificacao Portatil do Pipeline de Sprites Tibia 10.41

> **Aviso para este workspace:** os arquivos em `860/` nao sao 10.41. Eles
> foram identificados como Tibia 8.60 v2 customizado. A especificacao ativa e
> `ESPECIFICACAO-PIPELINE-ASSETS-860-CUSTOM.md`. Este documento permanece como
> referencia historica e nao deve ser usado para escrever nos binarios atuais.

## 1. Finalidade

Este documento concentra o conhecimento necessario para reconstruir, em outra
maquina e com ajuda do Codex, um conjunto de ferramentas capaz de:

- inspecionar clientes Tibia 10.41 em `DAT`, `SPR`, `OTFI` e `OTB`;
- reservar Client IDs vazios no `DAT`;
- importar PNGs de dimensoes multiplas de 32 pixels;
- ajustar automaticamente a estrutura visual `width x height` do objeto;
- anexar Sprite IDs no `SPR` sem alterar sprites existentes;
- substituir somente a aparencia de Client IDs, preservando flags/propriedades;
- registrar ou atualizar os itens correspondentes no `items.otb`;
- recalcular o `SpriteHash` exigido pelo Item Editor;
- remover com seguranca um sufixo de Client IDs, Sprite IDs e Server IDs;
- validar o resultado no nivel binario, semantico, visual, no Item Editor e no RME;
- instalar o conjunto final com backup e verificacao por hash.

O objetivo principal e importar apenas texturas. Propriedades funcionais, tags,
nomes e configuracoes de gameplay nao devem ser alterados. A unica mudanca
permitida no registro DAT de um item existente e a estrutura visual e sua lista
de Sprite IDs.

O documento descreve o algoritmo final. Tentativas intermediarias que falharam
sao mantidas apenas na secao de erros, para impedir que sejam repetidas.

## 2. Escopo e premissas

O alvo comprovado e a base customizada 10.41 deste projeto:

- sprite fisico: `32x32` pixels;
- DAT signature: `0x5383504E`;
- SPR signature: `0x53835077`;
- `extended: true`;
- `transparency: true`;
- `frame-durations: true`;
- `frame-groups: true`;
- metadata DAT no layout 10.10 a 10.56, `MetadataReader6/Writer6`;
- OTB identificado como `OTB 3.55.1-10.41`;
- itens DAT e Server IDs OTB representados em 16 bits;
- Windows como ambiente operacional do Item Editor e RME.

Nao generalize silenciosamente esse codigo para outro cliente. Para outra versao,
assinatura, tamanho fisico de sprite ou conjunto de features, crie um perfil
separado e fixtures proprias.

## 3. Fontes de verdade

Ordem de autoridade usada na engenharia reversa:

1. arquivos finais abertos com sucesso no RME e no Item Editor;
2. comportamento reproduzido no Object Builder local 0.5.6;
3. fonte oficial Object Builder v0.5.6, commit
   `4183e751e40cb7c2eab75675ab4fdfbafeb270d7`;
4. fonte do RME para o carregamento DAT/SPR;
5. bytes, relatorios e hashes gerados nos experimentos;
6. documentacao externa, somente como complemento.

Referencias publicas principais:

- Object Builder: `https://github.com/punkice3407/ObjectBuilder`
- release 0.5.6: `https://github.com/punkice3407/ObjectBuilder/releases/tag/v0.5.6`
- RME `graphics.cpp`:
  `https://github.com/OTAcademy/RME/blob/master/source/graphics.cpp`

## 4. Estado final comprovado

O conjunto ativo corrigido possui:

| Arquivo | Bytes | SHA-256 |
| --- | ---: | --- |
| `Tibia.dat` | 1.121.333 | `D8F0C52655D9A12EEEB45E14936152D794CAF552D6C986E923E362D4F2A1B8AF` |
| `Tibia.spr` | 91.852.145 | `FE7D750CD88A80CC664682F84EE3325A587257CB5D52CB5CB2E16526C619FA54` |
| `Tibia.otfi` | 185 | `7743548835944BC799CB871A4E5DEF84F7AF76815031871B9CE74B5EC0E8ADD3` |
| `items.otb` | 2.472.963 | `31368BA24CE11B4161AE5C6730F58B5E5A8F869F7FAF398D4F67EA97F9E049E0` |

Contagens finais:

- Client IDs de item: `100..64782`;
- quantidade de registros de item DAT/OTB: `64782 - 100 + 1 = 64683`;
- outfits: `752`;
- effects: `1`;
- missiles: `1`;
- soma usada pelo RME: `64782 + 752 = 65534`;
- Sprite IDs: `1..52337`;
- Server IDs OTB: `100..64782`, sem lacunas;
- assets importados retidos: `1915`, Client IDs `62868..64782`.

O teste funcional final abriu um mapa `.otbm` real no RME. Esse passo e
obrigatorio: observar apenas o splash, o processo ou a janela inicial nao valida
o carregamento completo dos assets.

## 5. Glossario e separacao de IDs

### 5.1 Client ID

Identifica um objeto no `Tibia.dat`. Itens comecam no ID `100`. A lista de itens
e sequencial e nao possui tabela de offsets. O header guarda o maior ID, nao a
quantidade aritmetica de registros.

### 5.2 Sprite ID

Identifica uma imagem fisica no `Tibia.spr`. E um espaco independente do Client
ID. O Sprite ID e 1-based; o valor `0` dentro do DAT e sentinela de imagem vazia.

### 5.3 Server ID

Identifica o item no `items.otb`. Nesta base o mapeamento usado para os novos
itens e identidade: `Server ID == Client ID`.

### 5.4 Consequencia pratica

Adicionar offsets ate Sprite ID `100000` nao cria Client IDs no painel Objetos.
Adicionar Client IDs no DAT nao cria Server IDs no OTB. Os tres espacos precisam
ser tratados explicitamente.

## 6. Limites obrigatorios

### 6.1 Limite do DAT

O header DAT usa `uint16` para os quatro maximos. O Object Builder le com
`readUnsignedShort()` e grava com `writeShort()`.

```text
max_client_id_dat = 65535
```

Criar Client ID `100000` no formato 10.41 e impossivel sem definir um novo
formato e alterar cliente, Object Builder, Item Editor, RME e OTB.

### 6.2 Limite operacional do RME local

O RME auditado faz, de forma equivalente:

```cpp
uint32_t maxID = item_count + creature_count;
uint16_t id = 100;
while (id <= maxID) {
    // le item ou outfit
    ++id;
}
```

Como `id` e `uint16_t` e a comparacao e inclusiva, `maxID == 65535` tambem e
invalido: depois do ID 65535, o incremento volta para zero e o loop nao termina.

Invariante correto:

```text
item_count + outfit_count < 65535
```

Com `752` outfits:

```text
max_item_id_rme = 65534 - 752 = 64782
```

Nao use `<= 65535`. Esse foi um erro real e causou uma primeira correcao
off-by-one terminando em `64783`, ainda incompativel.

### 6.3 Limite do SPR

Com `extended: true`, contagem e indices usam `uint32`. Sprite ID `100000` e
representavel. Isso nao altera os limites de Client ID ou Server ID.

### 6.4 Limite do OTB

Na biblioteca Item Editor auditada, `ServerItem.ID` e `ClientId` sao `UInt16`.
Portanto o OTB atual tambem nao suporta IDs acima de `65535`.

## 7. OTFI

O `Tibia.otfi` final e:

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

O OTFI nao e decorativo. O header DAT/SPR nao descreve todas essas features.
Sem ele, o Object Builder 10.41 sugere defaults incompletos e pode interpretar o
arquivo com o layout errado.

Falhas reproduzidas:

- Improved Animations desligado: `Unknown flag 0x64`, Item ID 1900;
- Frame Groups desligado: `Unknown flag 0x81`, Outfit ID 3;
- somente com as quatro features ligadas a base customizada carregou inteira.

A nova ferramenta deve ler e validar o OTFI antes de tocar DAT/SPR. Se as flags
divergirem do perfil, deve abortar, nao tentar adivinhar.

## 8. Formato DAT 10.41

### 8.1 Header

Todos os inteiros sao little-endian:

```text
offset  tamanho  campo
0       4        uint32 signature
4       2        uint16 maxItemId
6       2        uint16 maxOutfitId
8       2        uint16 maxEffectId
10      2        uint16 maxMissileId
```

Depois do byte 11 aparecem, sem offsets intermediarios:

1. items `100..maxItemId`;
2. outfits `1..maxOutfitId`;
3. effects `1..maxEffectId`;
4. missiles `1..maxMissileId`.

Para alterar somente items, basta interpretar corretamente todos os items,
identificar `items_end` e preservar byte a byte o sufixo de outfits/effects/
missiles.

### 8.2 Flags de item MetadataFlags6

Cada registro comeca com zero ou mais flags e termina em `0xFF`. Payloads:

| Flag | Nome | Payload apos a flag |
| ---: | --- | --- |
| `0x00` | Ground | `uint16 groundSpeed` |
| `0x01` | Ground Border | nenhum |
| `0x02` | On Bottom | nenhum |
| `0x03` | On Top | nenhum |
| `0x04` | Container | nenhum |
| `0x05` | Stackable | nenhum |
| `0x06` | Force Use | nenhum |
| `0x07` | Multi Use | nenhum |
| `0x08` | Writable | `uint16 maxTextLength` |
| `0x09` | Writable Once | `uint16 maxTextLength` |
| `0x0A` | Fluid Container | nenhum |
| `0x0B` | Fluid | nenhum |
| `0x0C` | Unpassable | nenhum |
| `0x0D` | Unmoveable | nenhum |
| `0x0E` | Block Missile | nenhum |
| `0x0F` | Block Pathfind | nenhum |
| `0x10` | No Move Animation | nenhum |
| `0x11` | Pickupable | nenhum |
| `0x12` | Hangable | nenhum |
| `0x13` | Vertical | nenhum |
| `0x14` | Horizontal | nenhum |
| `0x15` | Rotatable | nenhum |
| `0x16` | Has Light | `uint16 level`, `uint16 color` |
| `0x17` | Dont Hide | nenhum |
| `0x18` | Translucent | nenhum |
| `0x19` | Has Offset | `int16 x`, `int16 y` |
| `0x1A` | Has Elevation | `uint16 elevation` |
| `0x1B` | Lying Object | nenhum |
| `0x1C` | Animate Always | nenhum |
| `0x1D` | Mini Map | `uint16 color` |
| `0x1E` | Lens Help | `uint16 value` |
| `0x1F` | Full Ground | nenhum |
| `0x20` | Ignore Look | nenhum |
| `0x21` | Cloth | `uint16 slot` |
| `0x22` | Market Item | estrutura variavel abaixo |
| `0x23` | Default Action | `uint16 action` |
| `0x24` | Wrappable | nenhum |
| `0x25` | Unwrappable | nenhum |
| `0x26` | Top Effect | nenhum |
| `0x27` | Has Bones | oito `int16`, total 16 bytes |
| `0xFE` | Usable | nenhum |
| `0xFF` | Last Flag | terminador, nao possui payload |

Market Item:

```text
uint16 category
uint16 tradeAs
uint16 showAs
uint16 nameLength
byte[nameLength] name em ISO-8859-1
uint16 restrictProfession
uint16 restrictLevel
```

Regra de seguranca: flag desconhecida deve abortar com Client ID e offset do
arquivo. Nunca avance zero bytes em um loop de flag desconhecida, pois isso
dessincroniza todos os registros seguintes.

### 8.3 Aparencia do item

Apos `0xFF`:

```text
uint8 width
uint8 height
if width > 1 or height > 1:
    uint8 exactSize
uint8 layers
uint8 patternX
uint8 patternY
uint8 patternZ
uint8 frames
if frames > 1 and frame-durations == true:
    uint8 animationMode
    int32 loopCount
    int8 startFrame
    repeat frames:
        uint32 minimumDuration
        uint32 maximumDuration
repeat width*height*layers*patternX*patternY*patternZ*frames:
    uint32 spriteId  # porque extended == true
```

Sem `extended`, Sprite IDs seriam `uint16`. Sem `frame-durations`, os bytes da
animacao nao existem no DAT e a ferramenta aplica duracoes default em memoria.

O total de sprites de um frame group nao deve exceder `4096`, limite observado no
Object Builder 0.5.6.

### 8.4 Registro vazio de item

Registro default criado pelo modelo do Object Builder:

```text
FF 01 01 01 01 01 01 01 00 00 00 00
```

Interpretacao:

- nenhuma propriedade, terminador `FF`;
- width/height `1x1`;
- layers/patterns/frames todos `1`;
- Sprite ID `0`.

Esse registro serve para reservar Client ID. Ele deve ser inserido antes do
sufixo de outfits, nunca no fim absoluto do arquivo.

## 9. Formato SPR extended com transparencia

### 9.1 Header e tabela

```text
uint32 signature
uint32 spriteCount
uint32 offsets[spriteCount]
sprite blocks...
```

- assinatura esperada: `0x53835077`;
- Sprite ID `n` usa `offsets[n - 1]`;
- offsets sao posicoes absolutas no arquivo;
- offset `0` significa slot vazio/ausente;
- Sprite ID `0` nao tem entrada e e apenas sentinela do DAT.

Em cliente nao extended o count e `uint16`, mas cada endereco continua sendo
`uint32`. A implementacao nova deve modelar os dois formatos, ainda que o perfil
10.41 deste projeto exija extended.

### 9.2 Bloco de sprite

No offset:

```text
byte[3] colorKey = FF 00 FF
uint16 payloadLength
byte[payloadLength] rlePayload
```

O payload e uma sequencia de runs:

```text
uint16 transparentPixelCount
uint16 coloredPixelCount
repeat coloredPixelCount:
    uint8 red
    uint8 green
    uint8 blue
    uint8 alpha  # somente quando transparency == true
```

Para `transparency: false`, cada pixel colorido tem apenas RGB.

O decoder deve:

1. iniciar um buffer RGBA transparente de 1024 pixels;
2. avancar `transparentPixelCount`;
3. copiar `coloredPixelCount` pixels;
4. repetir ate consumir `payloadLength`;
5. deixar transparente qualquer cauda nao descrita;
6. rejeitar run truncado, payload fora do arquivo ou soma acima de 1024.

### 9.3 Sprite totalmente transparente

Nunca vincule um item a um Sprite ID cujo offset seja zero. Tambem nao use bloco
com payload de tamanho zero.

Representacao canonica adotada:

```text
FF 00 FF 04 00 00 04 00 00
```

Decomposicao:

```text
FF 00 FF  # color key
04 00     # payload length = 4
00 04     # 1024 pixels transparentes
00 00     # 0 pixels coloridos
```

O Object Builder normalmente trata uma imagem inteira transparente como sprite
vazio e grava offset zero. Isso e aceitavel para um slot SPR sem referencia, mas
nao para um tile que aparece na lista `spriteIndex` de um item composto.

### 9.4 Escrita do SPR

Ha duas estrategias seguras.

Preservacao de body:

1. aumentar a tabela em `newSprites * 4`;
2. somar esse delta a cada offset antigo nao zero;
3. copiar o body antigo byte a byte;
4. anexar novos blocos e escrever seus offsets.

Reconstrucao canonica:

1. ler cada bloco referenciado;
2. preservar os bytes brutos de blocos nao modificados;
3. escrever uma nova tabela;
4. escrever blocos sequencialmente e calcular offsets novos;
5. remover gaps e blocos que deixaram de ser referenciados.

A segunda estrategia produz arquivo menor e e indicada para normalizacao/trim. A
primeira facilita provar que o body original nao mudou durante importacao.

## 10. Normalizacao das imagens

### 10.1 Formatos de entrada

O pipeline comprovado usou PNG. O Object Builder tambem aceita BMP, JPG e GIF,
mas uma ferramenta nova deve inicialmente aceitar apenas PNG RGBA para reduzir
ambiguidade.

### 10.2 Regras

- converter para RGBA;
- dimensoes devem ser maiores que zero;
- largura e altura devem ser multiplas de 32;
- alpha `0` vira RGBA `0,0,0,0`;
- magenta opaco `255,0,255,255` tambem vira transparente;
- alpha parcial diferente de zero deve ser preservado;
- usar os bytes RGBA normalizados para hash e validacao.

O nome do arquivo pode conter dimensoes, mas os pixels sao a autoridade. Divergir
nome e dimensao real deve gerar warning ou erro configuravel.

### 10.3 Estrutura do objeto

```text
width_tiles  = image_width / 32
height_tiles = image_height / 32
```

Para importacao apenas visual:

```text
exactSize = 32 se width_tiles > 1 ou height_tiles > 1
layers = 1
patternX = 1
patternY = 1
patternZ = 1
frames = 1
```

As flags anteriores ao terminador `0xFF` permanecem byte a byte.

### 10.4 Ordem dos tiles

A ordem DAT nao e a ordem natural de crop da esquerda para a direita. Para cada
`h = 0..height-1` e `w = 0..width-1`:

```text
left = (width  - w - 1) * 32
top  = (height - h - 1) * 32
```

Exemplo `2x2`:

| Indice DAT | Tile da imagem |
| ---: | --- |
| 0 | inferior direito |
| 1 | inferior esquerdo |
| 2 | superior direito |
| 3 | superior esquerdo |

Usar crop natural sem essa inversao monta o objeto espelhado/embaralhado no RME.

## 11. Manifesto deterministico

Nunca dependa da ordem retornada pelo filesystem. Gere e congele um CSV antes da
importacao:

```csv
sequence,client_id,file_name,source_path
1,62868,Asphalt_Floor 00 - 32_00.png,C:\assets\Asphalt_Floor 00 - 32_00.png
2,62869,Asphalt_Floor 00 - 32_01.png,C:\assets\Asphalt_Floor 00 - 32_01.png
```

Validacoes do manifesto:

- nao vazio;
- `sequence` unica e continua;
- Client IDs unicos e, no modo de lote, continuos;
- todos os arquivos existem;
- extensao permitida;
- nenhuma imagem repetida por caminho acidental;
- registrar SHA-256 do arquivo e SHA-256 dos pixels normalizados;
- ordem natural/numerica deve ser aplicada apenas na criacao do manifesto;
- depois de criado, o manifesto e a fonte de verdade.

## 12. Algoritmo final de importacao DAT/SPR

### 12.1 Preflight

1. localizar `Tibia.dat`, `Tibia.spr`, `Tibia.otfi` e `items.otb`;
2. calcular SHA-256 de todos;
3. validar OTFI e assinaturas;
4. ler contagens;
5. calcular limite RME dinamico:

```text
rme_max_item = 65534 - outfit_count
```

6. rejeitar ultimo Client ID acima desse limite;
7. validar que os Client IDs alvo existem ou reservar os faltantes;
8. validar que a quantidade final de Sprite IDs cabe em `uint32`;
9. criar output separado; nunca escrever no source.

### 12.2 Reserva de Client IDs

Se `target_last_id > current_max_item_id`:

1. parsear ate `items_end`;
2. atualizar apenas `maxItemId` no header;
3. copiar todos os registros existentes byte a byte;
4. inserir `EMPTY_ITEM_RECORD` uma vez por novo ID;
5. copiar o sufixo de categorias byte a byte;
6. reparsear e conferir contagens/limites.

Nao reserve automaticamente ate `65535`, pois o RME atual suporta menos.

### 12.3 Importacao de cada imagem

Pseudocodigo:

```python
next_sprite_id = old_sprite_count + 1

for row in manifest:
    image = normalize_rgba(row.path)
    width, height, tiles = split_bottom_right_first(image)

    sprite_ids = []
    for tile in tiles:
        block = encode_sprite(tile)
        append_spr_block(block)
        sprite_ids.append(next_sprite_id)
        next_sprite_id += 1

    old_record = dat.items[row.client_id]
    property_prefix = old_record.bytes_before_appearance
    new_appearance = encode_appearance(width, height, sprite_ids)
    replacements[row.client_id] = property_prefix + new_appearance
```

`encode_sprite(tile)` deve retornar o bloco explicito de 9 bytes quando o tile
for totalmente transparente.

### 12.4 Reconstrucao DAT

```python
output = original_header
for client_id in 100..maxItemId:
    if client_id in replacements:
        output += original_property_prefix(client_id)
        output += replacement_appearance(client_id)
    else:
        output += original_record_bytes(client_id)
output += original_category_suffix
```

### 12.5 Escrita atomica

Para cada arquivo:

1. escrever `filename.tmp` no mesmo volume;
2. flush e fechar;
3. reabrir e validar o temporario;
4. usar rename/replace atomico para o nome final.

O conjunto DAT/SPR/OTFI/OTB nao pode ser trocado atomicamente como unidade. A
instalacao final precisa de staging, backup dos quatro arquivos e rollback se
qualquer hash pos-copia falhar.

## 13. Registro OTB

### 13.1 Responsabilidade

O Object Builder nao edita `items.otb`. Sem registro OTB, o Item Editor ou o RME
pode nao expor os novos itens, mesmo que DAT/SPR estejam corretos.

Fluxo usado:

- para IDs ja existentes no OTB, preservar todas as propriedades e atualizar
  somente `SpriteHash`;
- para IDs terminais ausentes, anexar `ServerItem` default;
- usar `ID == ClientId`;
- nao preencher nome, tags ou propriedades funcionais;
- proibir a criacao de uma lacuna interna.

### 13.2 Tipos observados na biblioteca Item Editor

`ServerItem` possui:

- `UInt16 ID`;
- `UInt16 ClientId`;
- `ServerItemType Type`;
- flags funcionais;
- valores de ground/light/minimap/texto/trade;
- `String Name`;
- `Byte[16] SpriteHash`.

Atributos OTB observados:

| Codigo | Nome |
| ---: | --- |
| `0x10` | ServerID |
| `0x11` | ClientID |
| `0x12` | Name |
| `0x14` | GroundSpeed |
| `0x20` | SpriteHash |
| `0x21` | MinimapColor, enum local grafado `MinimaColor` |
| `0x22` | MaxReadWriteChars |
| `0x23` | MaxReadChars |
| `0x2A` | Light |
| `0x2B` | StackOrder |
| `0x2D` | TradeAs |

Grupos OTB observados: None, Ground, Container, Weapon, Ammunition, Armor,
Changes, Teleport, MagicField, Writable, Key, Splash, Fluid, Door e Deprecated.

O arquivo usa uma arvore binaria com marcadores `0xFE` para inicio de no e
`0xFF` para fim, com escape de bytes reservados. O header textual final contem
`OTB 3.55.1-10.41`.

### 13.3 Estrategia recomendada para a ferramenta nova

Fase 1, compatibilidade comprovada:

- distribuir `PluginInterface.dll`, `Plugins/PluginThree.dll` e
  `Plugins/PluginThree.xml` como dependencias externas versionadas;
- carregar DAT/SPR pelo PluginThree;
- obter `ClientItem.SpriteHash` de 16 bytes;
- ler/gravar OTB com `OTLib.OTB.OtbReader/OtbWriter`;
- reabrir o OTB escrito antes de publicar.

Fase 2, implementacao OTB totalmente independente:

- implementar a arvore, escaping, root version e todos os atributos;
- reproduzir a serializacao de records existentes;
- reproduzir exatamente o algoritmo de `SpriteHash` do PluginThree;
- validar contra dezenas de fixtures e contra o OTB gerado pela biblioteca;
- somente remover a dependencia DLL quando os arquivos forem semanticamente
  identicos e aceitos pelo Item Editor/RME.

Conhecimento ainda incompleto: o algoritmo interno exato de `SpriteHash` do
PluginThree nao foi reimplementado. Nao invente `MD5(png)` ou `MD5(sprite block)`.
Use a biblioteca comprovada ou trate a reproducao do hash como uma subtarefa de
engenharia reversa com golden tests.

### 13.4 Regra de preservacao

`SpriteHash` e metadata visual e muda quando a representacao dos sprites muda.
Ele deve ser excluido da comparacao de propriedades funcionais e validado
separadamente contra o cliente carregado.

Esse detalhe corrigiu um falso positivo real: apos normalizar sprites vazios,
244 registros tiveram hash diferente, mas nenhuma propriedade funcional mudou.

## 14. Trim coordenado

Remover o sufixo exige coordenar quatro estruturas.

### 14.1 DAT

- definir novo `maxItemId`;
- manter registros `100..target` byte a byte;
- remover somente `target+1..oldMax`;
- recolocar o sufixo de outfits/effects/missiles sem mudanca.

### 14.2 SPR

- descobrir o maior Sprite ID referenciado pelos itens retidos;
- definir o count para esse ID ou para um limite explicitamente validado;
- remover entradas de tabela posteriores;
- ajustar offsets ou reconstruir o arquivo;
- garantir que nenhum item retido referencia Sprite ID acima do novo count.

### 14.3 OTB

- remover somente Server IDs terminais `target+1..oldMax`;
- rejeitar tail com lacunas inesperadas;
- preservar versao e records retidos;
- reabrir o arquivo escrito.

### 14.4 Manifesto

- remover as linhas dos Client IDs descartados;
- guardar no relatorio nome do asset e Sprite IDs removidos.

### 14.5 Caso real

O lote completo terminava em Client ID `64790` e Sprite ID `52465`. Para ficar
compativel com o RME foram removidos oito objetos, `64783..64790`. Eram as oito
plataformas finais `128x128`, 16 tiles cada:

```text
8 objetos * 16 sprites = 128 Sprite IDs removidos
52465 - 128 = 52337
```

Resultado:

```text
max Client/Server ID = 64782
max Sprite ID = 52337
```

## 15. Normalizacao de sprites vazios

### 15.1 Estados que devem ser reconhecidos

1. offset zero: slot SPR ausente;
2. offset nao zero e payload length zero: bloco `FF 00 FF 00 00`;
3. offset nao zero e run transparente explicito: bloco canonico de 9 bytes.

### 15.2 Politica final

- Sprite ID nao referenciado pode ter offset zero, mas nao deve ser criado sem
  necessidade;
- todo Sprite ID referenciado pelo DAT deve ter offset nao zero;
- todo bloco referenciado deve ter payload maior que zero;
- tile totalmente transparente deve usar o run explicito de 1024 pixels.

### 15.3 Normalizador

O normalizador final deve:

1. ler todos os offsets;
2. rejeitar offset fora do arquivo;
3. extrair cada bloco;
4. substituir somente blocos de payload zero pelo bloco canonico;
5. preservar byte a byte todo bloco nao vazio;
6. reconstruir tabela e body sequencialmente;
7. recalcular SpriteHash no OTB;
8. validar bitmaps pelo PluginThree.

No caso final, 394 blocos vazios retidos foram normalizados.

## 16. Pipeline recomendado de comandos

Uma CLI nova pode usar os seguintes subcomandos:

```text
asset1041 inspect --client DIR
asset1041 manifest --assets DIR --first-client-id N --out manifest.csv
asset1041 reserve --client DIR --last-client-id N --out STAGE
asset1041 import --client STAGE --manifest manifest.csv --out IMPORTED
asset1041 normalize-blanks --client IMPORTED --out NORMALIZED
asset1041 register-otb --client NORMALIZED --first-id A --last-id B --out OTB_READY
asset1041 trim --client OTB_READY --last-client-id N --out TRIMMED
asset1041 validate --source BASE --target TRIMMED --manifest manifest.csv
asset1041 install --source TRIMMED --rme-data DIR --backup-dir BACKUPS
```

Cada comando deve gerar JSON de relatorio e retornar exit code diferente de zero
quando qualquer invariante falhar.

Ordem canonica para um lote novo:

1. `inspect`;
2. `manifest`;
3. `reserve`, somente se necessario;
4. `import`;
5. `normalize-blanks`, idealmente no-op se o encoder ja for correto;
6. `register-otb`;
7. `validate`;
8. teste Item Editor;
9. instalar em copia do RME;
10. abrir mapa `.otbm` e conferir visualmente;
11. `install` na base desejada, com backup.

## 17. Arquitetura sugerida para implementacao do zero

Python 3.11+ e uma escolha adequada para DAT/SPR/imagens. A camada OTB comprovada
continua Windows/.NET enquanto o hash nao for reimplementado.

```text
asset1041/
  cli.py
  errors.py
  hashing.py
  atomic.py
  profiles/
    tibia_1041.py
  otfi/
    model.py
    parser.py
  dat/
    model.py
    reader.py
    writer.py
    metadata_v6.py
    appearance.py
  spr/
    model.py
    reader.py
    writer.py
    rle.py
  images/
    normalize.py
    tiling.py
  manifests/
    model.py
    build.py
  pipelines/
    reserve.py
    import_assets.py
    trim.py
    normalize_blanks.py
    install.py
  otb/
    adapter.py
    itemeditor_dotnet.py
    native_reader.py       # fase futura
    native_writer.py       # fase futura
  validate/
    binary.py
    semantic.py
    pixels.py
    itemeditor.py
    reports.py
tests/
  fixtures/
  golden/
```

Principios:

- modelos imutaveis para dados parseados;
- limites e features pertencem a um profile, nao a constantes globais soltas;
- reader nunca escreve;
- writer recebe um modelo validado;
- pipeline trabalha sempre em staging;
- validadores nao compartilham a mesma funcao de encode/decode quando isso
  esconderia o mesmo bug nos dois lados;
- relatorios devem listar mismatches, nao apenas `passed=false`.

## 18. Validacao obrigatoria

### 18.1 Validacao estrutural DAT

- assinatura correta;
- contagens esperadas;
- parse termina exatamente no inicio do sufixo;
- flags conhecidas;
- dimensoes maiores que zero;
- total de sprites por grupo entre 1 e 4096;
- todos os Sprite IDs dentro do count SPR ou zero;
- propriedades dos alvos preservadas;
- records nao alvo byte a byte iguais;
- sufixo de categorias byte a byte igual;
- `item_count + outfit_count < 65535`.

### 18.2 Validacao estrutural SPR

- assinatura/count corretos;
- tabela cabe no arquivo;
- cada offset referenciado e nao zero;
- cada offset aponta para header e payload completos;
- payload RLE nao ultrapassa 1024 pixels;
- canais condizem com transparency;
- novos IDs sao continuos;
- blocos antigos nao modificados preservados;
- nenhum tile referenciado tem payload zero;
- decode de cada novo tile e identico aos pixels normalizados da origem.

### 18.3 Validacao de montagem

Para cada asset:

- recompor width x height usando a mesma indexacao do cliente, mas por uma
  implementacao independente;
- comparar a imagem composta com o PNG normalizado;
- testar dimensoes 1x1, 2x2, 3xN e 4x4;
- registrar diff de pixels por Client ID e Sprite ID.

### 18.4 Validacao OTB

- IDs sem duplicatas;
- faixa continua `100..max`;
- `Server ID == Client ID` nos registros novos;
- records anteriores ao lote preservados;
- propriedades funcionais existentes preservadas;
- records novos iguais ao default, exceto ID/ClientId/SpriteHash;
- `SpriteHash` igual ao reportado pelo PluginThree;
- string `OTB 3.55.1-10.41` preservada;
- OTB gerado reabre no mesmo reader.

### 18.5 Validacao visual do Item Editor

Para cada Client ID importado:

- `GetClientItem(id)` nao retorna null;
- `SpriteHash` tem 16 bytes;
- `ClientItem.GetBitmap()` retorna bitmap valido;
- cada `Sprite.GetBitmap()` retorna bitmap valido;
- logs nao contem `Failed to get image`.

Validar apenas SpriteHash e insuficiente. O plugin ja produziu hash mesmo quando
o bitmap de um sprite falhava.

### 18.6 Validacao final do RME

1. copiar os quatro arquivos para uma instalacao de teste;
2. iniciar o RME pelo fluxo normal do Windows;
3. abrir um mapa `.otbm` real;
4. esperar o carregamento completo;
5. navegar ate uma area/amostra que use os itens;
6. conferir assets 1x1 e multi-tile;
7. confirmar ausencia de travamento e erros;
8. fechar a instancia de teste.

O processo estar vivo, `Responding=True`, mostrar splash ou nao mostrar janela
na automacao nao e criterio conclusivo.

## 19. Relatorios minimos

Todo run deve produzir:

```json
{
  "tool_version": "...",
  "profile": "tibia-1041-custom",
  "source_directory": "...",
  "output_directory": "...",
  "source_hashes": {},
  "output_hashes": {},
  "dat": {},
  "spr": {},
  "otb": {},
  "asset_count": 0,
  "client_id_range": [0, 0],
  "sprite_id_range": [0, 0],
  "mappings": [],
  "checks": {},
  "warnings": [],
  "errors": [],
  "passed": true
}
```

O CSV de mapping deve incluir:

- sequence;
- client_id;
- file_name;
- source_path;
- image_width/height;
- structure_width/height;
- sprite_ids separados de forma nao ambigua;
- SHA-256 do arquivo;
- SHA-256 dos pixels normalizados.

## 20. Historico real dos lotes

### 20.1 Baseline

- max Client ID: `64211`;
- outfits: `752`;
- effects/missiles: `1/1`;
- Sprite IDs: `45635`;
- OTB: 64112 records, IDs `100..64211`.

### 20.2 Lote 32x32

- 366 assets;
- Client IDs `62868..63233`;
- 366 novos sprites;
- Sprite IDs `45636..46001`;
- todos 1x1;
- uma duplicata visual conhecida entre dois arquivos City Floor, preservada por
  ser parte do lote, sem deduplicacao automatica.

### 20.3 Lote 64x64

- 1521 assets;
- Client IDs `63234..64754`;
- todos 2x2;
- 6084 novos sprites;
- Sprite IDs `46002..52085`;
- 330 tiles inteiramente transparentes.

### 20.4 Lote misto

- 36 assets;
- Client IDs `64755..64790`;
- dimensoes inferidas dos pixels, incluindo 96 e 128;
- 380 novos sprites;
- Sprite IDs `52086..52465`;
- 116 tiles inteiramente transparentes.

### 20.5 Registro OTB completo antes do trim

- 1923 assets na faixa `62868..64790`;
- 1344 records OTB existentes tiveram hash atualizado;
- 579 records foram anexados, IDs `64212..64790`;
- OTB final temporario tinha 64691 records.

### 20.6 Resultado retido

- oito Client/Server IDs removidos: `64783..64790`;
- 128 Sprite IDs removidos;
- 1915 assets retidos;
- DAT/OTB terminam em `64782`;
- SPR termina em `52337`;
- 394 tiles vazios retidos usam run explicito.

## 21. Erros encontrados e causas

### 21.1 SPR ate 100000 nao criou slots de objeto

Sintoma: header SPR chegou a 100000, mas Object Builder continuou mostrando o
ultimo objeto em 64211.

Causa: Sprite IDs e Client IDs sao espacos diferentes. A tabela SPR nao cria
registros DAT.

Correcao: para slot de objeto, inserir registro DAT antes de outfits. Mesmo
assim, respeitar o limite RME 64782.

### 21.2 Pedido de Client ID 100000

Sintoma: tentativa de expandir objetos ate 100000.

Causa: maxItemId DAT e `uint16`; OTB tambem usa IDs `uint16`.

Correcao: limitar a 65535 no formato e a 64782 no RME atual. Para ultrapassar,
e necessario projeto de novo formato e mudanca coordenada em todo o ecossistema.

### 21.3 Novas sprites nao apareciam no Item Editor

Sintoma: DAT/SPR continham imagens, mas o Item Editor nao exibia os novos itens.

Causa: `items.otb` ainda terminava em 64211 e/ou seus SpriteHashes nao
correspondiam ao DAT/SPR novo.

Correcao: adicionar records OTB terminais e recalcular SpriteHash.

### 21.4 `Failed to get image ... Check the transparency option`

Exemplos observados: Client IDs 64778, 64781, 64782 e seguintes ate 64790.

Causa real: objetos compostos referenciavam Sprite IDs cujo offset SPR era zero.
O PluginThree tentava interpretar bytes do inicio do arquivo como bloco e chegava
a tamanho invalido, observado como `61779`. A mensagem citava transparencia, mas
o problema principal era o endereco zero referenciado.

Primeira correcao incompleta: anexar `FF 00 FF 00 00`, bloco com payload zero.
Isso fez o Item Editor renderizar, mas nao e a representacao final recomendada.

Correcao final: `FF 00 FF 04 00 00 04 00 00` e recalculo OTB.

### 21.5 Item Editor abria, RME travava

Primeira causa confirmada: DAT terminava em 64790, logo
`64790 + 752 = 65542`, acima do espaco usado pelo contador `uint16_t` do RME.

Primeiro reparo incorreto: remover sete records e terminar em 64783. A soma ficou
`65535`. O validador inicialmente aceitou o limite inclusivo, mas o loop do RME
tambem processa 65535 e depois faz wrap para zero.

Reparo correto: remover oito records e terminar em 64782, soma 65534.

Segunda medida defensiva: substituir payloads transparentes de tamanho zero por
runs explicitos. O Item Editor aceita payload zero; a compatibilidade do RME com
esse estado nao deve ser presumida. O conjunto final usa apenas payloads
explicitos.

### 21.6 Falso diagnostico pela automacao do RME

Sintoma: processos de teste ficavam sem janela principal e pareciam indicar que
os arquivos ainda falhavam. A mesma coisa ocorreu com a base antiga conhecida.

Causa: o protocolo de teste nao abria um mapa. Estado de processo/splash nao
representava o fluxo completo do editor nessa instalacao.

Correcao: usuario abriu um mapa real e confirmou o funcionamento. Automatizacoes
futuras devem abrir `.otbm` e validar renderizacao.

### 21.7 Falso `property_mismatch` apos normalizar blanks

Sintoma: 244 records divergiam na comparacao OTB, embora imagens e propriedades
funcionais estivessem corretas.

Causa: o validador tratava `SpriteHash` como propriedade que deveria permanecer
identica ao source. A normalizacao visual exige hash novo.

Correcao: excluir SpriteHash da comparacao funcional e validá-lo separadamente
contra o PluginThree.

### 21.8 Ausencia ou flags erradas no OTFI

Sintomas: unknown flags e leitura dessincronizada.

Causa: features estruturais nao estao integralmente codificadas nos headers.

Correcao: preservar e validar OTFI junto com DAT/SPR.

### 21.9 Tiles multi-sprite montados incorretamente

Causa possivel: crop na ordem natural em vez da indexacao invertida do DAT.

Correcao: bottom-right first e teste de composicao pixel a pixel.

### 21.10 Scripts prototipo que nao devem ser copiados

- extensor SPR que cria milhares de offsets zero: util apenas para estudar o
  header, nao cria objetos e nao serve para sprites referenciados;
- reparador que usa bloco de payload zero de 5 bytes: substituido pelo run
  explicito de 9 bytes;
- validador antigo que exige offset zero para tile transparente: regra obsoleta;
- parser de flags que nao rejeita flag desconhecida: risco de dessincronizacao;
- validador que considera `combined <= 65535`: deve usar `< 65535`.

## 22. Testes automatizados recomendados

### 22.1 Unitarios DAT

- parse/escrita de cada flag 0x00..0x27 e 0xFE;
- market name vazio, ASCII e ISO-8859-1;
- int16 negativos em offset/bones;
- frames 1 e >1;
- extended on/off;
- registro vazio exato;
- unknown flag aborta;
- arquivo truncado aborta;
- round-trip sem mudanca preserva bytes.

### 22.2 Unitarios SPR

- sprite todo transparente;
- todo opaco;
- primeiro/ultimo pixel colorido;
- runs alternados;
- alpha parcial;
- magenta opaco normalizado;
- payload truncado;
- offset zero referenciado rejeitado;
- count/tabela fora do arquivo rejeitados;
- rebuild preserva blocos antigos.

### 22.3 Tiling

- 32x32 -> 1x1;
- 64x64 -> 2x2;
- 96x32 -> 3x1;
- 32x96 -> 1x3;
- 128x128 -> 4x4;
- imagem nao multipla de 32 rejeitada;
- composicao reconstruida idêntica a origem.

### 22.4 Limites

- `item + outfits = 65534` aceito;
- `item + outfits = 65535` rejeitado;
- Client ID 65536 rejeitado;
- SPR extended acima de 65535 aceito;
- OTB ID 65536 rejeitado;
- item count menor que target em trim rejeitado.

### 22.5 Integracao

- lote pequeno em fixture sintetica;
- lote que cruza o max OTB existente;
- update de record OTB existente;
- append de record OTB default;
- normalizacao seguida de recalculo de hash;
- trim coordenado;
- Item Editor bitmap de todos os tiles;
- abertura de mapa no RME.

## 23. Instalacao e rollback

Antes de instalar:

1. encerrar Object Builder, Item Editor e RME;
2. criar pasta de backup com timestamp;
3. copiar os quatro arquivos ativos para o backup;
4. registrar tamanho e SHA-256;
5. copiar a saida de staging;
6. recalcular hashes no destino;
7. comparar com a saida;
8. abrir Item Editor;
9. abrir mapa no RME.

Se qualquer passo falhar:

1. encerrar os programas;
2. restaurar os quatro arquivos do mesmo backup;
3. verificar hashes restaurados;
4. nao misturar DAT de um run com SPR/OTB de outro.

## 24. Dependencias para outra maquina

Minimo recomendado:

- Windows 10/11 64-bit;
- Python 3.11 ou superior;
- Pillow em versao fixada;
- PowerShell 5.1+ ou 7+ para a ponte .NET;
- Object Builder 0.5.6 para comparacao manual;
- Item Editor com `PluginInterface.dll`, `PluginThree.dll` e XML correspondente;
- RME usado pelo projeto;
- um mapa `.otbm` de teste;
- fixtures baseline e final com hashes conhecidos;
- Git para versionar codigo e golden files.

Nao e necessario automatizar a interface do Object Builder para o pipeline
principal. A edicao binaria direta foi mais previsivel, auditavel e reproduzivel.

## 25. Definition of Done

Uma reimplementacao so esta pronta quando:

- todos os parsers falham de forma explicita em input invalido;
- source nunca e alterado;
- manifest e mapping sao deterministicos;
- pixels novos fazem round-trip exato;
- propriedades DAT antigas permanecem byte a byte;
- itens nao alvo permanecem byte a byte;
- sufixo DAT permanece byte a byte;
- sprites antigos permanecem semanticamente e, quando previsto, byte a byte;
- nenhum Sprite ID referenciado tem offset/payload zero;
- OTB nao tem lacunas/duplicatas;
- propriedades OTB existentes permanecem iguais;
- hashes OTB coincidem com o cliente;
- Item Editor renderiza todos os itens e tiles;
- `item_count + outfit_count < 65535`;
- o RME abre e renderiza um mapa real;
- backup e rollback foram testados;
- relatorio final contem hashes e todos os checks.

## 26. Prompt inicial sugerido para o Codex na outra maquina

```text
Implemente do zero uma CLI chamada asset1041 seguindo integralmente esta
especificacao. Comece pelos modelos e readers read-only de OTFI, DAT e SPR.
Depois crie fixtures e testes de round-trip. Nao implemente escrita antes de os
readers validarem os golden files. A importacao deve preservar propriedades DAT,
records nao alvo e sufixo de categorias. Tiles transparentes referenciados devem
usar o bloco RLE explicito de 9 bytes. O limite operacional do RME e estrito:
item_count + outfit_count < 65535. Para OTB, use inicialmente o adapter da
biblioteca Item Editor e trate a implementacao nativa/SpriteHash como uma fase
separada. Cada comando deve escrever em staging, gerar JSON e abortar se qualquer
invariante falhar. O aceite final exige abrir um mapa real no RME.
```

## 27. Referencia funcional do Object Builder 0.5.6

Esta secao nao exige recriar a interface AIR. Ela registra a semantica que a CLI
deve reproduzir.

### 27.1 Arquitetura original

O Object Builder 0.5.6 local e um aplicativo Adobe AIR 64-bit:

- `ObjectBuilder.mxml` controla janela, menus, selecao e editores;
- `ObjectBuilderWorker.as` executa as operacoes pesadas em um AIR Worker;
- `WorkerCommunicator` transporta comandos, progresso, logs e resultados;
- `ThingTypeStorage` mantem items, outfits, effects e missiles;
- `SpriteStorage` mantem a tabela SPR e carrega pixels sob demanda;
- `ThingData` transporta propriedades, frame groups e pixels de um objeto.

A separacao entre interface e worker existe para impedir que DAT/SPR grandes
congelem a UI. Na ferramenta nova, o equivalente deve ser separacao entre core
puro, pipeline e camada CLI, com progresso estruturado e operacoes cancelaveis.

### 27.2 Inicializacao e persistencia

Na abertura, o aplicativo:

1. carrega recursos, idiomas, `versions.xml` e `sprites.xml`;
2. inicia o worker;
3. restaura configuracoes e paineis;
4. detecta DAT/SPR/OTFI;
5. associa versao pelas assinaturas;
6. somente depois permite Load.

Configuracoes AIR ficam em
`%APPDATA%/com.mignari.ObjectBuilder/Local Store/settings/`. O log persistente e
`Local Store/objectbuilder.log`.

O `versions.xml` da v0.5.6 define para 10.41:

```xml
<version value="1041" string="10.41"
         dat="5383504E" spr="53835077" otb="0"/>
```

O `sprites.xml` oferece tamanhos fisicos 32, 64, 128 e 256. Isso nao deve ser
confundido com um objeto 128x128 composto por 16 tiles fisicos 32x32.

### 27.3 Interface relevante

Menus principais:

- File: New, Open, Compile, Compile As, Close, Merge, Preferences e Exit;
- View: mostrar/ocultar Preview, Objects e Sprites;
- Tools: Find, LookType Generator, Object Viewer, Slicer, Animation Editor,
  Sprites Optimizer, Frame Durations Optimizer e Frame Groups Converter;
- Window: Log Window e Versions;
- Help: updater/about, com ajuda incompleta na v0.5.6.

Paineis:

- Preview/Info: versao, assinaturas, contagens e features;
- Objects: Client IDs e operacoes Replace/Import/Edit/Duplicate/New/Remove;
- editor central: Texture, Patterns, Animation e Properties;
- Sprites: Sprite IDs e operacoes Replace/Import/Export/Copy/New/Remove/Fill.

`Import` de objetos anexa Client IDs. `Replace` preserva Client IDs existentes.
`Import` de sprites apenas anexa pixels ao SPR e nao vincula esses pixels a um
objeto DAT.

### 27.4 Drop direto de PNG

No fluxo manual comprovado:

1. selecionar Client ID;
2. abrir Edit;
3. manter/ajustar width, height, layers, patterns e frames;
4. arrastar uma PNG para `Textura > Aparencia`;
5. conferir o preview;
6. clicar Save;
7. responder `No` ao prompt `replace current sprites`.

Internamente:

1. o handler usa o primeiro arquivo arrastado;
2. `ThingData.setSpriteSheet` remove magenta e fatia a imagem;
3. cada tile recebe ID temporario `uint.MAX_VALUE`;
4. Save envia `UpdateThingCommand` ao worker;
5. com `replaceSprites=false`, o worker chama `addSprite`;
6. os IDs temporarios sao trocados pelos Sprite IDs reais;
7. `replaceThing` atualiza o objeto em memoria.

Semantica do prompt:

- `No`: anexa novos Sprite IDs, opcao canonica para textura nova;
- `Yes`: substitui pixels dos Sprite IDs atuais quando eles nao sao zero;
- substituir ID compartilhado pode mudar outros objetos;
- se o ID atual for zero, o worker ainda precisa anexar um sprite, mas nao se
  deve depender dessa excecao.

A CLI reproduz o resultado de `No`: sempre anexa novos Sprite IDs e modifica
somente a aparencia do Client ID alvo.

### 27.5 Sprite sheets e OBD

Uma sprite sheet precisa ter exatamente o tamanho calculado pela estrutura do
frame group. O Object Builder nao faz resize automatico.

OBD v1/v2/v3 transporta propriedades, estrutura e pixels, comprimidos com LZMA.
V3 preserva frame groups. Para adicionar uma PNG simples em item vazio, OBD e
desnecessario; ele e util para transportar objetos completos ou estruturas
complexas.

### 27.6 Compile e Compile As

Save altera apenas o storage em memoria. Persistencia ocorre em Compile/Compile
As.

O worker:

1. valida que DAT e SPR estao carregados;
2. compila cada um em arquivo temporario;
3. grava OTFI;
4. substitui os destinos;
5. limpa o estado changed;
6. pode solicitar reload quando features estruturais mudam.

`Compile` usa os caminhos carregados. `Compile As` escolhe destino/nome/features
e e a opcao segura para testes. A CLI deve se comportar como Compile As por
padrao: source read-only e output separado.

### 27.7 Operacoes destrutivas que nao pertencem ao importador minimo

- Merge otimiza o source externo, remapeia e anexa categorias;
- Sprites Optimizer deduplica, remove vazios/nao usados e renumera IDs;
- Frame Groups Converter muda estrutura de outfits;
- Remove pode deixar sprites sem uso ou alterar numeracao apos otimizacao;
- Replace Sprite altera todos os objetos que compartilham aquele ID.

Essas operacoes devem ser comandos separados, desabilitados por default e nunca
executados implicitamente durante uma importacao de texturas.

## 28. Questoes ainda abertas

- algoritmo exato de `SpriteHash` do PluginThree, caso a dependencia .NET seja
  removida;
- especificacao completa e writer nativo OTB com escaping e todas as versoes;
- atomicidade real do conjunto de quatro arquivos sob falta de energia/disco;
- compatibilidade do run transparente explicito em outras versoes de cliente;
- comportamento de dimensoes fisicas de sprite 64/128/256 definidas em
  `sprites.xml`, que nao sao o mesmo que objetos compostos por tiles 32x32;
- suporte completo a outfits com dois frame groups em uma ferramenta generica;
- alteracoes necessarias no cliente/formatos para Client IDs acima de 65535.

Essas lacunas nao impedem o pipeline 10.41 comprovado, desde que o adapter do
Item Editor seja mantido para OTB e o perfil permaneça exatamente o descrito.
