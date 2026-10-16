[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$TargetRoot,
    [string]$PackageRoot,
    [string]$Rollback,
    [switch]$VerifyOnly
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ([string]::IsNullOrWhiteSpace($PackageRoot)) { $PackageRoot = $PSScriptRoot }

function Hash-File([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}
function Check-Ancestors([string]$Path) {
    $node = [IO.Path]::GetFullPath($Path)
    while ($node) {
        if (Test-Path -LiteralPath $node) {
            if ((Get-Item -LiteralPath $node -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw "Links/junctions nao permitidos: $node"
            }
        }
        $parent = Split-Path -Parent $node
        if ($parent -eq $node) { break }
        $node = $parent
    }
}
function Safe-Path([string]$Root, [string]$Relative) {
    if ([string]::IsNullOrWhiteSpace($Relative) -or $Relative -match '[\\:\x00-\x1f<>"|?*]' -or
        $Relative -match '(^/|/$|//|(^|/)\.{1,2}(/|$)|(^|/)[^/]*[ .](/|$))' -or
        $Relative -match '(?i)(^|/)(con|prn|aux|nul|com[1-9]|lpt[1-9])(\.[^/]*|)(/|$)') {
        throw "Caminho relativo inseguro: $Relative"
    }
    $base = [IO.Path]::GetFullPath($Root).TrimEnd('\','/')
    $full = [IO.Path]::GetFullPath((Join-Path $base $Relative))
    if (-not $full.StartsWith($base + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Caminho fora do destino: $Relative"
    }
    Check-Ancestors $full
    return $full
}
function Allowed-Path([string]$Relative) {
    if ($Relative -match '(?i)(^|/)(output|\.cache|\.venv|\.git|source|source_cache|backups|backup_before|history|historico|revisions|approvals|original_media|__pycache__)(/|$)' -or
        ($Relative -cnotmatch '^(README\.md|pytest\.ini|(?:ldporto_curator|scripts)/.+\.(?:py|ps1)|tests/.+\.(?:py|json|jsonl)|docs/(?:architecture|development|reports)/.+\.md)$')) {
        throw "Arquivo fora da allowlist de codigo/testes/docs: $Relative"
    }
}
function Check-Hash($Value, [switch]$Nullable) {
    if ($Nullable -and $null -eq $Value) { return }
    if ($Value -isnot [string] -or $Value -cnotmatch '^[a-f0-9]{64}$') { throw 'SHA256 invalido no manifesto/journal.' }
}
function Current-Hash([string]$Path) {
    if (Test-Path -LiteralPath $Path) {
        if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "Destino nao e arquivo: $Path" }
        return Hash-File $Path
    }
    return $null
}
function Save-State([string]$Path, $State) {
    Check-Ancestors $Path
    $temporary = $Path + '.new'
    Check-Ancestors $temporary
    $bytes = [Text.UTF8Encoding]::new($false).GetBytes(($State | ConvertTo-Json -Depth 20))
    $stream = [IO.File]::Open($temporary, [IO.FileMode]::Create, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try { $stream.Write($bytes, 0, $bytes.Length); $stream.Flush($true) } finally { $stream.Dispose() }
    if (Test-Path -LiteralPath $Path) { [IO.File]::Replace($temporary, $Path, [NullString]::Value) }
    else { [IO.File]::Move($temporary, $Path) }
}
function Replace-Verified([string]$Source, [string]$Destination, [string]$Stage, [string]$Expected) {
    Check-Ancestors $Source
    Check-Ancestors $Destination
    Check-Ancestors $Stage
    New-Item -ItemType Directory -Path (Split-Path -Parent $Stage) -Force | Out-Null
    Copy-Item -LiteralPath $Source -Destination $Stage -Force
    if ((Hash-File $Stage) -ne $Expected -or (Hash-File $Source) -ne $Expected) { throw 'Hash da copia temporaria diverge.' }
    New-Item -ItemType Directory -Path (Split-Path -Parent $Destination) -Force | Out-Null
    Check-Ancestors $Destination
    if (Test-Path -LiteralPath $Destination) { [IO.File]::Replace($Stage, $Destination, [NullString]::Value) }
    else { [IO.File]::Move($Stage, $Destination) }
    if ((Hash-File $Destination) -ne $Expected) { throw 'Hash apos substituicao diverge.' }
}
function Restore-Transaction([string]$TransactionPath, $Transaction, [bool]$ReadOnly) {
    $transactionRelative = $TransactionPath.Substring($target.Length + 1).Replace('\','/')
    if ($transactionRelative -cnotmatch '^backups/camera_final_[a-f0-9]{32}/TRANSACTION\.json$' -or
        $Transaction.schema -ne 'LDP_CAMERA_PATCH_TRANSACTION_V1' -or $Transaction.target_root -ne $target -or
        $Transaction.status -notin @('PREPARING','INSTALLING','INSTALLED','ROLLING_BACK','RECOVERY_REQUIRED','ROLLED_BACK','FAILED_ROLLED_BACK')) {
        throw 'Journal invalido ou pertencente a outro destino.'
    }
    $backupRelative = $transactionRelative.Substring(0, $transactionRelative.LastIndexOf('/'))
    $seen = @{}
    # Validate every file and existing backup before restoring anything. A row may
    # still say APPLYING after atomic replacement if the process was interrupted.
    foreach ($row in $Transaction.files) {
        Allowed-Path $row.path
        Check-Hash $row.installed_sha256
        Check-Hash $row.before_sha256 -Nullable
        if ($seen.ContainsKey($row.path)) { throw 'Caminho duplicado no journal.' }
        $seen[$row.path] = $true
        if ($row.state -notin @('PENDING','APPLYING','APPLIED','RESTORING','RESTORED') -or
            $row.backup -cne ($backupRelative + '/original/' + $row.path)) { throw 'Linha invalida no journal.' }
        $current = Current-Hash (Safe-Path $target $row.path)
        if ($current -ne $row.before_sha256 -and $current -ne $row.installed_sha256) {
            throw "Arquivo local diverge; rollback preservou tudo: $($row.path)"
        }
        $backup = Safe-Path $target $row.backup
        $backupHash = Current-Hash $backup
        if ($null -ne $row.before_sha256 -and (($Transaction.status -ne 'PREPARING' -and $null -ne $backupHash -and $backupHash -ne $row.before_sha256) -or
            ($current -eq $row.installed_sha256 -and $backupHash -ne $row.before_sha256))) {
            throw "Backup invalido/ausente: $($row.path)"
        }
    }
    if ($ReadOnly) { Write-Output 'Rollback verificado; nenhum arquivo alterado.'; return }
    $Transaction.status = 'ROLLING_BACK'
    Save-State $TransactionPath $Transaction
    foreach ($row in $Transaction.files) {
        $destination = Safe-Path $target $row.path
        $current = Current-Hash $destination
        if ($current -ne $row.before_sha256) {
            if ($current -ne $row.installed_sha256) { throw "Arquivo alterado durante rollback: $($row.path)" }
            $row.state = 'RESTORING'
            Save-State $TransactionPath $Transaction
            if ($null -eq $row.before_sha256) {
                Remove-Item -LiteralPath $destination -Force
            } else {
                Replace-Verified (Safe-Path $target $row.backup) $destination (Safe-Path $target ($backupRelative + '/restore/' + $row.path)) $row.before_sha256
            }
        }
        if ((Current-Hash $destination) -ne $row.before_sha256) { throw "Hash restaurado diverge: $($row.path)" }
        $row.state = 'RESTORED'
        Save-State $TransactionPath $Transaction
    }
    $Transaction.status = 'ROLLED_BACK'
    Save-State $TransactionPath $Transaction
    Write-Output 'Rollback concluido. Backups e journal preservados.'
}

$target = [IO.Path]::GetFullPath($TargetRoot).TrimEnd('\','/')
Check-Ancestors $target
if (-not (Test-Path -LiteralPath (Safe-Path $target 'ldporto_curator') -PathType Container)) {
    throw 'TargetRoot deve apontar para uma instalacao existente do VIDEO CURATOR.'
}
if ($Rollback) {
    $transactionPath = Safe-Path $target $Rollback
    $transaction = Get-Content -LiteralPath $transactionPath -Raw -Encoding UTF8 | ConvertFrom-Json
    Restore-Transaction $transactionPath $transaction ([bool]$VerifyOnly)
    return
}
$package = [IO.Path]::GetFullPath($PackageRoot).TrimEnd('\','/')
Check-Ancestors $package
$manifestPath = Safe-Path $package 'UPDATE_MANIFEST.json'
$manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($manifest.schema -ne 'LDP_CAMERA_PATCH_V1') { throw 'Manifesto desconhecido.' }
$seen = @{}
$pending = @()
foreach ($row in $manifest.files) {
    Allowed-Path $row.path
    Check-Hash $row.sha256
    Check-Hash $row.before_sha256 -Nullable
    if ($seen.ContainsKey($row.path)) { throw "Caminho duplicado no manifesto: $($row.path)" }
    $seen[$row.path] = $true
    $payload = Safe-Path (Safe-Path $package 'payload') $row.path
    if (-not (Test-Path -LiteralPath $payload -PathType Leaf) -or (Hash-File $payload) -ne $row.sha256) {
        throw "SHA256 do pacote invalido: $($row.path)"
    }
    $current = Current-Hash (Safe-Path $target $row.path)
    if ($current -eq $row.sha256) { continue }
    if ($current -ne $row.before_sha256) { throw "Versao local diverge do baseline: $($row.path)" }
    $pending += [pscustomobject]@{path=$row.path; installed_sha256=$row.sha256; before_sha256=$current; backup=''; state='PENDING'}
}
# A fresh install cannot conceal a previous interrupted transaction.
$backupRoot = Safe-Path $target 'backups'
if (Test-Path -LiteralPath $backupRoot) {
    foreach ($directory in (Get-ChildItem -LiteralPath $backupRoot -Directory -Force | Where-Object Name -Like 'camera_final_*')) {
        Check-Ancestors $directory.FullName
        $journal = Join-Path $directory.FullName 'TRANSACTION.json'
        Check-Ancestors $journal
        if (Test-Path -LiteralPath $journal -PathType Leaf) {
            $previous = Get-Content -LiteralPath $journal -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($previous.status -notin @('INSTALLED','ROLLED_BACK','FAILED_ROLLED_BACK')) {
                throw "Instalacao interrompida; execute -Rollback com: $journal"
            }
        }
    }
}
if ($VerifyOnly) { Write-Output "Pacote/baseline verificados; $($pending.Count) atualizacoes; nenhum arquivo alterado."; return }
if ($pending.Count -eq 0) { Write-Output 'Atualizacao ja aplicada; hashes conferidos.'; return }
$backupRelative = 'backups/camera_final_' + [Guid]::NewGuid().ToString('N')
$backupDirectory = Safe-Path $target $backupRelative
New-Item -ItemType Directory -Path $backupDirectory | Out-Null
$transactionPath = Join-Path $backupDirectory 'TRANSACTION.json'
foreach ($row in $pending) { $row.backup = $backupRelative + '/original/' + $row.path }
$transaction = [pscustomobject]@{schema='LDP_CAMERA_PATCH_TRANSACTION_V1'; target_root=$target; status='PREPARING'; files=$pending}
Save-State $transactionPath $transaction
try {
    foreach ($row in $pending) {
        if ($null -ne $row.before_sha256) {
            $backup = Safe-Path $target $row.backup
            New-Item -ItemType Directory -Path (Split-Path -Parent $backup) -Force | Out-Null
            Copy-Item -LiteralPath (Safe-Path $target $row.path) -Destination $backup
            if ((Hash-File $backup) -ne $row.before_sha256) { throw "Backup diverge: $($row.path)" }
        }
    }
    $transaction.status = 'INSTALLING'
    Save-State $transactionPath $transaction
    foreach ($row in $pending) {
        $destination = Safe-Path $target $row.path
        if ((Current-Hash $destination) -ne $row.before_sha256) { throw "Arquivo mudou durante instalacao: $($row.path)" }
        $row.state = 'APPLYING'
        Save-State $transactionPath $transaction
        Replace-Verified (Safe-Path (Safe-Path $package 'payload') $row.path) $destination (Safe-Path $target ($backupRelative + '/stage/' + $row.path)) $row.installed_sha256
        $row.state = 'APPLIED'
        Save-State $transactionPath $transaction
    }
    $transaction.status = 'INSTALLED'
    Save-State $transactionPath $transaction
} catch {
    $failure = $_
    try {
        Restore-Transaction $transactionPath $transaction $false
        $transaction.status = 'FAILED_ROLLED_BACK'
        Save-State $transactionPath $transaction
    } catch {
        $transaction.status = 'RECOVERY_REQUIRED'
        Save-State $transactionPath $transaction
        Write-Warning "Recuperacao exige revisao: $($_.Exception.Message). Journal: $transactionPath"
    }
    throw $failure
}
Write-Output "Camera instalada com hashes verificados. Rollback: -TargetRoot `"$target`" -Rollback `"$backupRelative/TRANSACTION.json`""
