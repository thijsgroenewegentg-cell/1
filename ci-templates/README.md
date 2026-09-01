# CI templates — enable in one step

GitHub blocks *bots* from pushing files into `.github/workflows/` without
special permission, so these ship as templates.

**To enable CI + automated installer builds**, from your own machine:

```bash
mkdir -p .github/workflows
cp ci-templates/ci.yml ci-templates/release.yml .github/workflows/
git add .github && git commit -m "Enable CI" && git push
```

(or create the same two files via the GitHub web UI → Add file.)

What you get:

| File | Trigger | Does |
| --- | --- | --- |
| `ci.yml` | every push / PR | runs the 101-check test suite on Windows **and** Linux runners |
| `release.yml` | every `v*` tag push | builds `Setup.exe` + portable `exe` + `AppImage` + `deb` and attaches them to the GitHub release |

Both are free for public repos; private repos use the free CI minutes allowance.
