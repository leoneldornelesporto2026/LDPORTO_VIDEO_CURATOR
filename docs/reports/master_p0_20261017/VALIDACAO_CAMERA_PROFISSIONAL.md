# Validação real da câmera — 17/10/2026

Foram produzidas somente três amostras técnicas curtas pelo `SeriesProject` e FFmpeg existentes. Não houve CURAR, render do lote, nova transcrição ou aprovação. O preset existente SEM_LEGENDA ocultou texto nas amostras; palavras e tempos originais permaneceram no diagnóstico. As legendas dos resultados anteriores não foram alteradas.

## Artefatos válidos

Pasta: `C:/Users/leone/Videos/LDPORTO_VIDEO_CURATOR/technical_camera_validation/20261017T130058Z_70e74423`.

| Caso | Janela original | Resultado | SHA256 MP4 |
| --- | --- | --- | --- |
| D_ALTERNANCIA_MEDIDA | 1147,62–1153,82 s | 6,2 s; vertical preenchido nos intervalos certificados e amplo no restante | `98ebb54480e1b5408be546bc8a236b46b75233c16f86f5427de726bc6b1bdfa6` |
| E_FONTE_AMPLA | 1393,98–1397,38 s | 3,4 s; palco/grupo preservado no painel horizontal com fundo do próprio vídeo | `3e04a3a911322abeb9b7560d17ac4f9153093c585144cbd5d7c84fa39c572341` |
| F_ZOOM_CERTIFICADO | 1147,25–1150,48409375 s | 3,234 s; recorte preenchido com zoom suave executado | `688ae1ced0eda39979a184460dcdd1a6fb3d5409f75867874908c3fbce904c97` |

Caminhos completos e planos: [REAL_PREVIEWS_VERIFIED.json](REAL_PREVIEWS_VERIFIED.json). O `TECHNICAL_VALIDATION.json` externo conserva os hashes do projeto pai antes/depois. Os ensaios anteriores foram preservados e não são a demonstração válida de zoom.

## Prova de execução

Correspondências SIFT entre frames originais e frames decodificados do MP4, com homografia RANSAC e teste de offsets de ±2 frames:

- Frame de saída em 0,208333 s: 1.172 inliers, zoom estimado 1,0013645.
- Frame de saída em 2,5 s: 1.291 inliers, zoom estimado 1,0207537.
- Crescimento relativo observado: **1,9363%**. Não é contagem de modos nem inferência a partir do nome do arquivo.

Prova detalhada externa: `PIXEL_PROOF_c00de062/PIXEL_MEASUREMENTS.json`, com frames de origem, frames de saída e matrizes. O zoom é calculado em relação à escala vertical base 960/1080; os eixos apresentam escalas compatíveis, sem evidência de estiramento nesses pontos.

A primeira importação experimental `15cbff3ae70a2e5f64a0` ainda usava um handoff compacto no lugar do certificado. A medição encontrou escala constante, confirmando que seu MP4 estava amplo. O alias incorreto foi removido; a nova importação persistida `63114d7dd8af829e4a40` forneceu diretamente os planos usados nos MP4s válidos. Não foi necessário construir um plano alternativo fora do fluxo normal para a prova final.

## Inspeção e limites

Frames efetivamente abertos: D início, D em 2,5 s, D em 5,3 s, E início, F em 2,5 s e fonte F início. Cabeça, rosto, mão no microfone e a outra mão visível foram preservados nesses pontos. D em 5,3 s mostra o retorno amplo e preserva o braço do instrumento.

O recorte preenchido elimina parte da extremidade do instrumento; a própria fonte já corta parte inferior do corpo do instrumento. Não foi comprovada preservação integral do instrumento ou de todos os movimentos em todos os frames. A categoria de ação musical e a importância do braço do instrumento exigem revisão humana. **Essas amostras comprovam execução técnica, sem homologar automaticamente o enquadramento para uma performance instrumental.** Quando essa região for essencial, o plano amplo é a opção segura.

Os três arquivos são H.264, 540×960, 24 fps, SAR 1:1, com AAC da trilha original e sem música inserida/normalização automática. Áudio e vídeo iniciam em PTS 0; diferenças de duração são inferiores a um frame. Isso verifica a estrutura temporal, sem afirmar inspeção humana labial ou fonética. O áudio original é recodificado para AAC, não copiado byte a byte.

Os cortes técnicos de F coincidem com limites certificados de câmera e cruzam duas palavras. O serializer registra essa condição; não há texto desenhado no vídeo técnico. Essa escolha não libera legendas ou os candidatos nativos bloqueados.

## Conclusão de homologação

Importação → índice persistido → plano → envelope de zoom → renderizador → MP4 → medição está comprovado. Aprovação editorial, legendas do pacote real, preservação completa de instrumentos e revisão visual de todos os frames continuam pendentes. Nenhuma aprovação foi criada para simular a conclusão.
