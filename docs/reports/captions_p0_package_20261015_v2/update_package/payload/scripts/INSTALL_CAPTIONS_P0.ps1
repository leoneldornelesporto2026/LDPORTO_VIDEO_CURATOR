[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$TargetRoot,
    [string]$PackageRoot,
    [string]$Rollback,
    [switch]$VerifyOnly
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ([string]::IsNullOrWhiteSpace($PackageRoot)) {
    $PackageRoot = [IO.Path]::GetDirectoryName($MyInvocation.MyCommand.Path)
}

function Hash-File([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}
function Safe-Path([string]$Root, [string]$Relative) {
    if ([string]::IsNullOrWhiteSpace($Relative) -or $Relative -match '[\\:]' -or $Relative -match '(^/|/$|//|(^|/)\.{1,2}(/|$)|(^|/)[^/]*[ .](/|$))') {
        throw "Caminho relativo inseguro: $Relative"
    }
    $base = [IO.Path]::GetFullPath($Root).TrimEnd('\','/')
    $full = [IO.Path]::GetFullPath((Join-Path $base $Relative))
    if (-not $full.StartsWith($base + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Caminho fora do destino: $Relative"
    }
    $node = $full
    while ($node -and $node.Length -ge $base.Length) {
        if (Test-Path -LiteralPath $node) {
            if ((Get-Item -LiteralPath $node -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw "Links/junctions nao permitidos: $node"
            }
        }
        if ($node -eq $base) { break }
        $node = Split-Path -Parent $node
    }
    return $full
}
function Allowed-Path([string]$Relative) {
    if ($Relative -notin @('README.md', 'pytest.ini') -and $Relative -notmatch '^(ldporto_curator|scripts|tests)/' -and $Relative -notmatch '^docs/(reports|development|architecture)/') {
        throw "Arquivo fora do escopo de atualizacao: $Relative"
    }
}
function Save-State([string]$Path, $State) {
    $State | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $Path -Encoding UTF8
}

$target = [IO.Path]::GetFullPath($TargetRoot).TrimEnd('\','/')
if (-not (Test-Path -LiteralPath (Join-Path $target 'ldporto_curator') -PathType Container)) {
    throw 'TargetRoot deve apontar para uma instalacao existente do VIDEO CURATOR.'
}
if ($Rollback) {
    $transactionPath = Safe-Path $target $Rollback
    $transaction = Get-Content -LiteralPath $transactionPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($transaction.schema -ne 'LDP_CAPTION_PATCH_TRANSACTION_V1' -or $transaction.status -ne 'INSTALLED' -or $transaction.target_root -ne $target) {
        throw 'Transacao de rollback invalida, ja revertida ou de outro destino.'
    }
    # Validate EVERY current and backup hash before making any rollback changes.
    foreach ($row in $transaction.files) {
        Allowed-Path $row.path
        $destination = Safe-Path $target $row.path
        if (-not (Test-Path -LiteralPath $destination -PathType Leaf) -or (Hash-File $destination) -ne $row.installed_sha256) {
            throw "Arquivo mudou depois da instalacao; rollback preservou tudo: $($row.path)"
        }
        if ($null -ne $row.before_sha256) {
            $backup = Safe-Path $target $row.backup
            if (-not (Test-Path -LiteralPath $backup -PathType Leaf) -or (Hash-File $backup) -ne $row.before_sha256) {
                throw "Backup invalido: $($row.path)"
            }
        }
    }
    if ($VerifyOnly) { Write-Output 'Rollback verificado; nenhum arquivo alterado.'; return }
    foreach ($row in $transaction.files) {
        $destination = Safe-Path $target $row.path
        if ($null -ne $row.before_sha256) {
            Copy-Item -LiteralPath (Safe-Path $target $row.backup) -Destination $destination -Force
            if ((Hash-File $destination) -ne $row.before_sha256) { throw "Hash restaurado diverge: $($row.path)" }
        } else {
            Remove-Item -LiteralPath $destination -Force
            if (Test-Path -LiteralPath $destination) { throw "Arquivo novo nao removido: $($row.path)" }
        }
    }
    $transaction.status = 'ROLLED_BACK'
    Save-State $transactionPath $transaction
    Write-Output 'Rollback concluido. Backups e projetos preservados.'
    return
}

$manifestPath = Join-Path $PackageRoot 'UPDATE_MANIFEST.json'
$manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($manifest.schema -ne 'LDP_CAPTION_PATCH_V1') { throw 'Manifesto desconhecido.' }
$seen = @{}
$pending = @()
foreach ($row in $manifest.files) {
    Allowed-Path $row.path
    if ($seen.ContainsKey($row.path)) { throw "Caminho duplicado no manifesto: $($row.path)" }
    $seen[$row.path] = $true
    $payload = Safe-Path (Join-Path $PackageRoot 'payload') $row.path
    if (-not (Test-Path -LiteralPath $payload -PathType Leaf) -or (Hash-File $payload) -ne $row.sha256) {
        throw "SHA256 do pacote invalido: $($row.path)"
    }
    $destination = Safe-Path $target $row.path
    $current = $null
    if (Test-Path -LiteralPath $destination) {
        if (-not (Test-Path -LiteralPath $destination -PathType Leaf)) { throw "Destino nao e arquivo: $($row.path)" }
        $current = Hash-File $destination
    }
    if ($current -eq $row.sha256) { continue }
    if ($current -ne $row.before_sha256) {
        throw "Versao local diverge do baseline; nenhuma alteracao feita: $($row.path)"
    }
    $pending += [pscustomobject]@{ path=$row.path; installed_sha256=$row.sha256; before_sha256=$current; backup=$null }
}
if ($VerifyOnly) { Write-Output "Pacote e baseline verificados: $($manifest.files.Count) arquivos; $($pending.Count) atualizacoes. Nenhum arquivo alterado."; return }
if ($pending.Count -eq 0) { Write-Output 'Atualizacao ja aplicada; hashes conferidos.'; return }
$backupRelative = 'backups/captions_p0_' + [Guid]::NewGuid().ToString('N')
$backupDirectory = Safe-Path $target $backupRelative
New-Item -ItemType Directory -Path $backupDirectory | Out-Null
$transactionPath = Join-Path $backupDirectory 'TRANSACTION.json'
$transaction = [pscustomobject]@{ schema='LDP_CAPTION_PATCH_TRANSACTION_V1'; target_root=$target; status='PREPARED'; files=$pending }
foreach ($row in $pending) {
    if ($null -ne $row.before_sha256) {
        $row.backup = $backupRelative + '/original/' + $row.path
        $backup = Safe-Path $target $row.backup
        New-Item -ItemType Directory -Path (Split-Path -Parent $backup) -Force | Out-Null
        Copy-Item -LiteralPath (Safe-Path $target $row.path) -Destination $backup
        if ((Hash-File $backup) -ne $row.before_sha256) { throw "Backup falhou: $($row.path)" }
    }
}
Save-State $transactionPath $transaction
$applied = @()
try {
    foreach ($row in $pending) {
        $destination = Safe-Path $target $row.path
        New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
        $applied += $row
        Copy-Item -LiteralPath (Safe-Path (Join-Path $PackageRoot 'payload') $row.path) -Destination $destination -Force
        if ((Hash-File $destination) -ne $row.installed_sha256) { throw "Verificacao apos copia falhou: $($row.path)" }
    }
    $transaction.status = 'INSTALLED'
    Save-State $transactionPath $transaction
} catch {
    foreach ($row in $applied) {
        $destination = Safe-Path $target $row.path
        if ($null -ne $row.before_sha256) {
            Copy-Item -LiteralPath (Safe-Path $target $row.backup) -Destination $destination -Force
            if ((Hash-File $destination) -ne $row.before_sha256) { throw "Falha na restauracao automatica: $($row.path)" }
        } elseif (Test-Path -LiteralPath $destination -PathType Leaf) {
            Remove-Item -LiteralPath $destination -Force
        }
    }
    $transaction.status = 'FAILED_ROLLED_BACK'
    Save-State $transactionPath $transaction
    throw
}
Write-Output "Atualizacao instalada com hashes verificados. Rollback: -TargetRoot `"$target`" -Rollback `"$backupRelative/TRANSACTION.json`""
