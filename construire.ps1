# Construit "Prisme.exe" a la racine du projet (Python 3 doit etre installe)
# PyInstaller ecrit son journal sur la sortie d'erreur : on juge sur les codes de retour
$ErrorActionPreference = 'Continue'
$racine = $PSScriptRoot
$travail = Join-Path $racine '.construction'
$venv = Join-Path $travail 'venv'
$python = Join-Path $venv 'Scripts\python.exe'

if (-not (Test-Path $python)) {
    New-Item -ItemType Directory -Force $travail | Out-Null
    & py -3 -m venv $venv
    & $python -m pip install --quiet --upgrade pip
    & $python -m pip install --quiet pyinstaller pillow
    if ($LASTEXITCODE -ne 0) { throw 'Installation de PyInstaller impossible' }
}

$icone = Join-Path $travail 'icone.ico'
& $python (Join-Path $racine 'app\icone.py') $icone
if ($LASTEXITCODE -ne 0) { throw "Creation de l'icone impossible" }

& $python -m PyInstaller --noconfirm --clean --onefile --windowed `
    --name 'Prisme' --icon $icone `
    --add-data "$(Join-Path $racine 'app\index.html');." `
    --distpath $racine --workpath (Join-Path $travail 'build') --specpath $travail `
    (Join-Path $racine 'app\serveur.py')
if ($LASTEXITCODE -ne 0) { throw 'La construction a echoue' }

"Exe cree : $(Join-Path $racine 'Prisme.exe')"
