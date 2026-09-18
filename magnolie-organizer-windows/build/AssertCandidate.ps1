param(
    [Parameter(Mandatory)][string] $Root,
    [Parameter(Mandatory)][string] $Directory
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Release.Common.ps1')
Assert-WindowsCandidate $Root $Directory (Get-ReleaseVersion $Root)
Write-Output 'Current Windows source and candidate artifact binding verified; no native/user approval implied.'
