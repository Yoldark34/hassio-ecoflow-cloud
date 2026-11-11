#!/usr/bin/env python3
"""Run the integration's hybrid client against the real account, outside Home Assistant, read-only.

usage: uv run python scripts/ef_live_check.py [seconds=60] [--app-only]
Logs in to the app API (and the open API unless --app-only) with ~/.config/ecoflow/credentials.json,
lists the account, groups STREAM units into packs, follows MQTT for a while, then prints what the
units and packs hold. Serials are shortened in the output. Nothing is written to the devices.
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_components.ecoflow_cloud import _discover_packs  # noqa: E402
from custom_components.ecoflow_cloud.api.hybrid_api import EcoflowHybridApiClient  # noqa: E402
from custom_components.ecoflow_cloud.api.private_api import EcoflowPrivateApiClient  # noqa: E402
from custom_components.ecoflow_cloud.device_data import DeviceData, DeviceOptions  # noqa: E402
from custom_components.ecoflow_cloud.devices.internal.stream_ac_5000 import StreamAC5000  # noqa: E402

KEYS = [
    "soc", "batteryPower", "bpPower", "gridPortPower", "unitInverterPower", "unitOnGridPower", "unitPvPower",
    "remainCap", "systemRole", "acOutEnabled",
    "sysEnergyStreamReport.bpSoc", "sysEnergyStreamReport.bpPwr", "sysEnergyStreamReport.loadPwr",
    "sysEnergyStreamReport.gridPwr", "sysEnergyStreamReport.pvPwr", "sysEnergyStreamReport.onGridPwr",
    "bpBackupConfig.backupSocOnOff", "bpBackupConfig.backupSoc", "powerParameterConfig.feedToGridLimitOnOff",
    "workMode", "cmsMaxChgSoc", "cmsMinDsgSoc", "feedGridModePowLimit", "meterLinkUp", "meterTotalPower",
    "masterSn", "systemDevCnt",
]


def short(sn: str | None) -> str:
    return f"{sn[:4]}…{sn[-4:]}" if sn and len(sn) > 8 else str(sn)


async def main() -> None:
    seconds = int(next((a for a in sys.argv[1:] if a.isdigit()), "60"))
    cred = json.load(open(os.path.expanduser("~/.config/ecoflow/credentials.json")))
    host = "api-e.ecoflow.com" if cred.get("region", "eu") == "eu" else "api.ecoflow.com"
    if "--app-only" in sys.argv:
        client = EcoflowPrivateApiClient(host, cred["account"]["email"], cred["account"]["password"], "Home")
    else:
        dev = cred["developer_api"]
        client = EcoflowHybridApiClient(
            host, cred["account"]["email"], cred["account"]["password"], "Home", host, dev["access_key"], dev["secret_key"]
        )
    await client.login()
    found = await client.fetch_all_available_devices()
    print("account:", [(short(d.sn), d.device_type, d.status) for d in found])

    options = DeviceOptions(5, 100, False, False, 300, True, 0)
    for info in found:
        if info.device_type == "STREAM_AC_5000":
            client.configure_device(DeviceData(info.sn, info.name, info.device_type, options, None, None), {d.sn: d for d in found})
    packs = await _discover_packs(client)
    for pack in packs:
        client.add_device(pack)
        print("pack:", pack.device_data.name, "members", [short(m.device_info.sn) for m in pack.members],
              "app main unit", short(pack.system.main_sn))

    # same order as async_setup_entry: brokers first, then the quota requests that go through them
    client.start()
    await client.quota_all(None)
    t0 = time.time()
    while time.time() - t0 < seconds:
        await asyncio.sleep(5)
    client.stop()

    for sn, device in client.devices.items():
        kind = "PACK" if not isinstance(device, StreamAC5000) else device.device_info.device_type
        print(f"\n== {short(sn)} {kind} status={device.status_tracker.status.label}")
        for key in KEYS:
            if key in device.data.params:
                value = device.data.params[key]
                print(f"   {key:45} {short(value) if key == 'masterSn' else value}")
    for pack in packs:
        print("\npack state:", pack.pack_state(), "| master:", short(pack.master_sn()), "| writes go to:", short(pack.target_sn()))


asyncio.run(main())
