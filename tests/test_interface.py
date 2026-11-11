"""Tests de l'interface (app/index.html) : chaque script de la page doit etre du JavaScript valide.

Une seule apostrophe non echappee dans les traductions casse tout le premier script : plus de traductions, et les
fonctions qui en dependent (fenetre des modeles, dates du fil...) plantent. Ce test passe par Node.js (node --check),
et ne fait rien si Node.js n'est pas installe.
Lancement : py -3 -m unittest tests.test_interface -v
"""

import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

PAGE = Path(__file__).resolve().parent.parent / 'app' / 'index.html'
NODE = shutil.which('node')


@unittest.skipUnless(NODE, 'Node.js absent : syntaxe des scripts non verifiee')
class ScriptsDeLaPageTest(unittest.TestCase):
    def test_syntaxe_des_scripts(self):
        scripts = re.findall(r'<script>(.*?)</script>', PAGE.read_text(encoding='utf-8'), re.S)
        self.assertGreaterEqual(len(scripts), 2)
        with tempfile.TemporaryDirectory() as dossier:
            for i, script in enumerate(scripts):
                with self.subTest(script=i):
                    fichier = Path(dossier) / f'script{i}.js'
                    fichier.write_text(script, encoding='utf-8')
                    resultat = subprocess.run([NODE, '--check', str(fichier)], capture_output=True, text=True)
                    self.assertEqual(resultat.returncode, 0, resultat.stderr[-800:])


if __name__ == '__main__':
    unittest.main()
