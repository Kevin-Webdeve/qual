"""Fetch the publicly offered local method helper and a verified Node LTS runtime."""
import hashlib
import io
import json
import urllib.request
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
vendor = root / "vendor"
method = vendor / "method"
node = vendor / "node"
method.mkdir(parents=True, exist_ok=True)
node.mkdir(parents=True, exist_ok=True)


def download(url):
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 Qual desktop setup"})
    with urllib.request.urlopen(request, timeout=90) as response:
        return response.read()


helper_url = "https://compressbase.com/method-api/sl-sr.mjs"
helper = download(helper_url)
if b"patchSlSr" not in helper or len(helper) > 200_000:
    raise ValueError("The public helper has an unexpected format.")
(method / "sl-sr.mjs").write_bytes(helper)
releases = json.loads(download("https://nodejs.org/dist/index.json"))
release = next(item for item in releases if item["lts"] and "win-x64-zip" in item["files"])
version = release["version"]
archive_name = f"node-{version}-win-x64.zip"
base_url = f"https://nodejs.org/dist/{version}/"
checksums = download(base_url + "SHASUMS256.txt").decode()
expected = next(line.split()[0] for line in checksums.splitlines() if line.split()[-1] == archive_name)
archive = download(base_url + archive_name)
actual = hashlib.sha256(archive).hexdigest()
if actual != expected:
    raise ValueError("Node archive SHA256 verification failed.")
with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
    prefix = f"node-{version}-win-x64/"
    for name in ("node.exe", "LICENSE"):
        (node / name).write_bytes(zipped.read(prefix + name))
(vendor / "method-provenance.json").write_text(json.dumps({
    "helper_url": helper_url, "helper_sha256": hashlib.sha256(helper).hexdigest(),
    "helper_documentation": "https://compressbase.com/method-api",
    "node_version": version, "node_archive_url": base_url + archive_name,
    "node_archive_sha256": actual,
    "notice": "Powered by CompressBase. Public local SL/SR helper, unmodified. No legacy patch API calls.",
}, indent=2), encoding="utf-8")
print(f"Installed public local SL/SR helper and verified Node {version}.")
