# nwoassets

CLI read-only para inventariar e validar os arquivos do projeto NWO MAPS.

O conjunto local é detectado como `tibia-860-v2-custom-extended`. A
especificação ativa está em
`ESPECIFICACAO-PIPELINE-ASSETS-860-CUSTOM.md`.

## Executar sem instalar

```powershell
python -m nwoassets validate .
python -m nwoassets inspect-client . --deep-spr
python -m nwoassets inspect-world .
python -m nwoassets scan . -o reports/inventory.json
```

## Instalar o comando

```powershell
python -m pip install -e .
nwoassets validate .
```

## Comandos

- `scan`: lista, classifica e calcula SHA-256 de todos os arquivos;
- `inspect-client`: lê OTFI, DAT, SPR e OTB;
- `inspect-world`: lê headers OTBM, mapas em ZIP e XMLs de `world`;
- `inspect-configs`: valida XMLs e resume OTML;
- `validate`: executa todas as inspeções e valida relações entre os formatos.

Use `--deep-spr` para ler e validar o RLE de todos os 245.380 sprites. O modo
normal valida header, tabela e offsets sem percorrer o payload completo.

O inventário ignora apenas diretórios gerados pela própria ferramenta ou pelo
Python: `reports`, `__pycache__`, `.venv`, `.pytest_cache` e `.git`.

## Segurança

Esta versão não possui comandos de escrita. DAT, SPR, OTB e OTBM são sempre
abertos somente para leitura. Importação de PNGs será uma fase posterior, depois
de existirem writers com round-trip byte a byte e suporte comprovado ao
`SpriteHash` desta base.
