# Revisão incremental de câmera vertical

O ponto de entrada sem nova análise é `final_camera.refine_from_existing_metadata`.
Ele recebe o corte original, metadados de resolução e observações visuais existentes,
retorna um novo plano e não executa detecção, Qwen, transcrição ou diarização.
Uma pessoa visualmente persistente pode orientar a composição sem ser identificada
como quem fala. Falta de geometria, nitidez, cobertura ou espaço mantém a fonte ampla.

`SeriesProject.derive_camera_revision` cria uma pasta inédita para episódios
explicitamente selecionados. Reutiliza a validação de snapshots e assets da revisão
de legendas. Copia ASS, SRT e a timeline canônica histórica por SHA256; títulos e
capas também são copiados por hash. Congela o novo plano de câmera e exige outra
prévia e aprovação humana. A origem e suas aprovações não são salvas ou alteradas.

```powershell
.\.venv\Scripts\python.exe scripts/REFINAR_CAMERA_EXISTENTE.py --project "<projeto Stories>" --episode "<id>" --micro "<clip_micro_perception.json existente>" --destination "<pasta nova>"
```

O comando acima consulta o plano. `--apply` cria a revisão separada;
`--render-preview --source "<original.mp4>"` também renderiza somente esse episódio,
após verificar o SHA256 da fonte. Para Reels, `scripts/REVISAR_CAMERA_SEM_QWEN.py`
reutiliza por padrão a percepção já persistida no projeto. Não usar `--all` para
aplicar um acabamento ainda em avaliação. Nenhum comando concede aprovação.

O zoom adicional é opcional, configurado em
`camera_v44.director_style.smart_zoom`, incluindo `enabled`, `micro_zoom_factor`,
`micro_zoom_duration` e `micro_zoom_min_hold_seconds`. O fator inicial é 1,035.
Uma curva smoothstep entra após a permanência inicial somente quando geometria,
resolução e nitidez permitem. Legendas e títulos são compostos depois da câmera.
Os parâmetros do envelope fazem parte da assinatura de aprovação dos Reels.

A passagem de fonte ampla para crop dentro da mesma cena pode usar uma mescla
suave dos mesmos frames. `camera_v44.director_style.focus_transition_seconds`
começa em 0,35 s, aceita até 0,45 s e pode ser desligado com zero. A mescla não
sobrepõe intervalos, não encurta a timeline e não atravessa cortes da fonte.
Gráficos locais sem revisão visual mantêm a fonte ampla, evitando criar uma faixa
com prateleira, camisa ou outro falso positivo do detector.

Mapas só recebem crop com regiões visuais explícitas revisadas, coordenadas
normalizadas e amostras de frames com SHA256 cobrindo o intervalo. A união da rota
e dos rótulos precisa caber com margens no 9:16. Sem esses dados, a fonte inteira
permanece com o preenchimento desfocado. Narração não fornece coordenadas de avião.

Cada tentativa de render usa um recibo exclusivo e nomes temporários UUID. Um MP4
anterior ou uma tentativa incompleta impede sobrescrita dos assets. Publicação usa
hard link exclusivo no mesmo volume e só ocorre depois da validação. Falhas deixam
evidências no diretório da tentativa; a recuperação usa outra revisão/pasta. Essa
operação exige filesystem com suporte a hard links, como NTFS; em outro filesystem
falha preservando o arquivo temporário, sem substituir a mídia anterior.

A limpeza só considera arquivos temporários registrados explicitamente por caminho,
tamanho e SHA256, fora das árvores protegidas. Arquivos antigos não são registrados
automaticamente. `output`, caches, originais, projetos, revisões, aprovações, manifests,
backups e evidências do Analyzer permanecem protegidos. O botão de limpeza não
oferece mais remoção da fonte original.
