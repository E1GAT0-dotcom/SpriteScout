"""Write the details Windows shows for SpriteScout.exe: its name, version and maker.

Code signing checks that every build carries the same product name and a
version that matches the release, so the build makes this file from the version
in spritescout.py rather than anyone typing it.

    python tools/windows_version.py SpriteScout-windows.exe "SpriteScout" version.txt
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import spritescout as scout  # noqa: E402

PRODUCT = "SpriteScout"


def maker():
    """Whoever the licence says holds the copyright."""
    found = re.search(r"Copyright \(c\) (\d{4}) (.+)", (ROOT / "LICENSE").read_text(encoding="utf-8"))
    return (found.group(2).strip(), found.group(1)) if found else (PRODUCT, "")


def version_numbers(version):
    """"2.6" as the four numbers Windows wants: 2, 6, 0, 0."""
    numbers = [int(part) for part in re.findall(r"\d+", version)][:4]
    return tuple(numbers + [0] * (4 - len(numbers)))


def version_file(file_name, description):
    """The file PyInstaller turns into the details on the Properties > Details tab."""
    holder, year = maker()
    numbers = version_numbers(scout.VERSION)
    strings = {
        "CompanyName": holder,
        "FileDescription": description,
        "FileVersion": scout.VERSION,
        "InternalName": PRODUCT,
        "LegalCopyright": f"Copyright (c) {year} {holder}".strip(),
        "OriginalFilename": file_name,
        "ProductName": PRODUCT,
        "ProductVersion": scout.VERSION,
    }
    table = ",\n          ".join(f"StringStruct({name!r}, {value!r})" for name, value in strings.items())
    return f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={numbers}, prodvers={numbers}, mask=0x3f, flags=0x0,
                    OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([
      StringTable('040904B0', [
          {table}])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    Path(sys.argv[3]).write_text(version_file(sys.argv[1], sys.argv[2]), encoding="utf-8")
    print(f"{sys.argv[3]}: {PRODUCT} {scout.VERSION}, {sys.argv[1]}")
