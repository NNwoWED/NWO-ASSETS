# nwoassets

CLI para inventariar, validar, versionar e importar imagens de itens nos arquivos
do projeto NWO MAPS. O conjunto local é detectado como
`tibia-860-v2-custom-extended`.

## Estrutura oficial

```text
NWO-ASSETS/
├─ assets/
│  ├─ 860/
│  ├─ items/
│  └─ world/
├─ export/            # PNGs derivados de items, outfits, effects e missiles
└─ versions/
```

`assets/` contém somente as três pastas operacionais. `versions/` recebe uma
subpasta imutável para cada operação, identificada por data, hora e microssegundos.

## Executar

```powershell
python -m nwoassets validate . --deep-spr
python -m nwoassets create-version . -o reports/version.json
python -m nwoassets import-items . C:\lote\manifest.csv --deep-spr -o C:\lote\report.json
python -m nwoassets import-effects . C:\lote\effects.csv --deep-spr -o C:\lote\effects-report.json
python -m nwoassets import-missiles . C:\lote\missiles.csv --deep-spr -o C:\lote\missiles-report.json
python -m nwoassets import-outfits . C:\lote\outfits.csv --deep-spr -o C:\lote\outfits-report.json
python -m nwoassets edit-animation-durations . C:\lote\durations.csv --deep-spr -o C:\lote\durations-report.json
python -m nwoassets edit-item-properties . examples\items-properties.csv -o reports\properties.json
python -m nwoassets edit-ground-speeds . reports\ground-speeds.csv --deep-spr -o reports\ground-speeds.json
python -m nwoassets inspect-map-position . 926 1195 7 -o reports\position.json
python -m nwoassets export-png . items 24300 --id-kind server -o reports\export.json
python -m nwoassets sync-runtime . -o reports\sync-runtime.json
python -m nwoassets adopt-runtime . --deep-spr -o reports\adopt-runtime.json
```

Também é possível instalar o comando:

```powershell
python -m pip install -e .
nwoassets validate .
```

## Sincronização com servidor, clients e NWO-STUDIO

Depois de qualquer alteração validada em `items.otb`, `items.xml`, `Tibia.dat`,
`Tibia.spr`, `mapanovo.otbm` ou nos cinco arquivos `.otml` canônicos, execute
`sincronizar-assets-runtime.bat` ou o comando
`python -m nwoassets sync-runtime . -o reports\sync-runtime.json`.

Quando o DAT/SPR tiver sido salvo manualmente na pasta `860` do client, use
`python -m nwoassets adopt-runtime . --deep-spr -o reports\adopt-runtime.json`.
O comando aceita somente um SPR append-only, cria a versao obrigatoria e
incorpora DAT/SPR em uma transacao com rollback. Ele identifica os Client IDs
alterados e atualiza no OTB os SpriteHash e as propriedades com equivalencia
segura (flags, cor de minimapa e stack order); qualquer alteracao fora desse
escopo e bloqueada.

O sincronizador valida a baseline com verificação profunda do SPR, copia
`items.otb` e `items.xml` para `Server-Data-Nwo/data/items`, copia `Tibia.dat` e
`Tibia.spr` para `nwo-otclient-mehah-4.0/data/things/860` e
`nwo-mobile/client/data/things/860`, sincroniza `items.otml`, `creatures.otml`,
`effects.otml`, `missiles.otml` e `things.otml` para as pastas `things` dos dois
clients, e recria
`nwo-otclient-mehah-4.0/data/things/860.rar`. A mesma transação publica
DAT/SPR/OTFI, os cinco `.otml`, OTB/XML e o mapa canônico em `NWO-STUDIO/assets`, além de recriar
e testar `assets/things/1098.rar` e `assets/world/mapanovo.rar`. As publicações
usam arquivos temporários, conferência de hash e rollback integrado antes de
substituir os arquivos anteriores.

## Versionamento obrigatório

Antes de substituir DAT, SPR ou OTB, `import-items`, `import-effects`,
`import-missiles` e `import-outfits` executam automaticamente o
mesmo processo de `create-version` e só continua se os três arquivos forem criados
e testados:

```text
versions/AAAAMMDD-HHMMSS-microssegundos/
├─ 860.rar       # conteúdo completo de assets/860
├─ items.rar     # conteúdo de assets/items, sem arquivos .xml
├─ world.zip     # somente o .otbm canônico
└─ version.json  # hashes e inventário da versão
```

O WinRAR, incluindo `rar.exe`, é obrigatório. Os RARs são testados pelo próprio
WinRAR e o OTBM dentro do ZIP é reaberto e comparado por SHA-256.

## Importação de itens

O manifesto CSV deve estar em UTF-8, com sequência contínua. Caminhos relativos
são resolvidos a partir da pasta do manifesto. Um modelo está em
`examples/items-import.csv`:

```csv
sequence,client_id,source_path,frames,frame_duration_ms,animation_async
1,24522,item-24522.png,1,,0
2,24521,subpasta/item-24521-animado.png,14,150,0
```

Cada PNG deve ser RGBA 8-bit, não entrelaçado, ter dimensões múltiplas de 32 e
medir no máximo 224×224 por frame. Animações usam uma folha vertical, de cima
para baixo, com `frames` e `frame_duration_ms` obrigatórios; `animation_async`
aceita `0` ou `1`. Alpha zero e magenta opaco (`#FF00FF`) tornam-se transparentes.
O Client ID deve existir na baseline. No modo padrão, a aparência usa uma camada
e nenhum pattern adicional.

Para trocar somente os pixels de um item com layout existente, inclusive água
animada com patterns, usar a coluna opcional `preserve_layout=1`:

```csv
sequence,client_id,source_path,preserve_layout
1,20227,agua-recolorida.png,1
```

Nesse modo, o PNG deve seguir exatamente a folha produzida por `export-png`:
layers e pattern X na horizontal; pattern Y, frames e pattern Z na vertical.
O limite de largura permanece 224 pixels e o de altura 224 pixels por frame.
O importador deriva o layout do DAT, sem achatar patterns ou mudar dimensões.
Deixar `frames`, `frame_duration_ms` e `animation_async` vazios ou ausentes:
os metadados existentes são preservados byte a byte, incluindo exactSize,
tempos variáveis, modo assíncrono, loop e frame inicial. As flags OTB também
permanecem intactas; somente os SpriteHash relacionados são atualizados.
Todos os pixels importados são reabertos e conferidos antes do commit, com
o mesmo versionamento obrigatório e rollback do fluxo padrão.

Depois do backup, a ferramenta prepara arquivos temporários ao lado dos oficiais,
reabre e valida tudo e faz a troca no próprio `assets/`. Se a validação final
falhar, DAT, SPR e OTB anteriores são restaurados automaticamente. Os temporários
não são uma pasta de staging e são removidos ao final.

## Importação de efeitos

`import-effects` recebe folhas verticais RGBA 8-bit de até 320x320 por frame.
O manifesto informa o Effect ID existente, a quantidade e duração dos frames e,
opcionalmente, um Effect ID vazio em `preserve_as` para conservar a aparência
substituída sem duplicar os sprites antigos:

```csv
sequence,effect_id,source_path,frames,frame_duration_ms,animation_async,preserve_as
1,1365,descendo.png,3,100,0,1469
```

A ferramenta preserva propriedades DAT, aceita tiles transparentes em aparências
multitile, cria e testa a versão obrigatória, reabre todos os pixels novos e faz
commit transacional somente de DAT e SPR. OTB, mapa, XMLs e OTMLs permanecem
byte a byte inalterados.

## Importação de missiles

`import-missiles` recebe uma folha RGBA 8-bit no layout completo produzido por
`export-png`, com os frames empilhados verticalmente. O manifesto usa
`sequence,operation,missile_id,reference_missile_id,source_path,frames,frame_duration_ms,animation_async`.
O Missile ID de referência define dimensões, layers e patterns direcionais. Em
`reserved`, o alvo precisa estar vazio; em `replace`, precisa estar ocupado. A
ferramenta preserva as propriedades do alvo, versiona DAT/SPR, reabre os pixels
importados e recusa qualquer alteração fora do Missile ID solicitado.

## Importação de outfits

`import-outfits` recebe uma folha completa no mesmo layout produzido por
`export-png`. O manifesto aceita
`sequence,operation,outfit_id,reference_outfit_id,source_path`; a coluna
`operation` é opcional e assume `reserved` quando omitida. Em `reserved`, o
Outfit ID alvo precisa estar vazio. Em `replace`, o alvo precisa estar ocupado e
pode ser sua própria referência para preservar dimensões, frame groups, timings
e demais metadados visuais. As propriedades do alvo são sempre preservadas. A
operação versiona, valida e modifica somente DAT e SPR.

Para reduzir ou ampliar uma animação existente, `operation=replace` aceita as
colunas opcionais `frames` e `frame_duration_ms`. As duas devem ser informadas,
o alvo deve usar a si mesmo como referência e possuir apenas uma frame group.

## Propriedades DAT/OTB

`import-cloned-items` cria novos Client IDs DAT e Server IDs OTB, sempre de forma
contigua imediatamente apos os maximos atuais. O manifesto trava o item de
referencia, os dois IDs novos, o PNG, o tamanho de cada frame, quantidade de
frames, duracao e modo assincrono. As propriedades DAT e OTB sao clonadas da
  referencia; definicoes existentes em `items.xml` tambem sao clonadas, inclusive
  quando a origem pertence a um intervalo. O layout visual vem do PNG. A operacao aceita folhas animadas em
grade, usa Sprite ID zero para tiles totalmente transparentes e preserva todos
os registros antigos byte a byte. Executar primeiro com `--dry-run --deep-spr`.
As colunas opcionais `layers`, `pattern_x`, `pattern_y` e `pattern_z` permitem
declarar explicitamente folhas com variacoes; `frame_width` e `frame_height`
representam o tamanho de uma unica aparencia, nao o tamanho total da folha.

`repair-item-patterns` corrige `width`, `height`, `layers`, `pattern_x/y/z` e
`frames` de itens ja importados. O manifesto trava Server ID, Client ID e PNG.
A operacao somente reutiliza Sprite IDs cujos pixels correspondem ao PNG; se um
pixel nao existir no SPR atual, ela recusa o lote. Assim, o reparo modifica apenas
DAT e SpriteHash/flag de animacao no OTB, mantendo o SPR byte a byte inalterado.

`repair-exact-item-clones` corrige lotes nos quais o numero do PNG representa o
Client ID de referencia. A ferramenta copia byte a byte as propriedades DAT e o
layout visual da referencia, clona o no OTB trocando somente Server ID, Client ID
e SpriteHash, replica definicoes existentes do `items.xml` e reutiliza apenas o
range de Sprite IDs criado na importacao original. Folhas do Object Builder com
`pattern_z` horizontal sao convertidas para a ordem DAT sem mudar pixels do SPR.

`edit-item-properties` recebe um CSV UTF-8 e resolve o Client ID real a partir do
Server ID do OTB. Informar também o `client_id` é recomendado: ele funciona como
uma trava e a operação é recusada se o mapeamento não coincidir. Um modelo está em
`examples/items-properties.csv`:

```csv
sequence,server_id,client_id,dat_add_flags,dat_remove_flags,otb_add_flags,otb_remove_flags
1,22904,22019,unpassable,,block_solid,
```

`edit-ground-speeds` altera exclusivamente o payload de velocidade dos pisos no
DAT e no OTB. O manifesto usa `sequence,server_id,client_id,ground_speed`. A
operacao exige que o Server ID seja do grupo ground, confirma o mapeamento do
Client ID e recusa a alteracao se os valores atuais do DAT e OTB divergirem.

`edit-item-elevations` altera exclusivamente o payload numerico da propriedade
de elevacao no DAT. O manifesto usa `sequence,server_id,client_id,elevation`.
A operacao exige mapeamento OTB exclusivo, a flag `has_height` no OTB e uma
propriedade de elevacao ja existente no DAT; aparência e demais propriedades
permanecem intactas.

As listas de flags usam `|` quando houver mais de uma propriedade. O editor DAT
aceita somente flags booleanas sem payload, preservando integralmente propriedades
como velocidade, luz, elevação e market data. No OTB, estão disponíveis os 28 bits
funcionais usados pelo servidor, entre eles `block_solid`, `movable`,
`block_projectile`, `block_pathfind`, `pickupable` e `walk_stack`.

Antes da escrita, a ferramenta cria e testa `860.rar`, `items.rar` e `world.zip`.
DAT e OTB são preparados, reabertos e validados; o SPR, OTFI, mapa e arquivos
textuais permanecem intocados. Uma falha no commit ou na validação restaura os dois
binários anteriores.

## Duração individual dos frames

`edit-animation-durations` altera somente os pares mínimo/máximo de duração de
cada frame no DAT. Sprite IDs, pixels, propriedades, modo assíncrono, loop e frame
inicial são preservados. Os tempos são separados por `|`:

```csv
sequence,category,client_id,frame_durations_ms
1,items,13544,100|100|700
```

As categorias aceitas são `items`, `outfits`, `effects` e `missiles`. Para outfits,
a edição exige exatamente um frame group animado.

A operação cria a versão obrigatória, valida que nenhum registro DAT fora do alvo
mudou e faz commit transacional somente do DAT.

## Inspetor de posição OTBM

`inspect-map-position` é somente leitura. Ele percorre o mapa sem carregá-lo todo
na memória e informa o tipo do tile, house ID, flags do tile e a pilha na ordem
visual, com posições iniciadas em 1. Para cada item, mostra Server ID, Client ID,
grupo e flags OTB/DAT. Itens dentro de containers recebem `nested_depth` maior que
zero.

## Exportação de PNG

`export-png` lê o DAT e o SPR sem modificar os arquivos oficiais e recompõe a
aparência na mesma ordem usada pelo `ThingType::exportImage` do client. Itens
multitile são reposicionados na ordem visual correta; layers e patterns ficam no
eixo horizontal, enquanto frames, pattern Y e pattern Z ficam no eixo vertical.
Outfits com mais de um frame group geram um PNG separado para cada grupo.

Por padrão, os arquivos são gravados em `export/<categoria>/`. A categoria pode
ser `items`, `outfits`, `effects` ou `missiles`. Items aceitam Client ID ou Server
ID; outfits, effects e missiles usam seus IDs DAT:

```powershell
python -m nwoassets export-png . items 24300 24302 --id-kind server
python -m nwoassets export-png . outfits 128 129 --out-dir export\outfits
python -m nwoassets export-png . effects 1357 1359 --out-dir export\effects
```

O comando recusa sobrescrever um PNG existente, salvo quando `--overwrite` for
informado. O relatório inclui os IDs resolvidos, dimensões, layers, patterns,
frames, Sprite IDs e SHA-256 de cada PNG.

## Comandos

- `scan`: inventaria e calcula SHA-256;
- `inspect-client`: inspeciona OTFI, DAT, SPR e OTB;
- `inspect-world`: inspeciona o OTBM e configurações de `assets/world`;
- `inspect-configs`: inspeciona XML e OTML;
- `validate`: executa a validação integrada;
- `create-version`: cria manualmente o conjunto RAR/RAR/ZIP;
- `import-items`: versiona e modifica DAT, SPR e OTB no local.
- `import-effects`: versiona e modifica efeitos animados no DAT e SPR;
- `import-missiles`: versiona e preenche Missile IDs reservados preservando o layout direcional de uma referência;
- `import-outfits`: versiona e preenche outfits reservadas no DAT e SPR usando outra outfit como referência;
- `edit-animation-durations`: versiona e edita tempos individuais de frames no DAT;
- `edit-item-properties`: versiona e edita flags booleanas DAT/OTB;
- `edit-ground-speeds`: versiona e edita a velocidade dos pisos no DAT/OTB;
- `inspect-map-position`: lê a pilha de uma coordenada do OTBM sem modificá-lo.
- `export-png`: exporta items, outfits, effects e missiles do DAT/SPR como PNG.

Use `--deep-spr` para validar o RLE de todos os sprites. A pasta `versions/` é
ignorada pelo inventário e pelo Git para não reprocessar nem versionar os backups.

## Garantias

Antes do commit, o importador confere o `SpriteHash` contra 64 itens distribuídos
pela baseline, reabre os pixels novos, preserva registros DAT não alvo e o payload
dos sprites antigos, mantém relações N:1 do OTB e verifica que OTFI, OTBM, XMLs e
OTMLs não mudaram. Toda versão permanece disponível em `versions/` para restauração
manual adicional.
