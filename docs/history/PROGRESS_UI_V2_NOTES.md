# L.D.PORTO VIDEO CURATOR — Progress UI V2

Melhoria implementada sobre o pacote `LDPORTO_VIDEO_CURATOR (2).zip`.

## O que mudou

- barra de progresso geral;
- barra de progresso da etapa atual;
- contador `Etapa X/Y`;
- contador explícito de etapas restantes;
- fluxo visual `✓ concluído / ▶ atual / ○ pendente`;
- tempo decorrido;
- ETA adaptativo da etapa;
- ETA adaptativo total;
- progresso real do FFmpeg via `-progress pipe:1`;
- progresso de geração de thumbnails;
- render do lote mostra `corte N/total`;
- botões de ação ficam bloqueados durante processamento para evitar execução concorrente;
- erros preservam a tela de progresso e continuam aparecendo no log.

## TESTAR 1 CORTE

Plano exibido:

1. Localizar análise
2. Carregar dados
3. Curadoria
4. Câmera/planos
5. Localizar vídeo
6. Gerar miniaturas
7. Preparar render
8. Renderizar preview
9. Validar e montar board
10. Concluir teste

Na etapa 8, o percentual vem do FFmpeg real.

## RENDERIZAR TODOS

O plano se expande dinamicamente conforme o número de cortes.
Para 12 cortes, a GUI mostra assets e render individual de cada corte, além das etapas globais.

## Validação

- `py_compile` dos módulos alterados: OK
- pytest: 18 passed
- teste de integração do parser de progresso FFmpeg: OK

A curadoria já existente foi preservada, inclusive `curation_overrides.json` com os vídeos `wA1ipztt54c` e `yZ78vCgiPZk`.
