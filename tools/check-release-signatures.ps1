param(
    [Parameter(Mandatory)][string]$Installer,
    [Parameter(Mandatory)][string]$Payload,
    [string]$SignerThumbprint = $env:STAR_RELEASE_SIGNER_SHA1
)

$ErrorActionPreference = 'Stop'
if ($SignerThumbprint -notmatch '^[a-fA-F0-9]{40}$') {
    throw 'The approved release certificate thumbprint is required.'
}

$paths = [ordered]@{
    Installer = $Installer
    Application = Join-Path $Payload '星译官.exe'
    Uninstaller = Join-Path $Payload 'Uninstall 星译官.exe'
    SetupUi = Join-Path $Payload '$PLUGINSDIR/stage/StarTranslatorSetup.exe'
}
$results = foreach ($target in $paths.GetEnumerator()) {
    $signature = Get-AuthenticodeSignature -LiteralPath $target.Value
    if ($signature.Status -ne 'Valid' -or $signature.SignatureType -ne 'Authenticode') {
        throw "$($target.Key) has no trusted Authenticode signature ($($signature.Status)). $($signature.StatusMessage)"
    }
    if ($signature.SignerCertificate.Thumbprint -ne $SignerThumbprint) {
        throw "$($target.Key) was signed by a different publisher certificate."
    }
    if (-not $signature.TimeStamperCertificate) {
        throw "$($target.Key) is missing a trusted timestamp."
    }
    [pscustomobject]@{
        component = $target.Key
        publisher = $signature.SignerCertificate.Subject
        timestampAuthority = $signature.TimeStamperCertificate.Subject
        sha256 = (Get-FileHash -LiteralPath $target.Value -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}
if (($results | Where-Object component -eq 'Application').sha256 -ne ($results | Where-Object component -eq 'SetupUi').sha256) {
    throw 'The signed setup UI differs from the signed application.'
}
$results | ConvertTo-Json
