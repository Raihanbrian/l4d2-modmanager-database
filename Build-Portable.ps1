param([string]$Python = "$PSScriptRoot\.venv\Scripts\python.exe")
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
& $Python -m pip install -r requirements-build.txt
if ($LASTEXITCODE -ne 0) { throw 'Build dependencies failed' }
# Limit DLL discovery to this Python installation and Windows, not the caller's tools.
$Python = (Resolve-Path -LiteralPath $Python).Path
$base = & $Python -c 'import sys; print(sys.base_prefix)'
if ($LASTEXITCODE -ne 0) { throw 'Python installation lookup failed' }
$previousBuildPath = $env:PATH
try {
    $env:PATH = ((Split-Path -Parent $Python), $base, (Join-Path $base 'Scripts'), (Join-Path $env:SystemRoot 'System32'), $env:SystemRoot) -join ';'
    & $Python -m PyInstaller --noconfirm --clean L4D2ModDatabase.spec
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed' }
} finally {
    $env:PATH = $previousBuildPath
}
$destination = Join-Path $PSScriptRoot 'dist\L4D2ModDatabase'
Copy-Item -LiteralPath 'LICENSE','release\README.txt','release\LICENSE_REVIEW.txt','release\THIRD_PARTY_NOTICES.txt' -Destination $destination
Copy-Item -LiteralPath 'docs\PRIVACY.md' -Destination (Join-Path $destination 'PRIVACY.txt')
$licenses = Join-Path $destination 'licenses'
New-Item -ItemType Directory -Path $licenses -Force | Out-Null
$base = & $Python -c 'import sys; print(sys.base_prefix)'
Copy-Item -LiteralPath (Join-Path $base 'LICENSE.txt') -Destination (Join-Path $licenses 'python-LICENSE.txt')
$pillowLicense = & $Python -c 'from importlib.metadata import distribution; d = distribution("Pillow"); print(d.locate_file(next(p for p in d.files if str(p).endswith(".dist-info/licenses/LICENSE"))))'
if ($LASTEXITCODE -ne 0) { throw 'Pillow license lookup failed' }
Copy-Item -LiteralPath $pillowLicense -Destination (Join-Path $licenses 'pillow-LICENSE')
Copy-Item -LiteralPath 'release\tcl8.6-license.terms' -Destination $licenses
Copy-Item -LiteralPath (Join-Path $base 'tcl\tk8.6\license.terms') -Destination (Join-Path $licenses 'tk8.6-license.terms')
Get-ChildItem -LiteralPath 'release\licenses' -File | ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination $licenses }
$version = & $Python -c 'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])'
$zip = Join-Path $PSScriptRoot "dist\L4D2ModDatabase-$version-win-x64.zip"
Compress-Archive -LiteralPath $destination -DestinationPath $zip -Force
$checksum = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Content -LiteralPath ($zip + '.sha256') -Value ($checksum + '  ' + [IO.Path]::GetFileName($zip)) -Encoding ascii
Get-FileHash -LiteralPath $zip -Algorithm SHA256 | Format-List
