# Auditoria das estatuas de personagens

## Sistema atual

- As estatuas sao registradas em `statueVoc`, no arquivo `142-vocations_and_classes.lua`.
- Dentro de uma house, 100 fragmentos sao transformados na primeira orientacao da estatua.
- Ao usar qualquer orientacao da estatua, ela retorna 100 fragmentos.
- Cada personagem usa um par de Server IDs alternado pelo atributo `rotateTo`.
- As estatuas existentes usam OTB `block_solid`, `block_pathfind`, `pickupable`, `movable` e `rotatable`.

## Substituicao existente

| Personagem | Server IDs | Client IDs |
|---|---:|---:|
| Neji | 14811 / 14812 | 13929 / 13930 |

## Novos pares

| Personagem | Fragmento | Server/Client IDs |
|---|---:|---:|
| Hinata | 17263 | 7404 / 7409 |
| Kabuto | 17241 | 7430 / 7434 |
| Kakashi | 17242 | 7435 / 7439 |
| Kiba | 17264 | 7440 / 7443 |
| Kimimaro | 17246 | 7450 / 7457 |
| Shino | 17262 | 7459 / 7460 |
| Zabuza | 17258 | 7461 / 7462 |

## Validacao dos destinos

- Todos os 14 vinculos Server ID/Client ID sao exclusivos no OTB.
- Nenhum destino aparece em scripts funcionais, armas, actions, NPCs, clients ou codigo nativo.
- A varredura integral do OTBM conferiu 7.824.286 tiles e 2.105.106 nodes de item sem encontrar os destinos.
- Os itens anteriores serao substituidos integralmente no XML para remover atributos de equipamento, potion e armas.
- As propriedades DAT/OTB serao alinhadas ao par de estatuas do Neji.
