"""Copy upstream notices from the isolated environment into an external folder."""
import argparse
from hashlib import sha256
from importlib import metadata
import json
from pathlib import Path
import shutil
import sys


RUNTIME_DISTRIBUTIONS = (
    "PySide6", "PySide6_Essentials", "PySide6_Addons", "shiboken6",
    "polars", "polars-runtime-32", "duckdb", "jsonschema",
    "jsonschema-specifications", "referencing", "rpds-py", "attrs",
    "typing_extensions", "packaging", "PyInstaller",
)


def collect(output, upstream):
    output, upstream = Path(output).resolve(), Path(upstream).resolve()
    project = Path(__file__).resolve().parents[1]
    if output.is_relative_to(project):
        raise ValueError("Generated notices must be outside the repository")
    output.mkdir(parents=True, exist_ok=True)
    records = []

    def copy(source, destination, origin):
        destination = output / destination
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        records.append({"file": destination.relative_to(output).as_posix(),
                        "sha256": sha256(destination.read_bytes()).hexdigest(), "origin": origin})

    copy(Path(sys.base_prefix) / "LICENSE.txt", "Python/LICENSE.txt", "CPython 3.12.10 Windows installation LICENSE.txt")
    distributions = []
    for name in RUNTIME_DISTRIBUTIONS:
        distribution = metadata.distribution(name)
        distributions.append({"distribution": name, "version": distribution.version,
                              "license": distribution.metadata.get("License-Expression") or distribution.metadata.get("License")})
        for file in distribution.files or ():
            path = Path(str(file))
            if ".dist-info" in str(path) and "licenses" in path.parts:
                copy(distribution.locate_file(file), Path(name) / path.name,
                     f"https://pypi.org/project/{name}/{distribution.version}/; wheel license file: {file}")
    origins = json.loads((upstream / "origins.json").read_text(encoding="utf-8"))
    for filename, origin in origins.items():
        source = upstream / filename
        if sha256(source.read_bytes()).hexdigest() != origin["sha256"]:
            raise ValueError(f"Upstream notice changed: {filename}")
        copy(source, Path("upstream") / filename, origin["url"])
    (output / "origins.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    (output / "versions.json").write_text(json.dumps(distributions, indent=2), encoding="utf-8")
    (output / "THIRD_PARTY_NOTICES.txt").write_text(
        "Cyber Analyst experimental Windows build\n"
        "Cyber Analyst: GPL-3.0-only; see the application LICENSE.\n"
        "Third-party components retain their upstream licenses, reproduced here without modification.\n"
        "Python: PSF license and the additional notices in Python/LICENSE.txt.\n"
        "Qt/PySide6/Shiboken: use the GPLv3 option for this GPLv3 application; QtCharts is GPLv3/commercial.\n"
        "Commercial Qt texts supplied by the wheels are preserved for provenance, not claimed as a commercial grant.\n"
        "Polars/DuckDB/JSON dependencies: see their original wheel license files.\n"
        "PyInstaller bootloader: GPL-2.0-or-later WITH Bootloader-exception; its terms do not relicense other components.\n"
        "Native Qt third-party attribution overview: upstream/Qt-third-party.html.\n"
        "Microsoft runtime DLLs: governed by Microsoft redistribution terms; see upstream/Microsoft-runtime.html.\n"
        "This inventory does not establish complete legal compliance. Before redistribution, verify native third-party\n"
        "attributions, Microsoft redistributable terms, and provide the corresponding sources required by GPL/LGPL.\n"
        "Application source and build configuration must accompany any distribution under the applicable GPL terms.\n"
        "llama.cpp, CUDA and GGUF models are external and are not redistributed in this package.\n",
        encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--upstream", type=Path, required=True,
                        help="External directory of unchanged authoritative texts plus URL/SHA-256 origins.json")
    args = parser.parse_args()
    collect(args.output, args.upstream)
