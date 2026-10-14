param([Parameter(Mandatory=$true)][string]$SpecFile, [Parameter(Mandatory=$true)][string]$OutputDirectory)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$taskDemoSpec = Get-Content -LiteralPath $SpecFile -Encoding UTF8 -Raw | ConvertFrom-Json
$taskVoice = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $taskPortugueseVoice = $taskVoice.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Culture.Name -eq 'pt-BR' } | Select-Object -First 1
    if ($taskPortugueseVoice) { $taskVoice.SelectVoice($taskPortugueseVoice.VoiceInfo.Name) }
    $taskVoice.Rate = 0
    foreach ($taskPhrase in $taskDemoSpec.phrases) {
        $taskWavePath = Join-Path $OutputDirectory ($taskPhrase.id + '.wav')
        if (-not (Test-Path -LiteralPath $taskWavePath)) {
            $taskVoice.SetOutputToWaveFile($taskWavePath)
            $taskVoice.Speak([string]$taskPhrase.text)
            $taskVoice.SetOutputToNull()
        }
    }
    Write-Output $taskVoice.Voice.Name
} finally { $taskVoice.Dispose() }
