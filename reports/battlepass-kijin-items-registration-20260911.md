# Registro dos itens Kijin do Passe de Batalha — 11/09/2026

## Escopo aprovado

- Operação: usar itens reservados e sem uso anterior.
- Finalidade: substituir os placeholders premium do Passe de Batalha.
- Uso no mapa antes da importação: zero ocorrências para os Server IDs 14637, 14638 e 14639.
- Aparência anterior: placeholder estático 32×32, Sprite ID 80990, sem nome no `items.xml`.

## Itens

| Item | Passe | Server ID | Client ID | PNG original | Layout | Propriedades |
|---|---:|---:|---:|---|---|---|
| Kijin Depot | Premium 33 | 14637 | 13758 | `kijin-depot-original.png` | 96×96, 3×3 tiles, 1 frame | Não empilhável, móvel; uso somente no piso de house por action dedicada. |
| Kijin Backpack | Premium 14 | 14638 | 13759 | `kijin-backpack-original.png` | 32×32, 1×1 tile, 1 frame | Container não empilhável, 40 espaços, slot backpack. |
| Kijin Shuriken Backpack | Premium 18 | 14639 | 13760 | `kijin-shuriken-backpack-original.png` | 32×32, 1×1 tile, 1 frame | Container não empilhável, 8 espaços, slot ammo, restrito a shurikens/kunais. |

## Política DAT/OTB

- A importação alterou apenas as aparências dos Client IDs reservados e os respectivos SpriteHash no OTB.
- Nos três itens foi removida a propriedade `stackable` no DAT e no OTB.
- Nos Client IDs 13759 e 13760 foi adicionada a flag DAT `container`.
- Nenhum payload desconhecido, atributo de velocidade, luz, elevação ou market data foi regravado.

## Arquivos e hashes dos PNGs originais

- Depot: `6B2DBAB094B55DB039ED6F09E36059915B1E55EEE95ED25B8D3E7E21804AA681`
- Backpack: `969F0B458E7900971E09E1B097825A01BA249E34CC3414D1B6D0A54289260E02`
- Shuriken Backpack: `C2AB6AA48D1BE7F41E9D0B77B0AACB53D0EBB2CC881CF483124DED130B413E82`
