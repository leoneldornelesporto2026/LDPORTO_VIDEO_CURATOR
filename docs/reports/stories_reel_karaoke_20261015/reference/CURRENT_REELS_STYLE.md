# Referência visual dos oito Reels existentes

Foram lidos os oito arquivos ASS finais existentes. Nenhum vídeo, legenda ou revisão foi alterado.

Todos usam Segoe UI em negrito, 60 px em 1080×1920. As palavras futuras aparecem em amarelo `#FFD700`; as pronunciadas ficam brancas `#FFFFFF` até o bloco terminar. O contorno é `#101010`, com 6 px, sombra de 2 px, alinhamento inferior central, margens laterais de 130 px e margem inferior de 320 px. Na prévia 540×960 essas medidas se reduzem pela metade.

O comportamento de bloco e cores é a referência. A implementação legada usa tags ASS `\k` com durações somadas. O motor compartilhado usa os inícios absolutos medidos pelo Analyzer para evitar acúmulo de erro nas pausas e no arredondamento.

O novo limite é de até seis palavras por bloco, conforme o pedido atual. Os Reels históricos também possuem blocos com sete palavras e blocos menores em finais de frase.

Os caminhos, SHA256, estilos literais e estatísticas individuais constam em [CURRENT_REELS_STYLE.json](CURRENT_REELS_STYLE.json).
