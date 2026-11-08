"""Serveur MCP de Prisme, pour qui travaille sur le code : equivalent de `Prisme.exe --mcp`.

Le serveur MCP est integre a Prisme (app/mcp_prisme.py, bibliotheque standard seulement) : rien a installer.
  python mcp/server.py           serveur MCP sur l'entree et la sortie standard
  python mcp/server.py --check   verifie la configuration et liste les outils
Variables : PRISME_URL, PRISME_TIMEOUT, PRISME_OUTPUT_DIR (voir mcp/README.md).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'app'))

if __name__ == '__main__':
    if '--mcp' not in sys.argv:
        sys.argv.append('--mcp')
    import serveur  # noqa: E402

    serveur.main()
