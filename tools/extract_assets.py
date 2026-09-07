#!/usr/bin/env python3
"""Rebuild the two vendor assets alfenctl ships, from Alfen's own installer.

``src/alfenctl/EDS.xml`` and ``src/alfenctl/logo_blobs.bin`` are not written
by hand and cannot be regenerated from anything in this repository.  Both
come out of the *ACE Service Installer*, and this script is the record of
how -- so that a future version of the app can be diffed against what we
ship rather than trusted:

* **EDS.xml** is the property catalog: every property id, its name, type,
  access and category.  The app carries it verbatim next to its
  executables, and so do we.
* **logo_blobs.bin** is the concatenation of the seven display assets a
  ``.fwu`` package must contain besides the customer logo -- four status
  icons and three Robotica fonts.  The app has them as byte arrays in
  ``ICUObjects.cs``; the file is those arrays, back to back, in the order
  :data:`alfenctl.logo.FWU_FIXED_OBJECTS` lists them.  There is no framing
  in it, which is why that table records each one's length.

Getting the inputs (once, on any machine):

1. Take ``ACE Service Installer vX.Y.Z.msi`` from Alfen and unpack it --
   ``msiextract`` from msitools, or 7-Zip -- to get the app directory.
   ``EDS.xml`` is in there as it stands.
2. ``ACEFWUCreator.dll`` from the same directory holds ``ICUObjects``.
   Decompile it (ILSpy, ``ilspycmd -p``) to get ``ICUObjects.cs``.

Then::

    (
        tools / extract_assets.py
        - -app
        - dir / path / to / app
        - -objects / path / to / ICUObjects.cs
    )
    tools / extract_assets.py - -check - -objects / path / to / ICUObjects.cs

``--check`` writes nothing and exits non-zero if what we ship differs, which
is the form worth running against a new release of the app.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from alfenctl.logo import BLOB_FILE, FWU_FIXED_OBJECTS  # noqa: E402

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "alfenctl"
EDS_FILE = "EDS.xml"

# `public static byte[] font_robotica_28 = new byte[18068] { 1, 2, ... };`
ARRAY = re.compile(
    r"public\s+static\s+byte\[\]\s+(?P<name>\w+)\s*=\s*new\s+byte\[(?P<size>\d+)\]"
    r"\s*\{(?P<body>[^}]*)\}",
    re.DOTALL,
)


def read_objects(source: Path) -> dict[str, bytes]:
    """Return every ``byte[]`` in a decompiled ``ICUObjects.cs``, by name."""
    arrays: dict[str, bytes] = {}
    for match in ARRAY.finditer(source.read_text(encoding="utf-8", errors="replace")):
        values = [
            int(v) for v in match["body"].replace("\n", " ").split(",") if v.strip()
        ]
        declared = int(match["size"])
        if len(values) != declared:
            raise SystemExit(
                f"{source}: {match['name']} declares {declared} bytes "
                f"but lists {len(values)}"
            )
        arrays[match["name"]] = bytes(values)
    return arrays


def build_blobs(source: Path) -> bytes:
    """Concatenate the assets alfenctl needs, in the order it slices them apart."""
    arrays = read_objects(source)
    missing = [obj.name for obj in FWU_FIXED_OBJECTS if obj.name not in arrays]
    if missing:
        raise SystemExit(f"{source}: no byte[] named {', '.join(missing)}")
    out = bytearray()
    for obj in FWU_FIXED_OBJECTS:
        blob = arrays[obj.name]
        if len(blob) != obj.blob_bytes:
            raise SystemExit(
                f"{obj.name} is {len(blob)} bytes in {source.name}, but "
                f"alfenctl.logo.FWU_FIXED_OBJECTS says {obj.blob_bytes}. "
                "The app's assets changed; update the table before regenerating."
            )
        out += blob
    return bytes(out)


def _report(name: str, produced: bytes, *, check: bool) -> bool:
    """Write ``produced`` over the shipped file, or compare it; True if they match."""
    target = PACKAGE / name
    current = target.read_bytes() if target.is_file() else b""
    if produced == current:
        print(f"{name}: unchanged ({len(produced)} bytes)")
        return True
    if check:
        print(
            f"{name}: DIFFERS -- shipped {len(current)} bytes, "
            f"the app gives {len(produced)}",
            file=sys.stderr,
        )
        return False
    target.write_bytes(produced)
    print(f"{name}: written ({len(produced)} bytes)")
    return True


def main(argv: list[str] | None = None) -> int:
    """Rebuild or verify the bundled vendor assets."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--app-dir", type=Path, help=f"the unpacked installer, holding {EDS_FILE}"
    )
    parser.add_argument(
        "--objects", type=Path, help="ICUObjects.cs, decompiled from ACEFWUCreator.dll"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="compare only; write nothing and exit 1 on a difference",
    )
    args = parser.parse_args(argv)
    if not args.app_dir and not args.objects:
        parser.error("give --app-dir, --objects, or both")

    ok = True
    if args.app_dir:
        eds = args.app_dir / EDS_FILE
        if not eds.is_file():
            raise SystemExit(f"no {EDS_FILE} in {args.app_dir}")
        ok &= _report(EDS_FILE, eds.read_bytes(), check=args.check)
    if args.objects:
        ok &= _report(BLOB_FILE, build_blobs(args.objects), check=args.check)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
