# Construit "Prisme.exe" a la racine du projet (Python 3 doit etre installe)
# Prepare un environnement Python dedie, puis laisse construire.py faire le reste
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

& $python (Join-Path $racine 'construire.py')
if ($LASTEXITCODE -ne 0) { throw 'La construction a echoue' }
