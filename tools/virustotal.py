"""Send each download to VirusTotal, so anyone can look before they download.

    VIRUSTOTAL_API_KEY=...  python tools/virustotal.py downloads/*

Scanning is what makes the fingerprint links work. Once a file has been through
VirusTotal, https://www.virustotal.com/gui/file/<fingerprint> opens its report
for everybody, with nothing to upload; until then that address says the file is
unknown. This uploads anything VirusTotal hasn't seen, waits for the answer, and
prints what every scanner said, adding it to the run's summary on GitHub.

It never fails a build. A scanner calling a program packed into one file
"suspicious" is a guess about the shape of the file, not a finding about what
the program does, and every unsigned build gets a few.

The free API allows four requests a minute, so this waits between them.
"""

import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

API = "https://www.virustotal.com/api/v3"
REPORT = "https://www.virustotal.com/gui/file"
PAUSE = float(os.environ.get("VIRUSTOTAL_PAUSE", "16"))  # seconds, to stay inside four a minute
WAIT_FOR_SCAN = 15 * 60  # give up waiting for a result after this long


def fingerprint(path):
    """The file's SHA-256, the same number the release lists."""
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def ask(address, key, body=None, kind=None):
    """One request to VirusTotal. Returns the answer, or None when it hasn't heard of the file."""
    request = urllib.request.Request(address, data=body, method="POST" if body else "GET")
    request.add_header("x-apikey", key)
    request.add_header("accept", "application/json")
    if kind:
        request.add_header("content-type", kind)
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=300) as answer:
                return json.load(answer)
        except urllib.error.HTTPError as trouble:
            if trouble.code == 404:
                return None
            if trouble.code == 429 and attempt < 3:  # out of requests for now
                print(f"    waiting for the quota ({60 * (attempt + 1)}s)", flush=True)
                time.sleep(60 * (attempt + 1))
                continue
            raise SystemExit(f"VirusTotal said {trouble.code} {trouble.reason}: "
                             f"{trouble.read()[:300].decode('utf-8', 'replace')}")
    raise SystemExit("VirusTotal kept saying there were too many requests.")


def upload(path, key):
    """Hand the file over, and return the name of the scan to wait for."""
    edge = "----------SpriteScout"
    body = (f"--{edge}\r\nContent-Disposition: form-data; name=\"file\"; "
            f"filename=\"{path.name}\"\r\nContent-Type: application/octet-stream\r\n\r\n"
            ).encode("utf-8") + path.read_bytes() + f"\r\n--{edge}--\r\n".encode("utf-8")
    answer = ask(f"{API}/files", key, body, f"multipart/form-data; boundary={edge}")
    return answer["data"]["id"]


def wait_for(scan, key):
    """Wait until the scanners have finished, then say what they found."""
    until = time.monotonic() + WAIT_FOR_SCAN
    while time.monotonic() < until:
        answer = ask(f"{API}/analyses/{scan}", key)
        if answer and answer["data"]["attributes"]["status"] == "completed":
            return answer["data"]["attributes"]
        print("    still scanning", flush=True)
        time.sleep(PAUSE)
    return None


def already_known(sum_of_file, key):
    """What VirusTotal already has on this exact file, if it's seen it before."""
    answer = ask(f"{API}/files/{sum_of_file}", key)
    if not answer:
        return None
    attributes = answer["data"]["attributes"]
    return {"stats": attributes.get("last_analysis_stats", {}),
            "results": attributes.get("last_analysis_results", {})}


def flagged_by(results):
    """The scanners that said something, as "Name (what it said)"."""
    return [f"{engine} ({found.get('result') or found['category']})"
            for engine, found in sorted(results.items())
            if found.get("category") in ("malicious", "suspicious")]


def scan(path, key, first):
    """Make sure this file has a VirusTotal report, and return what it says."""
    sum_of_file = fingerprint(path)
    print(f"{path.name}  {sum_of_file}", flush=True)
    if not first:
        time.sleep(PAUSE)
    found = already_known(sum_of_file, key)
    if found:
        print("    VirusTotal already had it", flush=True)
    else:
        print(f"    uploading {path.stat().st_size / 1e6:.1f} MB", flush=True)
        time.sleep(PAUSE)
        found = wait_for(upload(path, key), key)
        if not found:
            print("    no result yet; the report will fill in later", flush=True)
            return {"name": path.name, "sum": sum_of_file, "waiting": True}
    stats = found.get("stats", {})
    said_something = flagged_by(found.get("results", {}))
    print(f"    {stats.get('malicious', 0)} of {sum(stats.values())} scanners flagged it"
          + (f": {', '.join(said_something)}" if said_something else ""), flush=True)
    return {"name": path.name, "sum": sum_of_file, "stats": stats, "flagged": said_something}


def summary_line(scanned):
    """One row of the table that goes in the run's summary."""
    if scanned.get("waiting"):
        return (f"| `{scanned['name']}` | still scanning | "
                f"[report]({REPORT}/{scanned['sum']}) |")
    stats = scanned["stats"]
    count = stats.get("malicious", 0) + stats.get("suspicious", 0)
    verdict = "clean" if not count else ", ".join(scanned["flagged"])
    return (f"| `{scanned['name']}` | {count} of {sum(stats.values())} | {verdict} | "
            f"[report]({REPORT}/{scanned['sum']}) |")


def main(names):
    key = os.environ.get("VIRUSTOTAL_API_KEY", "").strip()
    if not key:
        print("No VIRUSTOTAL_API_KEY, so nothing was scanned. A free account at "
              "virustotal.com gives you one; add it as a repository secret called "
              "VIRUSTOTAL_API_KEY and this scans every download from then on.")
        return 0
    files = sorted(Path(name) for name in names if Path(name).is_file())
    if not files:
        print("Nothing to scan.")
        return 0

    everything = [scan(path, key, first=(number == 0)) for number, path in enumerate(files)]
    table = ["| Download | Flagged by | What they said | |", "|---|---|---|---|"]
    table += [summary_line(scanned) for scanned in everything]
    lines = ["## Virus scans", "",
             "Every download went through about seventy scanners. The fingerprint links",
             "above now open these reports for anybody.", "", *table, "",
             "A handful of scanners flag any program packed into a single file, whoever",
             "made it. Nothing here is signed yet, which is the other half of it.", ""]
    print("\n" + "\n".join(lines))
    where = os.environ.get("GITHUB_STEP_SUMMARY")
    if where:
        with open(where, "a", encoding="utf-8") as summary:
            summary.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
