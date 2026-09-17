# Auditoria por uso: 100 destinos para remakes

Data: 2026-09-16. Escopo: Server IDs a partir de 10051 até obter 100 destinos. Resultado: 10051–10156, excluindo 10087, 10091, 10127, 10130, 10150 e 10152. O CSV adjacente contém os 100 vínculos SID/CID na ordem crescente de SID.

Critério: o item não aparece em `assets/world/mapanovo.otbm` e não possui uso específico como item nos sistemas ativos examinados. Estar definido em `assets/items/items.xml` **não exclui** o item. Entre os 100 destinos, 45 possuem definição XML e 55 não possuem. A aparência e as propriedades OTB/DAT podem estar ocupadas em ambos os casos: estes são destinos para substituição, não vagas vazias.

Fontes examinadas: mapa canônico completo (7.824.286 tiles e 2.105.106 nós de item, além de itens inline); OTB/XML canônicos, idênticos por SHA-256 aos arquivos correspondentes do servidor; código e configurações em `Server-Data-Nwo/data`, `Server-Data-Nwo/mods`, `Server-Data-Nwo/src`, `Src-Nwo`, client PC e mobile. Referências numéricas em contextos não relacionados a itens (por exemplo, tempos de raid e códigos de erro de login) não foram consideradas uso do item.

Exclusões confirmadas: 10087 ocorre 7 vezes no mapa; 10127 e 10130 ocorrem 1 vez cada; 10091 integra a lista de chaves em `data/lib/000-constant.lua`; 10150 possui ação registrada em `data/actions/actions.xml`; 10152 é destino de `decayTo` do item 10119 em `items.xml`. Os 100 pares SID/CID do CSV são únicos e nenhum desses CIDs está associado a outro SID no OTB. Há 99 nós do grupo OTB 0 e 1 do grupo 1; flags e aparências variam.

Limites: a busca estática não prova ausência em inventários/casas persistidos, banco de dados, scripts que calculam IDs dinamicamente ou fontes externas ao escopo. Nenhuma consulta a banco foi feita. A lista não atribui arquivos OBD aos destinos e não é um manifesto `import-items`. Antes de cada importação, revalidar o uso e configurar nome, finalidade e propriedades desejadas, sem herdar flags antigas automaticamente. O importador substitui aparências pelo Client ID existente; os OBD precisam ser convertidos ao PNG suportado, e padrões múltiplos ainda exigem ampliação e teste da ferramenta.
