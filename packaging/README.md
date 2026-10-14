# Experimental Windows portable build

Target: CPython 3.12.10 x64, PyInstaller 6.22.3, `onedir`, no console.
Exact runtime/build dependency versions are in `requirements-build.txt`.
Use a separate environment outside this repository; do not reuse `.venv`.

Set `CYBER_ANALYST_BUILD_ROOT` to an external directory. Prepare unchanged
upstream notices there, with an `origins.json` recording each URL and SHA-256.
Run `collect_notices.py <build-root>/notices --upstream <upstream-directory>`
with the isolated environment, then:

```powershell
& <isolated-python> -m PyInstaller --noconfirm --clean `
  --distpath <build-root>/dist --workpath <build-root>/work `
  packaging/cyber_analyst.spec
```

Also set `PYINSTALLER_CONFIG_DIR` to an external cache directory and redirect
the build log externally. The spec rejects repository-local output/work paths.
It reads the existing `cyber_analyst.__main__` entrypoint without a new launcher.

The application, required native libraries, JSON metaschemas, and original
license notices are included. Datasets, tests, `.git`, runtime/model files,
personal configuration and development environments are not included.

This is an unsigned engineering build, not a public release. Validate the file
inventory, hashes, frozen native paths, external runtime and cleanup before use.
First-run guidance, path persistence, independent clean-machine compatibility,
CPU-only runtime support, signing and installers remain subsequent work.

GPLv3 application licensing does not replace third-party licenses. Before any
redistribution, provide the required corresponding sources and verify native
Qt third-party and Microsoft runtime redistribution obligations.
