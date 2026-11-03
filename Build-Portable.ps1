param([string]$Python = "$PSScriptRoot\.venv\Scripts\python.exe")
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
& $Python -m pip install -r requirements-build.txt
if ($LASTEXITCODE -ne 0) { throw 'Build dependencies failed' }
& $Python -m PyInstaller --noconfirm --clean L4D2ModDatabase.spec
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed' }
$destination = Join-Path $PSScriptRoot 'dist\L4D2ModDatabase'
Copy-Item -LiteralPath 'LICENSE','release\README.txt','release\LICENSE_REVIEW.txt','release\THIRD_PARTY_NOTICES.txt' -Destination $destination
Copy-Item -LiteralPath 'docs\PRIVACY.md' -Destination (Join-Path $destination 'PRIVACY.txt')
$licenses = Join-Path $destination 'licenses'
New-Item -ItemType Directory -Path $licenses -Force | Out-Null
$base = & $Python -c 'import sys; print(sys.base_prefix)'
Copy-Item -LiteralPath (Join-Path $base 'LICENSE.txt') -Destination (Join-Path $licenses 'python-LICENSE.txt')
Copy-Item -LiteralPath (Join-Path $PSScriptRoot '.venv\Lib\site-packages\pillow-12.3.0.dist-info\licenses\LICENSE') -Destination (Join-Path $licenses 'pillow-LICENSE')
Copy-Item -LiteralPath 'release\tcl8.6-license.terms' -Destination $licenses
Copy-Item -LiteralPath (Join-Path $base 'tcl\tk8.6\license.terms') -Destination (Join-Path $licenses 'tk8.6-license.terms')
Get-ChildItem -LiteralPath 'release\licenses' -File | ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination $licenses }
$version = & $Python -c 'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])'
$zip = Join-Path $PSScriptRoot "dist\L4D2ModDatabase-$version-win-x64.zip"
Compress-Archive -LiteralPath $destination -DestinationPath $zip -Force
$checksum = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Content -LiteralPath ($zip + '.sha256') -Value ($checksum + '  ' + [IO.Path]::GetFileName($zip)) -Encoding ascii
Get-FileHash -LiteralPath $zip -Algorithm SHA256 | Format-List
