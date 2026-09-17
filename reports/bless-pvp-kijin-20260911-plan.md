# Operação autorizada — 11/09/2026

- Usar item reservado: Bless PvP, SID 14686 / CID 13807, PNG `sprites/Icon_Blessing_PVP_2.png`, RGBA8 32x32, estático. DAT vazio (sprite 0), mapeamento OTB único. Ativa a flag PvP existente; não adiciona preço.
- Propriedades autorizadas separadamente: adicionar pickupable e stackable em DAT/OTB; manter movable no OTB. Nenhum payload desconhecido será alterado.
- Substituir: Kijin Depot, SID 14637 / CID 13758, PNG `sprites/locker1.png`, RGBA8 96x96 (3x3 tiles), estático. Preservar todas as propriedades DAT/OTB, XML, ação e recompensa do Passe de Batalha.
- Ícone de status: `sprites/Icon_Blessing_PVP.png`, RGBA8 32x32, copiado sem transformação para os status do desktop/mobile. Bit 29 no enum de ícones, sem novo opcode/polling. Ícone visível também com PvP sozinha.
- Variante `sprites/Icon_Blessing_PVP_3.png`: exclusão autorizada; nenhuma outra exclusão.
- Baseline obrigatória: `assets/860/Tibia.dat`, `Tibia.spr`, `assets/items/items.otb`, `items.xml`, `assets/world/mapanovo.otbm`. Versões imutáveis automáticas antes de cada operação; validação deep-spr e sync-runtime obrigatórios.
- Não alterar percentuais normais, classificação de morte PvP nem regra antidrop. Nenhum banco, publicação, reinício ou build APK nesta operação.

## Resultado local

- Importação: `reports/import-bless-pvp-kijin-20260911.json`, commit/pixels/hashes aprovados, zero erros, mapa e registros não alvo preservados. Versão `20260911-211741-749763`.
- Propriedades: `reports/properties-bless-pvp-20260911.json`, commit aprovado, somente SID 14686, DAT `0510ff` e OTB flags 224. Versão `20260911-211920-368914`.
- Validação final: `reports/validation-final-bless-pvp-kijin-20260911.json`. Sync aprovado: `reports/sync-runtime-bless-pvp-kijin-20260911.json` (servidor, RME, PC e RAR verificados).
- Após validação e sync, PNGs usados e os dois manifestos movidos juntos para `importados/bless-pvp-kijin-20260911/`. Cada PNG original também é o PNG efetivamente importado/copiado, sem transformação. Variante `_3` removida com autorização.
- Código/status PC/mobile e testes registrados nos logs gerais da raiz. Build do servidor e QA em jogo pendentes; APK/mobile não empacotado, sem cópia manual de DAT/SPR mobile.
