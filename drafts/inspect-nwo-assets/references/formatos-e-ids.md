# Formatos, perfis e espaços de IDs

## Fonte ativa

A autoridade local para o checkout é `ESPECIFICACAO-PIPELINE-ASSETS-860-CUSTOM.md`. O perfil aceito pela CLI é `tibia-860-v2-custom-extended`:

| Campo | Baseline ativa |
| --- | --- |
| Versão nominal | Tibia 8.60 v2 customizado |
| DAT signature | `0x4C2C7993` |
| SPR signature | `0x4C220594` |
| Metadata | `MetadataReader5`, com extensão local restrita |
| OTB | `OTB 3.20.20-8.60` |
| OTFI | extended, transparency, frame-durations e frame-groups ativos |
| Sprite físico | 32×32; grupo máximo configurado em 4096 |

O diretório `860` e a versão nominal não bastam. O OTFI define contagem/IDs SPR em `uint32`, alpha no RLE, durações e frame groups. Misturar assinaturas ou features deve falhar.

## IDs independentes

### Client ID

Identifica um objeto lógico/aparência no `Tibia.dat`. Os itens começam em 100. O header guarda máximos por categoria; os registros são sequenciais.

### Sprite ID

Identifica uma imagem física no `Tibia.spr`. É 1-based e independente do Client ID. O valor `0` referenciado pelo DAT significa imagem vazia.

Um Client ID pode referenciar vários Sprite IDs por dimensões, layers, patterns, animação e frame groups.

### Server ID

Identifica um nó de item no `items.otb`. O nó pode ter um Client ID, mas os espaços não são equivalentes. Na baseline ativa:

- Server IDs observados: `100..25243`;
- Client IDs OTB observados: até `24358`;
- vários Server IDs podem mapear para o mesmo Client ID;
- itens deprecated podem não possuir Client ID.

Nunca aplicar globalmente `Server ID == Client ID`.

## Particularidades comprovadas

- DAT: 30.123 registros; parse válido termina exatamente no EOF.
- SPR: 245.380 sprites; o modo normal valida header/tabela/offsets, e `--deep-spr` valida os blocos RLE.
- OTBM: há três variantes binariamente distintas. Todas declaram versão 2, dimensões 3000×3000 e items 3.20, mas isso não prova equivalência.
- XML: `items/new.xml` é fragmento com múltiplas raízes e só recebe wrapper em memória.
- OTML: a CLI inventaria estrutura textual e encoding; não realiza validação semântica completa.

### Flag DAT local `0x22`

A flag aparece sem payload apenas nos Client IDs de item 100, 4812, 4814 e 20227 deste DAT. O parse sincronizado até EOF é evidência local, não uma definição geral do formato. Não reutilizar a regra para outro arquivo, perfil ou versão.

## Limites da referência 10.41

`ESPECIFICACAO-PORTATIL-PIPELINE-SPRITES-1041.md` é referência histórica, não baseline ativa. Suas assinaturas (`0x5383504E`/`0x53835077`), `MetadataReader6`, OTB 3.55.1, limites operacionais, writers e mapeamento identidade de novos itens não podem ser transferidos ao perfil 8.60.

A CLI pode reconhecer assinaturas 10.41 para produzir erro informativo, mas o parse semântico implementado exige MetadataReader5. Não usar o documento 10.41 para editar ou “corrigir” arquivos atuais.
