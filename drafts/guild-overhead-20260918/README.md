# Emblemas de clã — pixel art 18×18

Uso: versão pequena ao lado do nome do personagem, PC e mobile. Os originais 256×256 do módulo não foram substituídos. PNGs de interface, sem Client ID/Server ID e sem modificação de DAT, SPR, OTB ou mapa.

## Arquivos

- `atlas-generated.png`: arte gerada pela ferramenta integrada ImageGen, a partir das referências existentes. Original preservado também na pasta de imagens geradas do Codex.
- `export-overhead.ps1`: recorte determinístico da folha realmente recebida (1586×992), amostragem nearest-neighbor, paleta limitada e alpha binário; contorno escuro de um pixel. Não usa suavização.
- `overhead/`: 24 bases (4 formas × 6 cores) e 8 símbolos sobrepostos. Todos os arquivos são RGBA 18×18.
- `manifest.json`: recortes, dimensões e hashes SHA-256.
- `all-combinations-1x.png` e `all-combinations-3x.png`: 192 combinações, colunas por forma/cor e linhas por símbolo. A ampliação replica pixels, não suaviza.

Copiados byte a byte para `nwo-otclient-mehah-4.0/mods/game_alliance/images/overhead/` e `nwo-mobile/client/mods/game_alliance/images/overhead/`.

O atlas gerado não respeitou a resolução exata pedida; por isso não é usado diretamente pelo client. Somente os PNGs normalizados de 18×18 são carregados, sem filtro suave, pelos dois `src/client/creature.cpp`. As imagens grandes e o módulo de seleção permanecem intactos. Recompilar e distribuir executável/APK junto dos novos PNGs; copiar apenas os PNGs não muda os caminhos embutidos nos executáveis antigos.

## Prompt usado (ImageGen integrado, não CLI/API)

Create ONE production sprite atlas for tiny MMORPG overhead guild emblems. Inputs1-4 are shape references (pointed shield, round medallion, hexagon, fork-bottom cloth banner). Input5 is reference for fox mask symbol. Redesign as STRICT LOW-RESOLUTION pixel art, NOT painted icons. Transparent PNG. Atlas exactly8 columns x5 rows of equal square cells, no gaps, no labels or grid. Each cell is a LOGICAL18x18 pixel sprite with single-color square pixel blocks. Ideally output144x90; if larger required upscale the entire logical144x90 atlas uniformly by nearest-neighbor to2304x1440, each logical pixel16x16. Every shield fits cell x1..16,y1..16. No antialias, glow, smoothing, gradients or tiny ornaments. One-pixel dark charcoal outline, simple gold rim with2tones, three-tone saturated interior, frontal view, center clear for overlay symbol. Rows1..4 correspond exactly to the4reference shapes. Each row has6colored versions, in columns1..6: golden yellow, red, cyan turquoise, purple, royal blue, forest green. Columns7..8 of rows1..4 are EMPTY TRANSPARENT. Row5 has8SEPARATE OVERLAY symbols, no shield/background: col1 ivory/gold Konoha leaf spiral; col2 red and ivory Uchiha fan; col3 three cyan breaking waves with ivory crests; col4 gold four-point shuriken with turquoise center; col5 ivory mountain with gold rising sun; col6 white fox face mask with red marks asreference5; col7 horizontal ivory eye outline with red iris and blackpupil/tomoe; col8 ivory crescent moon with goldstar onright. These8overlay symbols each fit a10x10logical pixel area centered in18x18cell, onepixel darkoutline for readability across all6background colors. Simplify aggressively into readable silhouettes at ACTUAL18x18 screen size. Background must be genuine transparent alpha, never black or checkerboard. All cells perfectly aligned for deterministic crop. No drop shadows.

Referências: `banner-base-1-1.png`, `banner-base-2-1.png`, `banner-base-3-1.png`, `banner-base-4-1.png`, `banner-logo-6.png`, em `nwo-otclient-mehah-4.0/mods/game_alliance/images/`.

## Validação

Executar na raiz NWO NEW:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File nwo-otclient-mehah-4.0/tests/guild_overhead_icons_test.ps1
```

Verifica 32 arquivos nos dois clients, dimensões, hashes, alpha binário, paleta, 192 combinações distintas, caminhos nativos, filtro e preservação do tamanho das imagens grandes. Folhas conferidas visualmente em 1× e 3×. Compilação e QA dentro do jogo/Android não executados nesta tarefa.
