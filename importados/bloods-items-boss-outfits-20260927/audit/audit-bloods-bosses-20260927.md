# Auditoria de destinos - itens e bosses

## Itens

- Operacao: substituir a aparencia de itens reservados existentes.
- Faixa: Server IDs 14607 a 14625, vinculados exclusivamente aos Client IDs 13728 a 13746.
- Uso: nenhum dos Server IDs aparece no mapa canonico ou em sistemas ativos pesquisados.
- Layout: 19 PNGs RGBA estaticos de 32x32, uma camada e um frame.
- Politica: preservar integralmente propriedades DAT/OTB e trocar apenas sprites e SpriteHash.

| Server ID | Client ID | Nome | PNG |
|---:|---:|---|---|
| 14607 | 13728 | Blood Iwagakure | blood-iwagakure.png |
| 14608 | 13729 | Blood Kirigakure | blood-kirigakure.png |
| 14609 | 13730 | Blood Konoha | blood-konoha.png |
| 14610 | 13731 | Blood Kumo | blood-kumo.png |
| 14611 | 13732 | Blood Suna | blood-suna.png |
| 14612 | 13733 | Bola de Cristal do Kage | Item_Bola_de_cristal_do_Kage-zzzzz.png |
| 14613 | 13734 | Chakra Pouch | crakra-pouch.png |
| 14614 | 13735 | BP Twitch | BP_Twitch.png |
| 14615 | 13736 | Sardinha | Sardinha.png |
| 14616 | 13737 | TP Home | tp-home.png |
| 14617 | 13738 | TP Iwa | tp-iwa.png |
| 14618 | 13739 | TP Kiri | tp-kiri.png |
| 14619 | 13740 | TP Konoha | tp-konoha.png |
| 14620 | 13741 | TP Kumo | tp-kumo.png |
| 14621 | 13742 | TP Suna | tp-suna.png |
| 14622 | 13743 | Peixe-Gato | Peixe-Gato.png |
| 14623 | 13744 | Prata | prata.png |
| 14624 | 13745 | Cobre | cobre.png |
| 14625 | 13746 | DG Stamina Potion | dg-stamina-potion.png |

## Bosses

- Operacao: usar Outfit IDs reservados e vazios.
- Faixa final: Outfit IDs 1011 a 1020, sem sprites e sem referencias encontradas no servidor, client PC ou mobile.
- A faixa baixa 38 a 47 foi descartada e restaurada ao estado vazio antes da sincronizacao.
- Layout 2x2: nove sheets RGBA 256x1024 usam Outfit 15 como referencia estrutural.
- Layout 3x3: Sand Disaster RGBA 384x1536 usa Outfit 631 como referencia estrutural.
- Animacao: dois frame groups direcionais, oito frames por grupo, preservando os tempos das referencias.

| Outfit ID | Boss | Referencia |
|---:|---|---:|
| 1011 | Adorador Shukaku Boss | 15 |
| 1012 | Alma Afogada Boss | 15 |
| 1013 | Assassin Boss | 15 |
| 1014 | Duna Boss | 15 |
| 1015 | Marionete Boss | 15 |
| 1016 | Nomade Perdido Boss | 15 |
| 1017 | Predador da Nevoa Profunda Boss | 15 |
| 1018 | Sand Disaster Boss | 631 |
| 1019 | Scorpion Boss | 15 |
| 1020 | Shukaku Fragment Boss | 15 |

## Validacoes anteriores

- `validate --deep-spr`: aprovado sem erros ou avisos.
- OTB: todos os vinculos Server ID/Client ID sao exclusivos.
- OTBM: 7.824.286 tiles e 2.105.106 nodes de item verificados, sem uso da faixa reservada.
- Busca semantica: nenhuma referencia ativa aos Outfit IDs 1011 a 1020.
