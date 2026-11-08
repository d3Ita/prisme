"""Serveur MCP de Prisme : Claude (Desktop ou Code) cree et modifie des images avec Prisme, sur cet ordinateur.

Transport stdio. Configuration par variables d'environnement :
  PRISME_URL         adresse de Prisme (par defaut http://127.0.0.1:7861, cet ordinateur seulement)
  PRISME_TIMEOUT     secondes d'attente d'une image avant de rendre un identifiant de tache (par defaut 120)
  PRISME_OUTPUT_DIR  dossier ou les images sont copiees, et seul dossier lu pour edit_image (par defaut ~/Prisme-MCP)

  python server.py --check   verifie la configuration et la liste des outils, puis s'arrete
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mcp.server.fastmcp import FastMCP, Image  # noqa: E402
from mcp.server.fastmcp.exceptions import ToolError  # noqa: E402

from prisme_client import Prisme, PrismeErreur, apercu, resume  # noqa: E402

mcp = FastMCP('prisme', instructions=(
    'Prisme creates and edits images locally on this computer with stable-diffusion.cpp. One image at a time: '
    'a creation takes from about 30 seconds on a recent graphics card to several minutes on a Mac or without one. '
    'If a tool returns a task_id, call get_status with it later. Images are saved in PRISME_OUTPUT_DIR.'))


def prisme():
    try:
        return Prisme.depuis_environnement()
    except PrismeErreur as e:
        raise ToolError(str(e)) from None


def appeler(fonction, *args, **kwargs):
    """Erreurs de Prisme en message clair pour Claude, sans trace."""
    try:
        return fonction(*args, **kwargs)
    except PrismeErreur as e:
        raise ToolError(str(e)) from None
    except OSError as e:
        raise ToolError(f'File error: {e.strerror or e}') from None


def contenu(resultat):
    """Texte (chemins, graine) et apercu de l'image pour Claude."""
    sortie = [resume(resultat)]
    for image in resultat.get('images', []):
        donnees, genre = apercu(image['png'])
        if donnees:
            sortie.append(Image(data=donnees, format=genre))
        else:
            sortie.append(f'The image is too large to show here; open {image["path"]}.')
    return sortie


@mcp.tool()
def generate_image(prompt: str, width: int = 1024, height: int = 1024, seed: int | None = None, model: str | None = None):
    """Create an image from a description with Prisme, on this computer.

    width and height: multiples of 16 between 256 and 2048 (1024 x 1024 by default).
    seed: optional, to reproduce an image. model: optional drawing model file from list_models, used for this
    image only. Returns the saved file path and the image, or a task_id to pass to get_status if it takes longer
    than PRISME_TIMEOUT.
    """
    return contenu(appeler(prisme().generer, prompt, width, height, seed, model))


@mcp.tool()
def edit_image(image_path: str, instruction: str):
    """Edit an image with Prisme, following an instruction such as "add snow on the roof".

    image_path: a PNG or JPEG inside PRISME_OUTPUT_DIR (for example an image created by generate_image).
    The result keeps the starting image's proportions. Needs a profile with image editing (Qwen-Image).
    """
    return contenu(appeler(prisme().modifier, image_path, instruction))


@mcp.tool()
def list_models():
    """Model files in Prisme's models folder, the ones currently selected, and whether image editing is possible."""
    return appeler(prisme().modeles)


@mcp.tool()
def list_profiles():
    """Model profiles by hardware (CPU only, 4 to 16 GB graphics cards, Apple Silicon), what is already downloaded,
    and the profile Prisme suggests for this computer."""
    return appeler(prisme().liste_profils)


@mcp.tool()
def get_status(task_id: str | None = None):
    """Prisme's status (busy, progress, configuration problems). With a task_id from generate_image or edit_image,
    returns the finished image, or its progress if it is still running."""
    resultat = appeler(prisme().suivre, task_id)
    return contenu(resultat) if resultat.get('status') == 'done' else resultat


def verifier():
    """Configuration et outils, sans contacter Prisme : pour l'installation et la CI."""
    try:
        p = Prisme.depuis_environnement()
    except PrismeErreur as e:
        sys.exit(f'Configuration error: {e}')
    outils = asyncio.run(mcp.list_tools())
    print(f'Prisme MCP: {p.url}, timeout {p.delai:.0f} s, images in {p.dossier}')
    print('Tools: ' + ', '.join(sorted(o.name for o in outils)))


if __name__ == '__main__':
    if '--check' in sys.argv:
        verifier()
    else:
        mcp.run()
