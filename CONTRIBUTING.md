# Contributing to Prisme

Thanks for your interest! Bug reports, ideas and pull requests are welcome, in English or French.

## Reporting a bug

Open an [issue](../../issues/new/choose) with the **Bug report** template. Please include your Prisme version (shown at the bottom of **Réglages**), your GPU and VRAM, and what you expected versus what happened. Never paste your access code (`app/code-acces.txt`).

## Suggesting a feature

Open an issue with the **Feature request** template and describe the problem it solves before the solution. Prisme aims to stay simple: one exe, a clear interface, no required dependency.

## Working on the code

```powershell
git clone https://github.com/d3Ita/prisme.git
cd prisme
py -3 app\serveur.py
```

Put your models in `models/`; the app installs its engines on first launch. Before opening a pull request:

1. Run the tests: `py -3 -m unittest discover -s tests -v`
2. Add a test for any change to the server, especially anything touching access control.
3. Keep the server on the Python standard library and the interface free of external dependencies.
4. Match the existing style: French identifiers and comments, short functions, no unused code.

The tests run automatically on GitHub for every pull request.

## Security issues

Please don't open a public issue for a security problem. Use GitHub's **Report a vulnerability** button in the **Security** tab instead.
