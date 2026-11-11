#!/usr/bin/env python3
"""Record raw EcoFlow MQTT traffic (app/private and open/public brokers) to a JSONL file.

usage: uv run python scripts/ef_capture.py <out.jsonl> [seconds=120] [--sn PREFIX ...]
Credentials come from ~/.config/ecoflow/credentials.json
(account.email/password, developer_api.access_key/secret_key, region eu|us).
Each line: {"t": epoch, "api": "private"|"public", "topic": ..., "hex": payload}.
Serials are kept in the file, so keep captures out of git.
"""

import argparse
import base64
import hashlib
import hmac
import json
import os
import random
import ssl
import threading
import time
import urllib.parse
import urllib.request
import uuid

import paho.mqtt.client as mqtt

CRED = os.path.expanduser("~/.config/ecoflow/credentials.json")


def _http(url: str, headers: dict, data: bytes | None = None, method: str = "GET") -> dict:
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    body = json.load(urllib.request.urlopen(req, timeout=20))
    if str(body.get("code")) != "0":
        raise RuntimeError(f"{url}: {body.get('code')} {body.get('message')}")
    return body["data"]


def private_session(host: str, email: str, password: str) -> tuple[dict, str, str]:
    login = _http(
        f"https://{host}/auth/login",
        {"lang": "en_US", "content-type": "application/json"},
        json.dumps(
            {
                "email": email,
                "password": base64.b64encode(password.encode()).decode(),
                "scene": "IOT_APP",
                "userType": "ECOFLOW",
            }
        ).encode(),
        "POST",
    )
    token, user_id = login["token"], str(login["user"]["userId"])
    auth = {"lang": "en_US", "authorization": f"Bearer {token}"}
    cert = _http(f"https://{host}/iot-auth/app/certification?userId={user_id}", auth)
    return cert, user_id, token


def public_call(host: str, ak: str, sk: str, path: str, params: dict | None = None) -> dict:
    nonce, ts = str(random.randint(100000, 999999)), str(int(time.time() * 1000))
    query = "&".join(f"{k}={v}" for k, v in sorted((params or {}).items()))
    base = f"accessKey={ak}&nonce={nonce}&timestamp={ts}"
    sign = hmac.new(sk.encode(), ((query + "&") if query else "").encode() + base.encode(), hashlib.sha256)
    headers = {"accessKey": ak, "nonce": nonce, "timestamp": ts, "sign": sign.hexdigest()}
    return _http(f"https://{host}/iot-open/sign{path}" + (f"?{query}" if query else ""), headers)


def connect(cert: dict, client_id: str, topics: list[str], api: str, out, lock: threading.Lock) -> mqtt.Client:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
    client.username_pw_set(cert["certificateAccount"], cert["certificatePassword"])
    client.tls_set(cert_reqs=ssl.CERT_REQUIRED)

    def on_connect(c, _u, _f, rc, _p):
        print(f"[{api}] connected rc={rc}, {len(topics)} topics")
        for topic in topics:
            c.subscribe(topic, qos=1)

    def on_message(_c, _u, msg):
        with lock:
            out.write(json.dumps({"t": time.time(), "api": api, "topic": msg.topic, "hex": msg.payload.hex()}) + "\n")
            out.flush()

    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(cert["url"], int(cert["port"]), keepalive=30)
    client.loop_start()
    return client


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("seconds", nargs="?", type=int, default=120)
    ap.add_argument("--sn", nargs="*", default=["ES21", "ES22"], help="serial prefixes to follow")
    args = ap.parse_args()

    cred = json.load(open(CRED))
    host = "api-e.ecoflow.com" if cred.get("region", "eu") == "eu" else "api.ecoflow.com"
    ak, sk = cred["developer_api"]["access_key"].strip(), cred["developer_api"]["secret_key"].strip()

    devices = [d["sn"] for d in public_call(host, ak, sk, "/device/list") if d["sn"][:4] in args.sn]
    print("following", [sn[:4] + "…" + sn[-4:] for sn in devices])

    lock = threading.Lock()
    clients = []
    with open(args.out, "a") as out:
        cert, user_id, _ = private_session(host, cred["account"]["email"], cred["account"]["password"])
        topics = [f"/app/device/property/{sn}" for sn in devices]
        topics += [f"/app/{user_id}/{sn}/thing/property/{k}" for sn in devices for k in ("get_reply", "set_reply")]
        clients.append(
            connect(cert, f"ANDROID_{uuid.uuid4().hex.upper()}_{user_id}", topics, "private", out, lock)
        )

        pcert = public_call(host, ak, sk, "/certification")
        acct = pcert["certificateAccount"]
        topics = [f"/open/{acct}/{sn}/{k}" for sn in devices for k in ("quota", "status", "set_reply")]
        clients.append(connect(pcert, f"Hassio-{acct}-capture", topics, "public", out, lock))

        time.sleep(args.seconds)
        for client in clients:
            client.disconnect()
            client.loop_stop()


if __name__ == "__main__":
    main()
