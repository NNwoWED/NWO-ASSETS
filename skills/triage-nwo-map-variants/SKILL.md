---
name: triage-nwo-map-variants
description: Comparar variantes de mapas OTBM locais ou contidas em ZIP, produzindo inventário, matriz de diferenças e recomendação técnica somente leitura. Usar ao triar mapas NWO concorrentes por hash, cabeçalho, versão, dimensões, descrição, estrutura e sidecars XML, sem extrair, alterar, publicar, instalar, sincronizar ou escolher automaticamente a variante canônica.
---

# Triar variantes de mapa NWO

Executar `scripts/compare_otbm.py` para obter uma análise determinística. Tratar cada
entrada como evidência imutável e manter a escolha canônica como decisão explícita de
produto/CEO.

## Fluxo

1. Registrar `git status --short` antes da análise.
2. Identificar cada variante com `--variant RÓTULO=CAMINHO`. Para um membro ZIP,
   usar `RÓTULO=arquivo.zip::membro.otbm`.
3. Gerar JSON reproduzível com `--format json --output <arquivo>` ou matriz Markdown
   com `--format markdown`. O script abre fontes somente para leitura e nunca extrai
   membros do ZIP.
4. Comparar SHA-256, tamanho, cabeçalho OTBM, versão, dimensões, descrição,
   referências de sidecars e contagens estruturais. Tratar `parse_errors` e sidecars
   ausentes como risco, não como autorização para corrigir conteúdo.
5. Formular recomendação técnica baseada em integridade e compatibilidade. Não
   declarar variante canônica.
6. Registrar `git status --short` após a análise e confirmar que nenhum mapa ou
   sidecar foi alterado.
7. Submeter a matriz e a recomendação ao gate explícito do CEO/produto antes de
   instalar, sincronizar, substituir ou publicar qualquer variante.

## Comandos

```bash
python3 scripts/compare_otbm.py \
  --variant atual=world/mapanovo.otbm \
  --variant alternativa="world/mapanovo 8.otbm" \
  --variant zip=world/mapanovo.zip::mapanovo.otbm \
  --format markdown
```

Para verificar o comparador, executar:

```bash
python3 -m unittest discover -s skills/triage-nwo-map-variants/tests -v
```

Não adicionar writers, opções de extração ou ações automáticas de cópia. Não
interpretar a recomendação como aprovação executiva.
