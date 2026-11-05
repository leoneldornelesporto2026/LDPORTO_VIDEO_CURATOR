# Release Studio 1.0.0 — 05/11/2026

## Incluído

- Novo programa Python desktop, **sem dependência do GitHub ou do motor antigo**.
- Curadoria R57 embutida: 12 Reels + 60 Stories, 72 capas e contratos editoriais originais.
- GUI e CLI Windows, integridade SHA256 de cada membro da curadoria e da mídia original.
- Crop vertical manual ou canvas 9:16 preservando o show horizontal; tarja branca de título.
- Prévia 540×960 e final 1080×1920 H.264/AAC com validação FFprobe.
- Legendas ASS desligadas por padrão até validação humana do áudio; importação de ASS corrigida, vinculada a hash, preserva rascunhos originais.
- Aprovação de prévia vinculada a hash + plano + mídia + versão do renderer, sem exportação final por engano.
- Exportação de capas e rascunhos editoriais sem modificá-los, histórico de render e relatório.

## Evidência de testes

- 14 testes automatizados aprovados em ambiente Linux, incluindo mídia sintética com áudio, preview e final, FFprobe, crop, ASS, bloqueio de fonte e aprovação.
- Aplicação GUI aberta em ambiente virtual gráfico (Xvfb): 72 linhas e capa exibidas.
- Contrato R57 original validado; 72 capas exportadas com hash preservado.

## Pendente na máquina do usuário

- Verificação do executável BAT e da interface no Windows 10/11.
- MP4 original do show com hash correspondente — **não incluído** no pacote.
- Revisão humana do contexto, enquadramento, ASR, áudio e direitos.
- Build opcional `.exe` no Windows, via `GERAR_EXE_WINDOWS.bat` com PyInstaller; não há `.exe` homologado neste ZIP.

**Não há upload ou publicação automática.**
