# Guia de mapeamento do NWO

Consolidação de 08/11/2026. Regras de construção, acabamento e revisão aprendidas com os mapas de referência e as correções do East City até o mapa 28. O fluxo oficial de arquivos e publicação está no [AGENTS.md](../AGENTS.md).

## Base de trabalho

- Use o arquivo e a aba indicados pelo usuário. Quando houver edições manuais posteriores à entrega, compare a versão salva atual com a entrega anterior por coordenada, andar, pilha, chão, presença ou ausência do SQM e metadados. Registre o hash da base usada.
- Preserve a intenção de cada edição autoral no nível em que ela foi feita. Um novo piso pode receber acabamento autorizado no mesmo SQM. Uma borda corrigida, um objeto retirado ou um tile apagado deve conservar a decisão do usuário. Uma troca de material pode preservar o recorte e a ordem da pilha. Consulte o [registro autoral do East City](reports/map-east-city-authorial-registry.json).
- Delimite os andares, os contornos e os acessos afetados. Quando o usuário pedir um piloto, trabalhe naquele trecho e confira a ligação com o entorno. Leve o princípio para outros locais somente quando a geometria e os materiais forem compatíveis.
- Use a paleta do próprio mapa. O East City trabalhado nesta série é 10.41 e usa os assets em `C:/Users/Wedson/Desktop/Release/data/1041`. O mapa operacional do projeto é `assets/world/mapanovo.otbm`, com baseline 8.60. Confira o vínculo Server ID → Client ID no OTB e a aparência no DAT/SPR antes de escolher a peça.

## Construção do relevo e dos caminhos

1. Desenhe primeiro a forma dos maciços, pisos, patamares, curvas e acessos. Separe os encontros planos dos desníveis. Quando o trabalho for só de acabamento, parta do relevo atual.
2. Monte as faces pelo maciço que lhes dá origem. Confira a direção, o material e a extensão real da face. Use uma cobertura por direção, com peças complementares nas quinas. Ao preencher uma antiga abertura com maciço, revise as faces independentes que ficaram sobrepostas. Ao abrir uma passagem, recalcule o contorno pela geometria atual.
3. Faça o acabamento interno e externo entre níveis. A borda plana sobre o andar superior pode acompanhar a face do andar inferior. Use a paleta do apoio que aparece na cena. Misture pedra sobre neve e neve sobre pedra onde cada camada tem encaixe visível.
4. Finalize as transições no mesmo plano, as terminações e o contato com o cenário. Confira o efeito sobre circulação, bloqueio, projéteis, elevação, velocidade do piso e transições de andar quando aplicáveis.

### Naturalidade em janelas de três SQMs

- Cada trecho de três SQMs é uma composição das **duas margens**, da largura e da curva do caminho. Varie entradas, reentrâncias, alargamentos, bifurcações e finais. Compare a silhueta inteira. Evite repetir a composição seguida ou criar um ciclo previsível A–B–A–B.
- Dentro de cada janela, use cada item de acabamento no máximo uma vez, contando as duas margens. IDs com aparência nativa idêntica contam como o mesmo padrão. Partes de um desenho podem voltar em outra composição, com encaixes e formas diferentes.
- Desloque a janela **um SQM por vez**. Revise os encontros entre trechos, os cantos e as terminações. Controle a sequência de perfis e também a geometria dos próprios SQMs. Preserve a continuidade visual e os acessos quando variar a largura.
- Dosagem de pedra e diversidade são decisões separadas. Distribua a pedra em faixas e manchas de larguras e comprimentos diferentes, com interrupções naturais e recortes de neve. A redução brusca de intensidade que deixou apenas um perfil repetido foi rejeitada. Escolha a presença de pedra pela cena e pelas referências.
- Quando faltarem variantes compatíveis, refine a forma local dentro do escopo autorizado. Apoio, continuidade e acesso têm prioridade sobre a contagem de padrões.

## Cortes secos, suporte e camadas

| Sinal na cena | O que conferir | Como ajustar |
| --- | --- | --- |
| Linha reta ou canto quadrado no encontro de dois pisos ou de duas bordas | Segmento contínuo exposto, lado da peça, contato com o SQM seguinte e camadas que cruzam a emenda | Ajuste o par ou conjunto, com um recorte, uma terminação menor ou uma continuação apoiada. Confira também os contatos externos. |
| Piso ou borda termina em degrau sobre a face de baixo | Projeção dos dois andares, material da face visível e alinhamento real dos sprites | Use o acabamento interno ou externo correspondente ao relevo. Uma borda parcial pode completar a passagem visual entre níveis e manter o volume da parede. |
| Neve aérea ou ponta de pedra isolada | Apoio de cada fragmento, orientação do lado reto, ligação pelo contorno e cobertura por objetos | Reoriente, encurte ou retire o fragmento que ficou solto. Preserve as peças do mesmo SQM que encaixam na montanha. |
| Cor de pedra comum em trecho congelado | Corpo, faces, piso e patamares projetados que sustentam o contorno | Troque a paleta da borda mantendo sua forma, quando o perfil equivalente encaixar. Preserve os encontros legítimos com rocha marrom. |
| Face repetida ou peça que sumiu sob outra camada | Pegada, direção, ordem de desenho e visibilidade no conjunto | Retire a cobertura redundante quando confirmada. Em correções visuais, conserve os SQMs cuja mudança ficaria totalmente encoberta. |

- **Confira o lado inteiro do sprite.** Quatro cantos compatíveis ou uma boa média de contato podem esconder uma faixa reta exposta. Olhe os segmentos contínuos e os encontros de dois a quatro SQMs. Uma peça pode encaixar de um lado e deixar corte seco no outro.
- **Suporte e encaixe são verificações diferentes.** A neve pode estar apoiada e terminar numa linha seca. Um pixel em contato, uma parede escura atrás ou um item no SQM vizinho podem gerar falsa impressão de apoio. Siga a ligação dos pixels até a superfície que sustenta o fragmento. Essa ligação pode contornar uma quina.
- **Reavalie a pilha após cada troca.** Estreitar pedra pode tirar o apoio de neve. Remover neve pode expor uma quina solta ou uma ponta reta de pedra. Corrija o conjunto até a cena ficar contínua. Uma pilha com duas quinas opostas pode ter uma peça correta e outra solta.
- **Um SQM só de bordas pode ser legítimo.** O acabamento pode encaixar no andar vizinho, como em `referencia3.otbm`. Use as superfícies existentes como apoio. Uma borda visual pode ocupar um tile sem adicionar chão caminhável ou duplicar uma face.
- **Renderize com os sprites nativos.** Respeite transparência, dimensão, âncora, ordem da pilha, offsets e elevação. Na projeção de superfície usada no East City, a posição na tela é `(x - (7 - z), y - (7 - z))` em SQMs. Confira as vistas dos níveis envolvidos com a projeção e o escurecimento. Na triagem de corpos 2×2, o quadrante noroeste 32×32 serviu como semente conservadora do topo horizontal. A extensão restante precisa de conferência na cena.
- **Use métricas para localizar candidatos.** Compare a silhueta e as arestas na escala nativa, com as peças vizinhas e os andares relevantes. Um alerta pode corresponder a uma transição válida ou oculta. A aprovação visual do conjunto prevalece sobre zerar contadores.

## Paleta de referência do East City 10.41

| Função | Server IDs usados no estudo |
| --- | --- |
| Corpo de montanha comum | `585`, `2961–2962`, `3016` |
| Corpo de montanha congelada | `3471–3472`, `3663–3665` |
| Piso plano de pedra congelada | `3690–3695`, `3771–3774` |
| Borda plana de pedra comum e congelada | `207–246` e `3696–3735`. Nos 40 pares conferidos, `SID congelado = SID comum + 3489`, com a mesma máscara e propriedades físicas. Aplique a troca onde o apoio é congelado. |
| Piso e borda de neve | Piso `3834–3839`. Borda `3840–3861`. |
| Piso e borda de gelo | Piso `4224–4225`. Borda `4230–4254` em pisos adjacentes com apoio e contato na direção do gelo. |
| Faces e peças especiais | Escolha pela direção e pelo volume do maciço. Reserve `4197` para composições situacionais confirmadas na referência. |

Ao trocar o material de um maciço, revise as faces no próprio nível e as faixas dos pisos e patamares vizinhos. Identifique o apoio pelo contato efetivo com o corpo ou com a face projetada. Confira também o contorno dos maciços que já tinham piso congelado antes da edição. A comparação entre versões localiza pisos trocados e pode deixar de fora uma faixa inteira de faces de pedra comum. Em áreas com rocha e neve, o acabamento pode alternar entre contorno de pedra e recortes de neve. Nos trechos em que o usuário retirou pedra para ampliar a neve, preserve o recorte e suavize a transição com neve apoiada no piso plano adjacente.

## Casos para consultar

| Referência | Aplicação |
| --- | --- |
| `referencia1.otbm` e mapa 6 manual | Variedade de largura e recortes, neve sobre pedra e encaixes que ocupam dois a quatro SQMs. |
| Mapa 7 manual, `referencia3.otbm` e mapa 9 manual | Transições entre duas bordas, acabamento interno e externo entre andares e escolha de pedra congelada pelo material da face inferior. |
| Mapas 16–18 e mapa 19 manual | O piloto do caminho consolidou a janela móvel de três SQMs. A correção manual no 19 forma um bloco 2×2 em `2631–2632,1593–1594,3`. Veja o contato das quatro peças juntas. [Auditoria do piloto](reports/path18-final-20261103.json) · [Estudo do mapa 19](work/learn-contact-19-20261103/confirmed-learning.json). |
| Esclarecimento sobre neve aérea e mapa 22 | Em `2720,1619,4`, o usuário manteve a pedra bege `219` e retirou as pontas de neve `3859` e `3856`. A `3847` tem um lado oeste reto de 32 pixels e precisa de continuidade desse lado. Outros usos da peça encaixam normalmente. [Auditoria da neve](reports/snow22-final-20261104.json). |
| Mapas 23, 25 e 26 | A dupla `3727/3725` tinha 23 pixels de corte lateral no ponto analisado. A dupla curta `3726/3717` encaixou e a neve `3840` que perderia o apoio saiu junto. No cume, a correção do meio revelou a necessidade de conferir as duas junções laterais. As peças `3718` e `3708` resolveram os pontos circulados no contexto daquele cume. [Estudo do mapa 23](work/stone-support-study-23-20261104/confirmed-learning.json) · [Auditoria do mapa 26](reports/east26-final-20261105.json). |
| Mapas 27 e 28 | Revise faces antigas sobre o novo maciço, margens do gelo e faixas planas em andares vizinhos. As trocas do mapa 28 conservaram a forma das bordas internas. Em `2505,1616,2`, a face `587` passou para `3501` e o monte de neve `3912` que o usuário retirou permaneceu ausente. [Auditoria do mapa 28](reports/east28-final-20261105.json). |

## Fluxo de edição e entrega

1. **Inspecione.** Leia o OTBM no NWO-ASSETS, confirme as coordenadas, os IDs, o perfil de assets e as edições autorais. Para o canônico, use `python -m nwoassets inspect-map-position . <x> <y> <z> -o reports/position-before-<id>.json`. Para um mapa externo, use a inspeção nativa sobre o arquivo alvo com o perfil correspondente.
2. **Versione antes de abrir para edição.** No NWO-ASSETS, rode `python -m nwoassets validate . --deep-spr` e `python -m nwoassets create-version . -o reports/version-<id>.json`. Mantenha os backups testados e imutáveis. Para o East City externo, arquive também o OTBM de origem efetivo e seus assets nativos 10.41 com os hashes.
3. **Planeje e visualize.** Registre os SQMs propostos, a pilha antes/depois e o motivo. Confira o conjunto com os sprites reais, incluindo as camadas que passam por cima, os contatos vizinhos e o andamento do caminho.
4. **Grave pelo fluxo nativo.** Para o East City externo, use `nwoassets.map_edit.rewrite_map` com a origem atual e a nova versão autorizada. Para o mapa canônico, siga o fluxo do editor e de publicação do [AGENTS.md](../AGENTS.md). Preserve atributos, ordem dos itens e registros fora do escopo.
5. **Audite a gravação.** Reabra o arquivo, confira as coordenadas previstas, os metadados, o balanceamento da árvore OTBM e os bytes dos tiles fora da edição. Compare os hashes da origem e dos assets e confira as propriedades físicas. Uma análise estática de acesso verifica conectividade no arquivo. Testes no jogo devem ser registrados separadamente quando realizados.
6. **Valide e entregue.** Rode `inspect-world` e `validate . --deep-spr` com relatórios no NWO-ASSETS. Se houver falha, interrompa a entrega e aplique o procedimento de recuperação do projeto. Sincronize os destinos obrigatórios quando houver alteração dos assets canônicos. Na entrega externa, informe o novo arquivo, a extensão da correção, a comparação visual e qualquer efeito relevante sobre os acessos.

Comandos e formatos adicionais estão no [README do NWO-ASSETS](README.md). A seção de ferramentas do [AGENTS.md](../AGENTS.md) reúne os utilitários locais de inspeção e engenharia reversa, úteis quando os leitores, os assets e o código do editor não bastarem para esclarecer um formato.
