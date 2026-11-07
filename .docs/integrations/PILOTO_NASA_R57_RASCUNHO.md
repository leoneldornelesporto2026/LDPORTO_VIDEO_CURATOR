# Piloto NASA R6 → R57, apenas rascunhos técnicos

O controlador usa o ZIP R6 validado, o MP4 NASA de SHA256 exato e um ID de candidato explicitamente informado. Não executa downloads, inferência, importação R57, render final, aprovação ou publicação.

## PowerShell 5.1, branch develop e Git limpo

Sem ZIP de prévias:
    .\scripts\windows\testing\PILOTO_NASA_R57_RASCUNHO.ps1 -CandidateId MOMENT_00000_0002 -ConfirmTechnicalPilot

Com ZIP R57 apenas de prévias, quando todos os arquivos já existirem:
    .\scripts\windows\testing\PILOTO_NASA_R57_RASCUNHO.ps1 -CandidateId MOMENT_00000_0002 -ConfirmTechnicalPilot -CreatePreviewZip

São criados roteiro R6, proposta de Stories por duração, SRT/ASS para revisão somente onde houver ASR original, capas PNG com quadros reais da fonte, staging com checklist SHA256 e, opcionalmente, ZIP R57 não aprovado. Tudo em output/ e sem alterar os arquivos de entrada.

Se faltarem legendas ou outra evidência, o script lista PENDENTE e bloqueia o ZIP. Mesmo com o pacote estruturalmente válido, a curadoria de conteúdo, direitos, áudio, legendas, camera e prévia continua obrigatória.

A suíte tests/test_r6_nasa_pilot_script.py só verifica guardrails estáticos; é necessária uma execução real no Windows para homologar o piloto.