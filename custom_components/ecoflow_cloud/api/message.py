import json
import random
from abc import ABC, abstractmethod
from typing import override

from paho.mqtt.client import PayloadType


class Message(ABC):
    @abstractmethod
    def to_mqtt_payload(self) -> PayloadType:
        raise NotImplementedError()

    @staticmethod
    def gen_seq() -> int:
        return 999900000 + random.randint(10000, 99999)


JSONType = None | bool | int | float | str | list["JSONType"] | dict[str, "JSONType"]
JSONDict = dict[str, JSONType]


class PrivateAPIMessageProtocol(Message):
    def to_dict(self) -> dict:
        raise NotImplementedError()


class JSONMessage(Message):
    def __init__(self, data: JSONDict) -> None:
        super().__init__()
        self.data = data

    @staticmethod
    def prepare_payload(command: JSONDict) -> JSONDict:
        payload: JSONDict = {
            "from": "HomeAssistant",
            "id": str(Message.gen_seq()),
            "version": "1.0",
        }
        payload.update(command)
        return payload

    @override
    def to_mqtt_payload(self) -> PayloadType:
        return json.dumps(JSONMessage.prepare_payload(self.data))


class OpenAPICommand(Message):
    """A set command for the open-API broker, sent by an app-API entry that also holds developer keys.

    ``target_sn`` names the unit that receives it, which may differ from the entity's device (a pack).
    """

    def __init__(self, target_sn: str, envelope: JSONDict, params: JSONDict) -> None:
        super().__init__()
        self.target_sn = target_sn
        self.envelope = envelope
        self.params = params

    @override
    def to_mqtt_payload(self) -> PayloadType:
        return json.dumps(
            {**self.envelope, "params": self.params, "id": Message.gen_seq(), "version": "1.0", "sn": self.target_sn}
        )
