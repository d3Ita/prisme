"""Le serveur MCP integre (`serveur.py --mcp`, bibliotheque standard) avec le client MCP officiel, comme Claude.

Ignore si le paquet `mcp` (SDK officiel) n'est pas installe ; la CI l'installe pour ce test seulement.
Lancement : py -3 -m unittest tests.test_protocole_mcp -v
"""

import asyncio
import base64
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
except ImportError:
    ClientSession = None

from test_mcp import FauxPrisme, png  # noqa: E402

SERVEUR = Path(__file__).resolve().parent.parent / 'app' / 'serveur.py'


@unittest.skipIf(ClientSession is None, 'SDK MCP officiel absent (pip install mcp)')
class ProtocoleOfficielTest(unittest.TestCase):
    def setUp(self):
        self.faux = FauxPrisme()
        self.faux.image = png(512, 384)
        self.addCleanup(self.faux.fermer)
        dossier = tempfile.TemporaryDirectory(prefix='prisme_protocole_', ignore_cleanup_errors=True)
        self.addCleanup(dossier.cleanup)
        self.dossier = Path(dossier.name)

    def session(self, appels):
        async def deroulement():
            # Dossier de travail temporaire : le serveur MCP ne touche pas aux donnees de Prisme
            params = StdioServerParameters(command=sys.executable, args=[str(SERVEUR), '--mcp'], env={
                **os.environ, 'PRISME_URL': self.faux.url, 'PRISME_OUTPUT_DIR': str(self.dossier / 'sorties'),
                'PRISME_RACINE': str(self.dossier / 'racine'), 'PRISME_TIMEOUT': '20'})
            async with stdio_client(params) as (lecture, ecriture):
                async with ClientSession(lecture, ecriture) as session:
                    init = await session.initialize()
                    outils = await session.list_tools()
                    resultats = [await session.call_tool(nom, arguments) for nom, arguments in appels]
                    return init, outils, resultats
        return asyncio.run(asyncio.wait_for(deroulement(), 60))

    def test_creation_et_modification_par_le_client_officiel(self):
        init, outils, (statut, creation, modification, erreur) = self.session([
            ('get_status', {}),
            ('generate_image', {'prompt': 'un renard', 'width': 512, 'height': 384, 'seed': 3}),
            ('edit_image', {'image_path': 'image_20261108_120000.png', 'instruction': 'ajoute de la neige'}),
            ('generate_image', {'prompt': 'un renard', 'width': 1000}),
        ])
        self.assertEqual(init.serverInfo.name, 'prisme')
        self.assertIn('Prisme', init.instructions)
        self.assertEqual({o.name for o in outils.tools}, {'generate_image', 'edit_image', 'list_models', 'list_profiles',
                                                         'get_status', 'install_engine', 'download_profile', 'download_model'})
        self.assertFalse(statut.isError)
        self.assertEqual(json.loads(statut.content[0].text)['version'], '1.8.5')
        self.assertFalse(creation.isError)
        infos = json.loads(creation.content[0].text)
        self.assertEqual((infos['status'], infos['seed'], infos['width']), ('done', 3, 512))
        self.assertEqual(creation.content[1].type, 'image')
        self.assertEqual(base64.b64decode(creation.content[1].data), self.faux.image)
        self.assertFalse(modification.isError)
        self.assertTrue(self.faux.recu[1]['source_data'].startswith('data:image/png;base64,'))
        self.assertTrue(erreur.isError)
        self.assertIn('multiple of 16', erreur.content[0].text)
        self.assertNotIn('Traceback', erreur.content[0].text)

    def test_accord_de_l_utilisateur_par_le_client_officiel(self):
        _, _, (profil, externe) = self.session([
            ('download_profile', {'profile_id': 'qwen-12go'}),
            ('download_model', {'url': 'https://huggingface.co/a/b/resolve/main/mien.gguf', 'use_as': 'vae'}),
        ])
        self.assertEqual(json.loads(profil.content[0].text)['approved_by_user'], True)
        self.assertEqual(json.loads(externe.content[0].text)['status'], 'downloading')
        self.assertEqual([c for c, _, _ in self.faux.posts], ['/api/demander-telechargement'] * 2)


if __name__ == '__main__':
    unittest.main()
