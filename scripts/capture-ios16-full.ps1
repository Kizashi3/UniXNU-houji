param(
    [ValidateRange(30,86400)][int]$Seconds = 1800,
    [Parameter(Mandatory=$true)][string]$Directory
)
$ErrorActionPreference = 'Stop'
$folder = [System.IO.Path]::GetFullPath($Directory)
if ([System.IO.Directory]::Exists($folder)) { throw 'Use a new capture directory' }
$null = [System.IO.Directory]::CreateDirectory($folder)
$deadline = [DateTime]::UtcNow.AddSeconds($Seconds)
$events = Join-Path $folder 'host-events.log'
$serial = $null
$stream = $null
$buffer = [byte[]]::new(65536)
$part = 0
$total = 0L
$connections = 0
$nextStatus = [DateTime]::UtcNow
$nextNotice = [DateTime]::UtcNow
function Event([string]$message) {
    Add-Content -LiteralPath $events -Encoding utf8 -Value ([DateTime]::UtcNow.ToString('o') + ' ' + $message)
}
function DebugPort {
    $key = 'Registry::HKEY_LOCAL_MACHINE\SYSTEM\CurrentControlSet\Enum\USB\VID_1209&PID_0001\ACE5DBG001\Device Parameters'
    $name = (Get-ItemProperty -LiteralPath $key -Name PortName -ErrorAction SilentlyContinue).PortName
    if ($name -match '^COM[0-9]+$' -and [System.IO.Ports.SerialPort]::GetPortNames() -contains $name) { $name }
}
Event 'capture-start; raw bytes preserved; replay on connect; status every 30 seconds; no flash/reboot commands'
try {
    $stream = [System.IO.File]::Open((Join-Path $folder 'serial-000.log'),[System.IO.FileMode]::CreateNew,
        [System.IO.FileAccess]::Write,[System.IO.FileShare]::Read)
    while ([DateTime]::UtcNow -lt $deadline) {
        if (-not $serial) {
            $port = DebugPort
            if (-not $port) { Start-Sleep -Milliseconds 500; continue }
            try {
                $serial = [System.IO.Ports.SerialPort]::new($port,115200,[System.IO.Ports.Parity]::None,8,[System.IO.Ports.StopBits]::One)
                $serial.DtrEnable=$true; $serial.RtsEnable=$true
                $serial.ReadTimeout=500; $serial.WriteTimeout=2000; $serial.ReadBufferSize=262144
                $serial.Open(); $serial.Write("replay`n")
                $connections++; Event "connected $port; connection=$connections"
                Write-Output "Connected $port; preserving complete stream in $folder"
                $nextStatus=[DateTime]::UtcNow.AddSeconds(30)
            } catch {
                Event ('connect-error: '+$_.Exception.Message)
                if ($serial) { $serial.Dispose(); $serial=$null }
                Start-Sleep -Milliseconds 500; continue
            }
        }
        try {
            if ([DateTime]::UtcNow -ge $nextStatus) {
                $serial.Write("status`n"); $nextStatus=[DateTime]::UtcNow.AddSeconds(30)
            }
            $n=$serial.Read($buffer,0,$buffer.Length)
            if ($n -gt 0) {
                if ($stream.Length+$n -gt 64MB) {
                    $stream.Dispose(); $part++
                    $path=Join-Path $folder ('serial-{0:d3}.log' -f $part)
                    $stream=[System.IO.File]::Open($path,[System.IO.FileMode]::CreateNew,[System.IO.FileAccess]::Write,[System.IO.FileShare]::Read)
                    Event "rotate part=$part"
                }
                $stream.Write($buffer,0,$n); $stream.Flush(); $total+=$n
            }
        } catch [System.TimeoutException] {
        } catch {
            Event ('stream-error: '+$_.Exception.Message)
            if ($serial) { $serial.Dispose(); $serial=$null }
        }
        if ([DateTime]::UtcNow -ge $nextNotice) {
            Write-Output "Captured $total bytes; parts=$($part+1); connections=$connections"
            $nextNotice=[DateTime]::UtcNow.AddSeconds(60)
        }
    }
} finally {
    if ($serial) { $serial.Dispose() }
    if ($stream) { $stream.Dispose() }
    Event "capture-stop bytes=$total parts=$($part+1) connections=$connections"
    $files=@(Get-ChildItem -LiteralPath $folder -Filter 'serial-*.log' -File | Sort-Object Name | ForEach-Object {
        @{name=$_.Name; bytes=$_.Length; sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()}
    })
    @{bytes=$total;connections=$connections;parts=$files;rebooted=$false;flashed=$false} |
        ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $folder 'capture.json') -Encoding utf8
}
