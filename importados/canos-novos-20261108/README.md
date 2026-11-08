# Canos de metal — somente peças diferentes

Comparação dos pixels dos dez PNGs fornecidos com o catálogo de itens estáticos do DAT/SPR: quatro peças novas e seis duplicadas. PNGs originais preservados sem alteração.

## Itens adicionados

| PNG | Server ID novo | Client ID novo | Referência SID / CID | Dimensões |
| --- | ---: | ---: | --- | --- |
| 12.png | 27090 | 26205 | 27027 / 26142 | 96×96 |
| 34.png | 27091 | 26206 | 27029 / 26144 | 96×96 |
| peca restante12.png | 27092 | 26207 | 27031 / 26146 | 64×64 |
| peca22.png | 27093 | 26208 | 27030 / 26145 | 64×64 |

Mantidas as propriedades DAT/OTB/XML dos canos de referência, inclusive bloqueio, deslocamento e demais flags. As quatro peças são estáticas, com uma camada e sem padrões extras. Os nomes XML seguem as referências Metal Pipe 1, 3, 5 e 4; os IDs novos distinguem as orientações.

## Duplicados não importados

| PNG | Server ID já existente | Observação |
| --- | --- | --- |
| 1.png | 27027 | Pixels idênticos. |
| 2.png | 27028 | Pixels idênticos. |
| 3.png | 27029 | Pixels idênticos. |
| modelo feio mas que pode ser usado.png | 27032 | 64×63: idêntico ao 27032 ao considerar uma linha transparente inferior. Comparação em memória; original não editado nem importado. |
| peca restante1.png | 27031 | Pixels idênticos. |
| peca2.png | 27030 | Pixels idênticos. |

Versão completa e testada antes da gravação: `20261108-043809-791533`.
Mapa preservado: SHA-256 `0e6b4ec99c87f8ddb3000cec35581df9eec3a15fa2c26a59354d6b6f37f08390`. Sem alteração do OTBM ou das peças antigas.

Validação profunda aprovada sem erros/avisos; quatro itens reexportados e conferidos pixel a pixel. Sincronização concluída com servidor, RME, PC, mobile e NWO-STUDIO, com hashes conferidos e RARs testados. Verificação estática mobile aprovada; APK dispensado pelo usuário, sem teste in-game nesta tarefa.

O manifesto importa somente os quatro PNGs da primeira tabela. Os seis duplicados foram arquivados aqui apenas como fontes e evidência da comparação.

Relatórios: `NWO-ASSETS/reports/*canos*20261108.json`. Prévia: `NWO-ASSETS/work/canos-novos-20261108/canos-novos-conferencia.png`.
