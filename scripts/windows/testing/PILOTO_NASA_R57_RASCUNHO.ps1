#requires -Version 5.1
<#
  NASA R6 -> R57 technical review-only pilot.
  No download, inference, Git write, R57 import, final render or publication.
  Requires an explicit candidate ID and a technical-only confirmation.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$')]
    [string]$CandidateId,
    [switch]$ConfirmTechnicalPilot,
    [switch]$CreatePreviewZip,
    [string]$AnalyzerRoot
)
$ErrorActionPreference = 'Stop'
if (-not $ConfirmTechnicalPilot) {
    throw 'Informe -ConfirmTechnicalPilot para autorizar somente rascunhos de teste.'
}
$repo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..\..')).Path
$analyzer = if ($AnalyzerRoot) {
    (Resolve-Path -LiteralPath $AnalyzerRoot).Path
} else {
    Join-Path (Split-Path -Parent $repo) 'LDPORTO_VIDEO_ANALYZER'
}
$inbox = Join-Path $repo 'input\analyzer\Eo2bUJcxASI\2131f80ae982b4dc'
$media = Join-Path $analyzer 'input\youtube\Eo2bUJcxASI\Eo2bUJcxASI.mp4'
$py = Join-Path $repo '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $py -PathType Leaf)) { $py = 'python' }
Set-Location -LiteralPath $repo
$branch = (& git branch --show-current).Trim()
if ($LASTEXITCODE -ne 0 -or $branch -ne 'develop') { throw 'Exige branch develop.' }
$dirty = & git status --porcelain
if ($LASTEXITCODE -ne 0 -or $dirty) { throw 'Revise alteracoes locais antes do piloto.' }
if (-not (Test-Path -LiteralPath $inbox -PathType Container)) { throw 'R6 NASA ausente.' }
if (-not (Test-Path -LiteralPath $media -PathType Leaf)) { throw 'Original NASA ausente.' }
foreach ($name in @('ffmpeg','ffprobe')) {
    if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
        throw "Executavel ausente: $name"
    }
}
function Invoke-CuratorJson {
    param([Parameter(Mandatory=$true)][string[]]$CommandArgs)
    $raw = & $py -m ldporto_studio @CommandArgs | Out-String
    if ($LASTEXITCODE -ne 0) { throw "Curator falhou: $($CommandArgs[0])" }
    return ($raw | ConvertFrom-Json -ErrorAction Stop)
}
Write-Host '[1/7] SHA256 e candidato tecnico NASA' -ForegroundColor Cyan
$review = Invoke-CuratorJson -CommandArgs @('r6-review','--inbox',$inbox,'--summary')
$originalSha = ([string]$review.source.source_sha256).ToLowerInvariant()
$actualSha = (Get-FileHash -LiteralPath $media -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualSha -ne $originalSha) { throw 'SHA256 NASA nao corresponde ao Analyzer.' }
$candidate = @($review.first_ten_candidates | Where-Object { $_.id -eq $CandidateId })
if ($candidate.Count -ne 1) { throw "Candidato NASA inexistente: $CandidateId" }
Write-Warning 'Candidato tecnico: nao constitui escolha editorial aprovada.'
Write-Host ("ID: {0}; alertas: {1}" -f $CandidateId,$candidate[0].blocker_count)

Write-Host '[2/7] Roteiro R6 pendente' -ForegroundColor Cyan
$draftResult = Invoke-CuratorJson -CommandArgs @(
    'r6-draft','--inbox',$inbox,'--ids',$CandidateId,
    '--mode','preserve','--confirm-review-draft'
)
$draft = [string]$draftResult.output
if (-not (Test-Path -LiteralPath $draft -PathType Leaf)) { throw 'Roteiro nao encontrado.' }

Write-Host '[3/7] Divisoes tecnicas de Stories' -ForegroundColor Cyan
$storyResult = Invoke-CuratorJson -CommandArgs @(
    'r6-story-propose','--inbox',$inbox,'--draft',$draft,'--save'
)
$story = [string]$storyResult.saved_proposal
if (-not (Test-Path -LiteralPath $story -PathType Leaf)) { throw 'Stories nao encontrados.' }

Write-Host '[4/7] Rascunhos ASR sem inventar falas' -ForegroundColor Cyan
$captionArgs = @('r6-caption-drafts','--inbox',$inbox,'--draft',$draft,'--story-proposal',$story)
$captionReport = Invoke-CuratorJson -CommandArgs $captionArgs
$captions = $null
if ([int]$captionReport.clips_with_draft -gt 0) {
    $captionSaved = Invoke-CuratorJson -CommandArgs ($captionArgs + @('--save'))
    $captions = [string]$captionSaved.saved_drafts_dir
}
if ([int]$captionReport.clips_without_cues -gt 0) {
    Write-Warning ("Cortes sem falas ASR: {0}" -f $captionReport.clips_without_cues)
}

Write-Host '[5/7] Capas PNG da fonte exata' -ForegroundColor Cyan
$coverResult = Invoke-CuratorJson -CommandArgs @(
    'r6-cover-drafts','--inbox',$inbox,'--draft',$draft,
    '--story-proposal',$story,'--media',$media,'--kind','all',
    '--save','--confirm-review-only'
)
$covers = [string]$coverResult.saved_covers_dir
if (-not (Test-Path -LiteralPath $covers -PathType Container)) {
    throw 'PNGs de revisao nao encontrados.'
}

Write-Host '[6/7] Staging com auditoria estrutural' -ForegroundColor Cyan
$prefillArgs = @('r6-assets-prefill','--inbox',$inbox,'--draft',$draft,
                 '--story-proposal',$story,'--covers-dir',$covers,'--save')
if ($captions) { $prefillArgs += @('--captions-dir',$captions) }
$prefill = Invoke-CuratorJson -CommandArgs $prefillArgs
$stage = [string]$prefill.saved_staging_dir
$bindings = [string]$prefill.bindings_path
if (-not (Test-Path -LiteralPath $bindings -PathType Leaf)) {
    throw 'Checklist de assets ausente.'
}
$audit = Invoke-CuratorJson -CommandArgs @(
    'r6-assets','--inbox',$inbox,'--draft',$draft,'--story-proposal',$story,
    '--bindings',$bindings,'--assets-root',$stage
)
if ([int]$audit.audit.assets_verified -ne [int]$prefill.assets_available -or
    $audit.audit.human_approved -ne $false) {
    throw 'Auditoria de assets divergente ou aprovacao indevida.'
}

Write-Host '[7/7] Gate R57 apenas para previas' -ForegroundColor Cyan
$missing = @($prefill.missing_assets)
$zip = $null
if ($missing.Count -gt 0) {
    Write-Warning ("ZIP bloqueado: {0} arquivos ausentes." -f $missing.Count)
    $missing | ForEach-Object { Write-Host ("PENDENTE: " + $_) -ForegroundColor Yellow }
} elseif ($CreatePreviewZip) {
    $result = Invoke-CuratorJson -CommandArgs @(
        'r6-r57-preview-package','--inbox',$inbox,'--draft',$draft,
        '--story-proposal',$story,'--bindings',$bindings,
        '--assets-root',$stage,'--save','--confirm-preview-only'
    )
    if ($result.human_approved -ne $false -or
        $result.publication_ready -ne $false -or
        $result.r57_imported -ne $false) { throw 'ZIP com estado indevido.' }
    $zip = [string]$result.zip_path
    if ((Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant() -ne
        [string]$result.zip_sha256) { throw 'SHA do ZIP divergente.' }
} else {
    Write-Warning 'ZIP nao criado. Opcional: -CreatePreviewZip.'
}
if ((Get-FileHash -LiteralPath $media -Algorithm SHA256).Hash.ToLowerInvariant() -ne
    $originalSha) { throw 'Original NASA mudou durante piloto.' }
Write-Host 'PILOTO TECNICO CONCLUIDO (AINDA NAO APROVADO)' -ForegroundColor Green
Write-Host ("Roteiro: {0}" -f $draft)
Write-Host ("Stories: {0}" -f $story)
Write-Host ("Capas: {0}" -f $covers)
Write-Host ("Legendas: {0}" -f $(if ($captions) { $captions } else { 'AUSENTES' }))
Write-Host ("Staging: {0}" -f $stage)
Write-Host ("Bindings: {0}" -f $bindings)
Write-Host ("Assets: {0}/{1}" -f $prefill.assets_available,$prefill.assets_required)
Write-Host ("ZIP preview: {0}" -f $(if ($zip) { $zip } else { 'NAO GERADO' }))
Write-Host 'Sem importacao, render final ou publicacao.'
