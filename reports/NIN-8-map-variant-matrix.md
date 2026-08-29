# NIN-8 — Matriz de variantes OTBM

Gerada pelo comparador read-only em 2026-07-30. A execução abriu arquivos somente
para leitura e leu o membro ZIP em memória, sem extração persistente.

| Variante | SHA-256 | Bytes | OTBM | Dimensões | Items | Descrição | Nós | Prof. | Sidecars | Erros |
|---|---|---|---|---|---|---|---|---|---|---|
| atual | 500e7a0aee816db313906fc891ef9e837bec895f6b9ac7875c04f9f9d86b36e8 | 75673440 | 2 | 3000×3000 | 3.20 | No map description available. | 9663814 | 6 | house_file=ok, spawn_file=ok | nenhum |
| alternativa | 9e8eef5d340431e88d86e11562d7437406ab61d726914420bbab062b797a9448 | 75673433 | 2 | 3000×3000 | 3.20 | No map description available. | 9663813 | 6 | house_file=ok, spawn_file=ok | nenhum |
| zip | ac21eb49c1b493669c92d7c0965f29dd3a05ef0cf683b290b66a4f307c62d162 | 75673502 | 2 | 3000×3000 | 3.20 | No map description available. | 9663813 | 6 | house_file=ausente, spawn_file=ausente | nenhum |

## Recomendação técnica

Priorizar para validação funcional uma variante sem erros de parsing e com os
sidecars referenciados disponíveis. Pelos critérios estáticos, `atual` e
`alternativa` atendem essa condição; diferem em 7 bytes e 1 nó, portanto a
diferença requer validação funcional no servidor/editor antes da escolha.

O mapa no ZIP difere em hash e tamanho e não contém no próprio arquivo ZIP os
sidecars referenciados. Isso reduz sua portabilidade como pacote isolado e é um
risco técnico a registrar, não uma autorização para descartá-lo.

Esta análise não escolhe, instala, sincroniza, substitui ou publica a variante
canônica. A decisão pertence ao CEO/produto em gate explícito separado.

## Verificação

- 3 fixtures passaram: parsing, ZIP/sidecars sem extração e reprodutibilidade.
- `py_compile` passou para comparador e testes.
- Nome e frontmatter foram validados localmente.
- O validador oficial `quick_validate.py` não iniciou porque `PyYAML` não está
  disponível no ambiente (`ModuleNotFoundError: yaml`).
- Nenhum arquivo em `world/` foi escrito pelo comparador.
