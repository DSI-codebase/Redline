"""A stand-in for the Tesseract binary, for ``tests/test_ocr.py``.

Run as ``python _tesseract_stand_in.py WORKDIR <Tesseract's own arguments>``.
It answers ``--version`` as Tesseract 5.3.4 does. Otherwise it copies
``WORKDIR/answer.tsv`` or ``WORKDIR/answer.txt`` to the output file pytesseract
asked for, and appends one JSON line to ``WORKDIR/runs.jsonl`` saying which
output was asked for and what image arrived. Standard library only, because it
runs in its own process.
"""

import json
import os
import struct
import sys

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def main(argv):
    workdir, args = argv[0], argv[1:]
    if args == ["--version"]:
        sys.stdout.write("tesseract 5.3.4\n leptonica-1.84.1\n")
        return 0

    image, output_base = args[0], args[1]
    with open(image, "rb") as fh:
        head = fh.read(24)
    png = head[:8] == PNG_SIGNATURE
    # Tesseract writes TSV when configured to, and plain text otherwise.
    output = "tsv" if "tessedit_create_tsv=1" in args else "txt"

    run = {"output": output, "png": png,
           "size": list(struct.unpack(">II", head[16:24])) if png else None}
    with open(os.path.join(workdir, "runs.jsonl"), "a",
              encoding="utf-8") as fh:
        fh.write(json.dumps(run) + "\n")

    with open(os.path.join(workdir, "answer." + output), "rb") as src:
        answer = src.read()
    with open(output_base + "." + output, "wb") as dst:
        dst.write(answer)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
