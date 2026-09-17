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

## Sincronização com servidor e client

Depois de qualquer alteração validada em `items.otb`, `items.xml`, `Tibia.dat`
ou `Tibia.spr`, execute `sincronizar-assets-runtime.bat` ou o comando
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
`Tibia.spr` para `nwo-otclient-mehah-4.0/data/things/860` e recria
`nwo-otclient-mehah-4.0/data/things/860.rar`. As publicações usam arquivos
temporários, conferência de hash e rollback; o RAR é testado pelo WinRAR antes
de substituir o arquivo anterior.

## Versionamento obrigatório

Antes de substituir DAT, SPR ou OTB, `import-items`, `import-effects` e `import-outfits` executam automaticamente o
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
Nesta fase, o Client ID deve existir entre `100..24522`; a aparência continua com
uma camada e sem patterns adicionais.

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

## Importação de outfits

`import-outfits` recebe uma folha completa no mesmo layout produzido por
`export-png`. O manifesto aceita
`sequence,operation,outfit_id,reference_outfit_id,source_path`; a coluna
`operation` é opcional e assume `reserved` quando omitida. Em `reserved`, o
Outfit ID alvo precisa estar vazio. Em `replace`, o alvo precisa estar ocupado e
pode ser sua própria referência para preservar dimensões, frame groups, timings
e demais metadados visuais. As propriedades do alvo são sempre preservadas. A
operação versiona, valida e modifica somente DAT e SPR.

## Propriedades DAT/OTB

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
