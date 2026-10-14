# Experimental Windows x64 onedir build. All generated paths must be external.
import os
from pathlib import Path
import shutil
from PyInstaller.config import CONF
from PyInstaller.utils.hooks import collect_data_files

project = Path(SPECPATH).resolve().parent
output = Path(os.environ["CYBER_ANALYST_BUILD_ROOT"]).resolve()
if output.is_relative_to(project):
    raise ValueError("CYBER_ANALYST_BUILD_ROOT must be outside the repository")
for key in ("distpath", "workpath"):
    path = Path(CONF[key]).resolve()
    if path.is_relative_to(project) or not path.is_relative_to(output):
        raise ValueError(f"{key} must be inside the external build root")
notices = output / "notices"
if not (notices / "THIRD_PARTY_NOTICES.txt").is_file():
    raise ValueError("Prepare the external third-party notices before building")

a = Analysis(
    [str(project / "src" / "cyber_analyst" / "__main__.py")],
    pathex=[str(project / "src")],
    binaries=[],
    datas=collect_data_files("jsonschema_specifications", includes=["schemas/**/*"]),
    hiddenimports=["_polars_runtime_32._polars_runtime", "rpds.rpds"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["pytest", "_pytest", "pip", "setuptools", "wheel", "tkinter",
              "jsonschema.benchmarks", "jsonschema.tests",
              "PySide6.QtTest", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtNetwork",
              "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
              "PySide6.QtWebEngineQuick", "PySide6.QtMultimedia",
              "PySide6.QtMultimediaWidgets", "PySide6.QtSvg", "PySide6.QtSvgWidgets"],
    noarchive=False,
)
# The current UI has no external image/icon/QML assets. Retain the native Windows
# platform/style plugins, not every platform and image format installed in PySide.
allowed_plugins = {"platforms/qwindows.dll", "styles/qmodernwindowsstyle.dll"}
required_qt_libraries = {"Qt6Core.dll", "Qt6Gui.dll", "Qt6Widgets.dll", "Qt6Charts.dll",
                         "Qt6OpenGL.dll", "Qt6OpenGLWidgets.dll"}
def needed_binary(entry):
    name = entry[0].replace("\\", "/")
    if name.startswith("PySide6/Qt6") and name.endswith(".dll"):
        return name.rsplit("/", 1)[-1] in required_qt_libraries
    marker = "PySide6/plugins/"
    return marker not in name or name.split(marker, 1)[1] in allowed_plugins
a.binaries = [entry for entry in a.binaries if needed_binary(entry)]
# jsonschema's hook collects package data broadly, including benchmark fixtures.
# Keep runtime schemas, but never ship dependency tests/benchmark datasets.
a.datas = [entry for entry in a.datas
           if not {"tests", "benchmarks"}.intersection(entry[0].replace("\\", "/").split("/"))]

pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [("X utf8", None, "OPTION")], exclude_binaries=True,
          name="CyberAnalyst", debug=False, bootloader_ignore_signals=False,
          strip=False, upx=False, console=False, disable_windowed_traceback=False,
          uac_admin=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="CyberAnalyst")
portable = Path(CONF["distpath"]) / "CyberAnalyst"
shutil.copyfile(project / "LICENSE", portable / "LICENSE")
shutil.copytree(notices, portable / "licenses", dirs_exist_ok=True)
(portable / "PORTABLE_README.txt").write_text(
    "Cyber Analyst 0.1.0 - experimental Windows x64 portable build\n"
    "Engineering validation only; unsigned; not a public release.\n"
    "Run CyberAnalyst.exe. Keep the _internal directory beside the executable.\n"
    "No Python installation is required. No administrator privileges are required.\n"
    "Data > Add datasets loads UTF-8 CSVs and enables raw-data browsing/search.\n"
    "For Analyze/AI Analyst, open Settings, select an official llama-server.exe and GGUF model,\n"
    "then Apply settings. Runtime/models are not bundled or automatically downloaded.\n"
    "Multiple models require an explicit selection. Paths are not persisted between sessions.\n"
    "Local lifecycle logs: %LOCALAPPDATA%\\CyberAnalyst\\logs\\application.log.\n"
    "Closing during investigation waits for completion; closing during Analyst requests cancels them.\n"
    "GPL-3.0-only: see LICENSE and licenses/THIRD_PARTY_NOTICES.txt.\n"
    "Before redistribution, supply corresponding sources and resolve remaining third-party obligations.\n",
    encoding="utf-8")
