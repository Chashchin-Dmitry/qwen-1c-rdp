# agent-rdp connect helper. The password is typed by the user here and passed via stdin only; it is not saved or logged.
# Host and user come from environment variables: RDP_HOST (required), RDP_USER (default: user).
$ErrorActionPreference = 'Continue'
$log = Join-Path $PSScriptRoot 'connect_log.txt'
$exe = Join-Path $env:APPDATA 'npm\agent-rdp.cmd'
$rdpHost = $env:RDP_HOST
if (-not $rdpHost) { $rdpHost = Read-Host 'RDP host (replica server)' }
$rdpUser = $env:RDP_USER
if (-not $rdpUser) { $rdpUser = 'user' }
$env:AGENT_RDP_PORT = '47254'
Set-Content $log ("==== " + (Get-Date -Format s)) -Encoding UTF8
& $exe disconnect 2>&1 | Out-Null
$sec = Read-Host ('Password for ' + $rdpUser + ' (input hidden)') -AsSecureString
$plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec))
foreach ($u in @($rdpUser, ('.\' + $rdpUser))) {
  Add-Content $log ("[try user " + $u + "]") -Encoding UTF8
  $out = $plain | & $exe connect --host $rdpHost --username $u --password-stdin --enable-win-automation --stream-port 9224 --width 1920 --height 1080 2>&1
  $txt = ($out | Out-String)
  Add-Content $log $txt -Encoding UTF8
  Write-Host $txt
  if ($txt -notmatch 'ERROR|failed|Failed') { Add-Content $log '[connected]' -Encoding UTF8; break }
  & $exe disconnect 2>&1 | Out-Null
}
$plain = $null
Write-Host 'Done. You can close this window.'
Read-Host 'Press Enter'
