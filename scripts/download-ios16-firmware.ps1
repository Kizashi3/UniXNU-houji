param([string]$Proxy = 'http://127.0.0.1:7897')
$ErrorActionPreference = 'Stop'
$portRoot = Split-Path $PSScriptRoot -Parent
$spec = Get-Content -LiteralPath (Join-Path $portRoot 'ios16\firmware.json') -Raw | ConvertFrom-Json
$uri = [Uri]$spec.url
if ($uri.Scheme -ne 'https' -or $uri.Host -ne 'updates.cdn-apple.com') { throw 'Unexpected firmware source' }
$cacheRoot = Join-Path $portRoot 'out\ios16\firmware'
$null = New-Item -ItemType Directory -Path $cacheRoot -Force
$name = [System.IO.Path]::GetFileName($uri.AbsolutePath)
$firmwarePath = Join-Path $cacheRoot $name
$partialPath = $firmwarePath + '.partial'
if (-not (Test-Path -LiteralPath $firmwarePath)) {
    & curl.exe --proxy $Proxy --location --fail --silent --show-error --continue-at - --retry 5 --retry-delay 2 --output $partialPath $spec.url
    if ($LASTEXITCODE -ne 0) { throw "Download interrupted ($LASTEXITCODE); partial file retained for resume" }
    $candidate = $partialPath
} else {
    $candidate = $firmwarePath
    Write-Output 'Checking existing firmware cache'
}
if ((Get-Item -LiteralPath $candidate).Length -ne [long]$spec.bytes) { throw 'Firmware length mismatch' }
$digest = (Get-FileHash -LiteralPath $candidate -Algorithm SHA1).Hash.ToLowerInvariant()
if ($digest -ne $spec.sha1) { throw 'Firmware SHA1 mismatch; candidate retained for inspection' }
$sha256 = (Get-FileHash -LiteralPath $candidate -Algorithm SHA256).Hash.ToLowerInvariant()
if ($spec.sha256 -and $sha256 -ne $spec.sha256) { throw 'Firmware SHA256 mismatch' }
if ($candidate -eq $partialPath) { Move-Item -LiteralPath $partialPath -Destination $firmwarePath }
@{build=$spec.build;version=$spec.version;bytes=[long]$spec.bytes;sha1=$digest;sha256=$sha256;verified=$true} |
    ConvertTo-Json | Set-Content -LiteralPath ($firmwarePath + '.json') -Encoding utf8
Write-Output "Verified firmware cache: $firmwarePath"
