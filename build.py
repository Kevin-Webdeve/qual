"""Build a portable Windows folder and include notices for bundled components."""
import importlib.metadata
import shutil
import subprocess
import sys
from pathlib import Path

from engine import ffmpeg, process_options

root = Path(__file__).resolve().parent
release_directory = root / "dist" / "2.3"
subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
                "--name", "Qual", "--distpath", str(release_directory), "--collect-all", "imageio_ffmpeg", "--add-data", f"{root / 'vendor'};vendor",
                "--add-data", f"{root / 'method_runner.mjs'};.", str(root / "app.py")], cwd=root, check=True)
destination = release_directory / "Qual"
for name in ("README.md", "THIRD_PARTY.md"):
    shutil.copy2(root / name, destination / name)
licenses = destination / "licenses"
licenses.mkdir(exist_ok=True)
for package in ("Pillow", "imageio-ffmpeg", "pyinstaller"):
    distribution = importlib.metadata.distribution(package)
    for relative in distribution.files or []:
        if "license" in relative.name.lower() or "copying" in relative.name.lower():
            source = Path(distribution.locate_file(relative))
            if source.is_file():
                shutil.copy2(source, licenses / f"{package}-{source.name}")
for label, relative in [("Python", "LICENSE.txt"), ("Tcl", "tcl/tcl8.6/license.terms"), ("Tk", "tcl/tk8.6/license.terms")]:
    source = Path(sys.base_prefix) / relative
    if source.is_file():
        shutil.copy2(source, licenses / f"{label}-{source.name}")
shutil.copy2(root / "vendor" / "node" / "LICENSE", licenses / "Node-LICENSE.txt")
shutil.copy2(root / "vendor" / "method-provenance.json", licenses / "method-provenance.json")
for option, name in [("-L", "FFmpeg-license.txt"), ("-buildconf", "FFmpeg-build.txt")]:
    result = subprocess.run([ffmpeg(), option], capture_output=True, **process_options())
    (licenses / name).write_bytes(result.stdout + result.stderr)
print(f"Portable application: {destination / 'Qual.exe'}")
