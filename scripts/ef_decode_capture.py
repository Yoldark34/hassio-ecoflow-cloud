#!/usr/bin/env python3
"""Summarise a capture from ef_capture.py: EcoPacket cmd_func/cmd_id per device, and the keys the
STREAM_AC_5000 decoder extracts from each private frame (with last value).

usage: uv run python scripts/ef_decode_capture.py <capture.jsonl> [--values]
"""
import collections
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from custom_components.ecoflow_cloud.devices.internal import stream_ac_5000 as s5  # noqa: E402


def label(topic: str) -> str:
    m = re.search(r"(ES2[12])[A-Z0-9]*", topic)
    return m.group(1) if m else topic


rows = [json.loads(line) for line in open(sys.argv[1])]
cmds: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
keys: dict[str, dict] = collections.defaultdict(dict)
dec = s5.StreamAC5000.__new__(s5.StreamAC5000)
for r in rows:
    if r["api"] != "private" or "/property/" not in r["topic"]:
        continue
    dev = label(r["topic"])
    raw = bytes.fromhex(r["hex"])
    for h in s5._iter_packets(raw):
        cmds[dev][(h.cmd_func, h.cmd_id, h.src, len(h.pdata))] += 0
        cmds[dev][(h.cmd_func, h.cmd_id, h.src)] += 1
    for k, v in dec._prepare_data(raw)["params"].items():
        keys[dev][k] = v
for dev in sorted(cmds):
    print(f"== {dev} cmd_func/cmd_id/src counts:", {k: v for k, v in cmds[dev].items() if len(k) == 3})
    print(f"   decoded keys ({len(keys[dev])}):", sorted(keys[dev]) if "--values" not in sys.argv else keys[dev])
