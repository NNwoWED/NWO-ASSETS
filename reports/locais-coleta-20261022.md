# Locais de coleta no mapa — 22/10/2026

Fontes: `D:\download\lista-para-o-coletor.txt`, `Server-Data-Nwo/data/lib/765-skills_system.lua`, `Server-Data-Nwo/data/items/items.xml`, `NWO-ASSETS/assets/items/items.otb` e `NWO-ASSETS/assets/world/mapanovo.otbm`. O mapa operacional do servidor em `Server-Data-Nwo/data/world/mapanovo.otbm` tem o mesmo SHA-256 do mapa canônico: `AC32C669BED3512D69AE054CAFC8564A236C9894B22BBC9A0E9D7ACAEFAD5512`.

## Arquivos de posições

- `locais-coleta-20261022.csv`: 1.196 SQMs físicos, com X/Y/Z, nome do nó, materiais configurados, Server ID, Client ID, nível e ferramenta. Há 1.205 instâncias de nós: nove SQMs contêm dois depósitos de minério empilhados, registrados juntos na mesma linha.
- `locais-pescaria-candidatos-20261022.csv`: 100 SQMs de água do mapa, adjacentes a tiles sem água, para vistoria. São amostras de posições possíveis, não um inventário de todas as águas nem confirmação de captura ou acesso.

O campo `setor_por_x` do primeiro CSV divide o mapa apenas pela coordenada X. Ele não certifica vila, cave nem rota. A presença do nó no OTBM e a configuração de recompensa no servidor não comprovam coleta no jogo; essa confirmação ainda exige teste e captura em cada ponto.

## Nós de coleta encontrados

| Profissão | Material configurado | Nó no mapa (Server ID) | Nós | Exemplo X,Y,Z |
|---|---|---|---:|---|
| Mineração | Pedra de Sódio | Pedra com sódio (14248) | 109 | 1212,926,7 |
| Mineração | Carvão | Pedra com carvão (14249) | 101 | 852,838,7 |
| Mineração | Minério de Cobre | Pedra com cobre (14244) | 75 | 1364,915,7 |
| Mineração | Minério de Ferro | Pedras com ferro (14245) | 255 | 495,1014,7 |
| Herbalismo | Fibra, Pimenta Sansho ou Erva de Shikkotsu | Arbusto Silvestre (17404) | 154 | 1106,879,7 |
| Herbalismo | Lótus da Névoa | Arbusto Orvalhado (14571) | 117 | 1883,723,7 |
| Herbalismo | Raiz de Sunagakure | Arbusto Árido (14572) | 73 | 547,1200,7 |
| Lenhador | Carvalho da Folha | Árvore de Carvalho (14573) | 128 | 1539,590,7 |
| Lenhador | Carvalho Nobre | Carvalho da Névoa (14574) | 30 | 1710,1205,6 |
| Lenhador | Madeira de Acácia Seca | Acácia do Deserto (14575) | 163 | 578,853,7 |

As coordenadas da tabela são exemplos reais do OTBM. O CSV contém todos os pontos de cada nó e preserva andares distintos.

## Pescaria

O servidor aceita como alvo água com Server IDs 4608–4613. Ele sorteia o recurso conforme nível, vara e posição; não há um objeto de peixe fixo no OTBM. Os 100 SQMs do CSV são locais para testar a pesca. A coluna de espécies indica possibilidade pelo código, não captura observada.

| Espécie | Restrição regional no código | Nível exigido no recurso |
|---|---|---:|
| Ayu | Nenhuma | 1 |
| Salmão | Nenhuma | 6 |
| Carpa | Três faixas de coordenadas no leste do mapa | 10 |
| Sayori | Nenhuma | 10 |
| Unagi | Nenhuma | 15 |
| Fugu | Nenhuma | 20 |
| Traíra do Oásis | X 326–1063, Y 1056–1431, Z 7 | 10 |
| Peixe Escorpião | X 326–1063, Y 1056–1431, Z 7 | 20 |
| Robalo da Névoa | Duas faixas de coordenadas no leste do mapa | 20 |

Robalo da Névoa é um recurso adicional encontrado no código, além dos materiais da lista inicial. As exigências de nível acima são as de `gatherResources`, usadas na seleção da captura.

## Divergências e itens pendentes

- **Bronze**: não há depósito de Bronze em `gatherResources`. O recurso de nível 15 é **Minério de Cobre**, com 75 nós no mapa. Os dois nomes não foram equiparados.
- **Sódio e Carvão**: o código exige, respectivamente, nível 5 e nível 0; a lista de referência informa 1 e 5. Confirmar a apresentação no cliente.
- **Lótus da Névoa, Carvalho Nobre e Madeira de Acácia Seca**: o código exige níveis 30, 30 e 20, enquanto a lista informa 5, 5 e 10.
- **Unagi**: o código exige nível 15; a lista informa 20+.
- **Ouro, Prata e Sal-Gema**: nenhum nó desses materiais aparece em `gatherResources`. Nomes de itens e arte não bastam para marcá-los como coletáveis.
- **Traíra do Oásis, Fugu e Peixe Escorpião**: estão configurados como capturas no servidor, mas precisam de teste no jogo antes de publicação como disponíveis. O código não restringe Fugu a uma região.

Validação da baseline: `validation-locais-coleta-20261022.json` (`passed: true`, zero erros, zero avisos). Nenhum arquivo canônico de asset ou mapa foi alterado.
