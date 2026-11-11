#!/usr/bin/env python3
"""Turn an ef_capture.py capture into a test fixture with every serial number replaced.

usage: uv run python scripts/ef_make_fixture.py <capture.jsonl> <out.jsonl> [--max-per-kind N]
Serial-like ASCII runs (16 upper-case letters/digits mixing both) become fakes of the same
length that keep the 4-char product prefix, so protobuf lengths stay valid. Topics are reduced
to (api, kind, device prefix) so no account id survives. Check the output before committing.
"""

import argparse
import collections
import json
import re

SERIAL = re.compile(rb"(?<![A-Z0-9])[A-Z0-9]{16}(?![A-Z0-9])")


def fake_for(serial: bytes, table: dict[bytes, bytes]) -> bytes:
    if serial not in table:
        n = sum(1 for s in table if s[:4] == serial[:4]) + 1
        table[serial] = serial[:4] + b"TEST" + str(n).zfill(len(serial) - 8).encode()
    return table[serial]


def scrub(payload: bytes, table: dict[bytes, bytes]) -> bytes:
    def repl(m: re.Match[bytes]) -> bytes:
        s = m.group(0)
        if not (re.search(rb"[A-Z]", s) and re.search(rb"[0-9]", s)):
            return s
        return fake_for(s, table)

    return SERIAL.sub(repl, payload)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("capture")
    ap.add_argument("out")
    ap.add_argument("--max-per-kind", type=int, default=0, help="0 keeps every frame")
    args = ap.parse_args()

    table: dict[bytes, bytes] = {}
    kept: collections.Counter = collections.Counter()
    t0 = None
    with open(args.capture) as src, open(args.out, "w") as out:
        for line in src:
            r = json.loads(line)
            serial = re.search(r"/([A-Z0-9]{16})(/|$)", r["topic"])
            prefix = fake_for(serial.group(1).encode(), table).decode() if serial else ""
            kind = r["topic"].rstrip("/").split("/")[-1] if r["api"] == "public" else (
                "property" if "/device/property/" in r["topic"] else r["topic"].split("/")[-1]
            )
            key = (r["api"], kind, prefix)
            if args.max_per_kind and kept[key] >= args.max_per_kind:
                continue
            kept[key] += 1
            t0 = t0 if t0 is not None else r["t"]
            payload = scrub(bytes.fromhex(r["hex"]), table)
            out.write(json.dumps({"dt": round(r["t"] - t0, 3), "api": r["api"], "kind": kind,
                                  "device": prefix, "hex": payload.hex()}) + "\n")
    for k, v in sorted(kept.items()):
        print(v, *k)
    print("replaced serials:", len(table))


if __name__ == "__main__":
    main()
