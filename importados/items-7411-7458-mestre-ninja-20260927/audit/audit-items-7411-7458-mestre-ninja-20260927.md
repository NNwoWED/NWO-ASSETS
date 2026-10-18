# Auditoria de importacao - itens 7411/7426/7429/7458 e Mestre Ninja

## Itens

- Operacao: substituir somente a aparencia de itens existentes.
- Politica: preservar integralmente propriedades DAT/OTB, vinculos, nomes XML e comportamento dos itens.
- Layout: PNG RGBA estatico 32x32, uma camada e um frame.
- Os quatro vinculos OTB sao exclusivos e usam o mesmo valor para Server ID e Client ID.

| Server ID | Client ID | Item atual | Uso identificado | PNG |
|---:|---:|---|---|---|
| 7411 | 7411 | Ornamented axe | arma melee nivel 50 | 7411.png |
| 7426 | 7426 | Amber staff | arma melee nivel 40 | 7426.png |
| 7429 | 7429 | Nidaime Boots | arma melee nivel 75 | 7429.png |
| 7458 | 7458 | Fur cap | equipamento de cabeca | 7458.png |

## Mestre Ninja

- Operacao: usar Outfit ID reservado e vazio.
- Outfit ID: 1021.
- Referencia estrutural: Outfit 15.
- Layout: sheet RGBA 256x1024, 2x2, quatro direcoes, dois frame groups e oito frames por grupo.
- Busca semantica: nenhuma referencia ativa ao Outfit ID 1021 no servidor, client PC ou mobile.

## Validacao anterior

- `validate --deep-spr`: aprovado sem erros ou avisos.
- Outfit 1021: dois grupos vazios, quatro direcoes, zero Sprite IDs referenciados.
