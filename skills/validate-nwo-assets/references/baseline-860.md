# Baseline NWO 8.60

## Invariantes estáveis

- Perfil esperado: `tibia-860-v2-custom-extended`.
- DAT: assinatura `0x4C2C7993`.
- SPR: assinatura `0x4C220594`.
- OTFI: IDs estendidos ativos; interpretar Sprite IDs como `uint32`.
- OTB esperado: `OTB 3.20.20-8.60`.
- A flag DAT local `0x22` foi observada sem payload apenas nesta baseline; não a
  generalizar para outros clientes 8.60.

As assinaturas DAT e SPR formam um par. Uma combinação mista não é um perfil
parcialmente válido: é erro de perfil e deve encerrar a inspeção com código `2`.

## Baseline conhecida em 2026-07-30

- 30.123 registros DAT.
- 245.380 sprites.
- 25.144 nós OTB, com Server IDs contínuos de 100 a 25.243.
- Três variantes distintas de mapa.
- `items/new.xml` pode ser tratado como fragmento e gerar aviso.

Esses números ajudam a detectar regressões, mas não substituem os checks emitidos
pela CLI nem autorizam publicação.

## Semântica dos códigos da CLI

- `0`: execução bem-sucedida e, para `validate`, checks obrigatórios aprovados.
- `1`: validação concluída com erros.
- `2`: erro esperado de formato, perfil ou I/O.

O runner reserva `3` para detectar mutação do status Git.
