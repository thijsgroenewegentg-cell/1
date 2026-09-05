# /.github/README.md

## Enabling continuous integration

`ci.yml` in this folder is a ready-to-use GitHub Actions workflow. It is stored
here rather than in `.github/workflows/` because the token that created this
branch is not allowed to push workflow files. Activate it with one command:

```bash
mkdir -p .github/workflows
git mv .github/ci.yml .github/workflows/ci.yml
git commit -m "Enable CI"
git push
```

What it does on every push and pull request, entirely on GitHub's free tier:

| Job | Steps |
|---|---|
| `test` | pyflakes lint · `compileall` · the 111-check offline smoke suite · a one-shot `main.py --say` run |
| `package` | builds a wheel + sdist with `python -m build` and checks them with `twine` |

The matrix covers Ubuntu, macOS and Windows on Python 3.11, plus Python 3.9 and
3.12 on Ubuntu. No models are downloaded — `tests/mock_ollama.py` stands in for
Ollama, including token streaming and vision replies.
