from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class StreamAC5000BatteryStatus(_message.Message):
    __slots__ = ("cmsMaxChgSoc", "soc", "bmsChgRemTime", "bmsDsgRemTime", "f32ShowSoc", "cmsMinDsgSoc")
    CMSMAXCHGSOC_FIELD_NUMBER: _ClassVar[int]
    SOC_FIELD_NUMBER: _ClassVar[int]
    BMSCHGREMTIME_FIELD_NUMBER: _ClassVar[int]
    BMSDSGREMTIME_FIELD_NUMBER: _ClassVar[int]
    F32SHOWSOC_FIELD_NUMBER: _ClassVar[int]
    CMSMINDSGSOC_FIELD_NUMBER: _ClassVar[int]
    cmsMaxChgSoc: int
    soc: int
    bmsChgRemTime: int
    bmsDsgRemTime: int
    f32ShowSoc: float
    cmsMinDsgSoc: int
    def __init__(self, cmsMaxChgSoc: _Optional[int] = ..., soc: _Optional[int] = ..., bmsChgRemTime: _Optional[int] = ..., bmsDsgRemTime: _Optional[int] = ..., f32ShowSoc: _Optional[float] = ..., cmsMinDsgSoc: _Optional[int] = ...) -> None: ...

class StreamAC5000StatusPack(_message.Message):
    __slots__ = ("battery",)
    BATTERY_FIELD_NUMBER: _ClassVar[int]
    battery: StreamAC5000BatteryStatus
    def __init__(self, battery: _Optional[_Union[StreamAC5000BatteryStatus, _Mapping]] = ...) -> None: ...

class StreamAC5000Meter(_message.Message):
    __slots__ = ("meterSn", "meterPhaseAPower", "meterPhaseBPower", "meterPhaseCPower", "meterPhaseAVol", "meterPhaseBVol", "meterPhaseCVol", "meterFreq", "meterTotalPower")
    METERSN_FIELD_NUMBER: _ClassVar[int]
    METERPHASEAPOWER_FIELD_NUMBER: _ClassVar[int]
    METERPHASEBPOWER_FIELD_NUMBER: _ClassVar[int]
    METERPHASECPOWER_FIELD_NUMBER: _ClassVar[int]
    METERPHASEAVOL_FIELD_NUMBER: _ClassVar[int]
    METERPHASEBVOL_FIELD_NUMBER: _ClassVar[int]
    METERPHASECVOL_FIELD_NUMBER: _ClassVar[int]
    METERFREQ_FIELD_NUMBER: _ClassVar[int]
    METERTOTALPOWER_FIELD_NUMBER: _ClassVar[int]
    meterSn: str
    meterPhaseAPower: float
    meterPhaseBPower: float
    meterPhaseCPower: float
    meterPhaseAVol: float
    meterPhaseBVol: float
    meterPhaseCVol: float
    meterFreq: int
    meterTotalPower: float
    def __init__(self, meterSn: _Optional[str] = ..., meterPhaseAPower: _Optional[float] = ..., meterPhaseBPower: _Optional[float] = ..., meterPhaseCPower: _Optional[float] = ..., meterPhaseAVol: _Optional[float] = ..., meterPhaseBVol: _Optional[float] = ..., meterPhaseCVol: _Optional[float] = ..., meterFreq: _Optional[int] = ..., meterTotalPower: _Optional[float] = ...) -> None: ...

class StreamAC5000SysConfig(_message.Message):
    __slots__ = ("maxChgPow", "maxDsgPow", "cmsBattFullEnergy", "f32ShowSoc", "cmsMaxChgSoc", "cmsMinDsgSoc", "feedGridModePowLimit", "feedGridModePowMax")
    MAXCHGPOW_FIELD_NUMBER: _ClassVar[int]
    MAXDSGPOW_FIELD_NUMBER: _ClassVar[int]
    CMSBATTFULLENERGY_FIELD_NUMBER: _ClassVar[int]
    F32SHOWSOC_FIELD_NUMBER: _ClassVar[int]
    CMSMAXCHGSOC_FIELD_NUMBER: _ClassVar[int]
    CMSMINDSGSOC_FIELD_NUMBER: _ClassVar[int]
    FEEDGRIDMODEPOWLIMIT_FIELD_NUMBER: _ClassVar[int]
    FEEDGRIDMODEPOWMAX_FIELD_NUMBER: _ClassVar[int]
    maxChgPow: float
    maxDsgPow: float
    cmsBattFullEnergy: float
    f32ShowSoc: float
    cmsMaxChgSoc: float
    cmsMinDsgSoc: float
    feedGridModePowLimit: float
    feedGridModePowMax: float
    def __init__(self, maxChgPow: _Optional[float] = ..., maxDsgPow: _Optional[float] = ..., cmsBattFullEnergy: _Optional[float] = ..., f32ShowSoc: _Optional[float] = ..., cmsMaxChgSoc: _Optional[float] = ..., cmsMinDsgSoc: _Optional[float] = ..., feedGridModePowLimit: _Optional[float] = ..., feedGridModePowMax: _Optional[float] = ...) -> None: ...

class StreamAC5000Bms(_message.Message):
    __slots__ = ("soc", "cmsMaxChgSoc", "power", "cmsBattFullEnergy", "bmsDsgRemTime", "bmsChgRemTime", "minCellVol", "maxCellVol", "bmsSn")
    SOC_FIELD_NUMBER: _ClassVar[int]
    CMSMAXCHGSOC_FIELD_NUMBER: _ClassVar[int]
    POWER_FIELD_NUMBER: _ClassVar[int]
    CMSBATTFULLENERGY_FIELD_NUMBER: _ClassVar[int]
    BMSDSGREMTIME_FIELD_NUMBER: _ClassVar[int]
    BMSCHGREMTIME_FIELD_NUMBER: _ClassVar[int]
    MINCELLVOL_FIELD_NUMBER: _ClassVar[int]
    MAXCELLVOL_FIELD_NUMBER: _ClassVar[int]
    BMSSN_FIELD_NUMBER: _ClassVar[int]
    soc: int
    cmsMaxChgSoc: int
    power: int
    cmsBattFullEnergy: int
    bmsDsgRemTime: int
    bmsChgRemTime: int
    minCellVol: int
    maxCellVol: int
    bmsSn: str
    def __init__(self, soc: _Optional[int] = ..., cmsMaxChgSoc: _Optional[int] = ..., power: _Optional[int] = ..., cmsBattFullEnergy: _Optional[int] = ..., bmsDsgRemTime: _Optional[int] = ..., bmsChgRemTime: _Optional[int] = ..., minCellVol: _Optional[int] = ..., maxCellVol: _Optional[int] = ..., bmsSn: _Optional[str] = ...) -> None: ...

class StreamAC5000BmsPack(_message.Message):
    __slots__ = ("bms",)
    BMS_FIELD_NUMBER: _ClassVar[int]
    bms: StreamAC5000Bms
    def __init__(self, bms: _Optional[_Union[StreamAC5000Bms, _Mapping]] = ...) -> None: ...

class StreamAC5000Cms(_message.Message):
    __slots__ = ("soc", "power", "cmsBattFullEnergy", "remainCap", "dsgRemainTime", "remainTime")
    SOC_FIELD_NUMBER: _ClassVar[int]
    POWER_FIELD_NUMBER: _ClassVar[int]
    CMSBATTFULLENERGY_FIELD_NUMBER: _ClassVar[int]
    REMAINCAP_FIELD_NUMBER: _ClassVar[int]
    DSGREMAINTIME_FIELD_NUMBER: _ClassVar[int]
    REMAINTIME_FIELD_NUMBER: _ClassVar[int]
    soc: int
    power: int
    cmsBattFullEnergy: int
    remainCap: int
    dsgRemainTime: int
    remainTime: int
    def __init__(self, soc: _Optional[int] = ..., power: _Optional[int] = ..., cmsBattFullEnergy: _Optional[int] = ..., remainCap: _Optional[int] = ..., dsgRemainTime: _Optional[int] = ..., remainTime: _Optional[int] = ...) -> None: ...

class StreamAC5000EnergyStream(_message.Message):
    __slots__ = ("loadPwr", "gridPwr", "pvPwr", "bpPwr", "bpSoc", "onGridPwr", "backupPwr")
    LOADPWR_FIELD_NUMBER: _ClassVar[int]
    GRIDPWR_FIELD_NUMBER: _ClassVar[int]
    PVPWR_FIELD_NUMBER: _ClassVar[int]
    BPPWR_FIELD_NUMBER: _ClassVar[int]
    BPSOC_FIELD_NUMBER: _ClassVar[int]
    ONGRIDPWR_FIELD_NUMBER: _ClassVar[int]
    BACKUPPWR_FIELD_NUMBER: _ClassVar[int]
    loadPwr: int
    gridPwr: int
    pvPwr: int
    bpPwr: int
    bpSoc: int
    onGridPwr: int
    backupPwr: int
    def __init__(self, loadPwr: _Optional[int] = ..., gridPwr: _Optional[int] = ..., pvPwr: _Optional[int] = ..., bpPwr: _Optional[int] = ..., bpSoc: _Optional[int] = ..., onGridPwr: _Optional[int] = ..., backupPwr: _Optional[int] = ...) -> None: ...

class StreamAC5000SystemConfig(_message.Message):
    __slots__ = ("systemGroupId", "distributedDeviceRole", "seriesDeviceId", "systemDevCnt")
    SYSTEMGROUPID_FIELD_NUMBER: _ClassVar[int]
    DISTRIBUTEDDEVICEROLE_FIELD_NUMBER: _ClassVar[int]
    SERIESDEVICEID_FIELD_NUMBER: _ClassVar[int]
    SYSTEMDEVCNT_FIELD_NUMBER: _ClassVar[int]
    systemGroupId: int
    distributedDeviceRole: int
    seriesDeviceId: int
    systemDevCnt: int
    def __init__(self, systemGroupId: _Optional[int] = ..., distributedDeviceRole: _Optional[int] = ..., seriesDeviceId: _Optional[int] = ..., systemDevCnt: _Optional[int] = ...) -> None: ...

class StreamAC5000BackupConfig(_message.Message):
    __slots__ = ("backupSocOnOff", "backupSoc")
    BACKUPSOCONOFF_FIELD_NUMBER: _ClassVar[int]
    BACKUPSOC_FIELD_NUMBER: _ClassVar[int]
    backupSocOnOff: bool
    backupSoc: int
    def __init__(self, backupSocOnOff: _Optional[bool] = ..., backupSoc: _Optional[int] = ...) -> None: ...

class StreamAC5000DevicePower(_message.Message):
    __slots__ = ("sn", "soc", "pvSelfPwr", "gridPortPower", "onGridState", "invPwr", "onGridPwr", "backupPwr", "pv1Pwr", "pv2Pwr", "pv3Pwr", "pv4Pwr")
    SN_FIELD_NUMBER: _ClassVar[int]
    SOC_FIELD_NUMBER: _ClassVar[int]
    PVSELFPWR_FIELD_NUMBER: _ClassVar[int]
    GRIDPORTPOWER_FIELD_NUMBER: _ClassVar[int]
    ONGRIDSTATE_FIELD_NUMBER: _ClassVar[int]
    INVPWR_FIELD_NUMBER: _ClassVar[int]
    ONGRIDPWR_FIELD_NUMBER: _ClassVar[int]
    BACKUPPWR_FIELD_NUMBER: _ClassVar[int]
    PV1PWR_FIELD_NUMBER: _ClassVar[int]
    PV2PWR_FIELD_NUMBER: _ClassVar[int]
    PV3PWR_FIELD_NUMBER: _ClassVar[int]
    PV4PWR_FIELD_NUMBER: _ClassVar[int]
    sn: str
    soc: float
    pvSelfPwr: float
    gridPortPower: float
    onGridState: int
    invPwr: float
    onGridPwr: float
    backupPwr: float
    pv1Pwr: float
    pv2Pwr: float
    pv3Pwr: float
    pv4Pwr: float
    def __init__(self, sn: _Optional[str] = ..., soc: _Optional[float] = ..., pvSelfPwr: _Optional[float] = ..., gridPortPower: _Optional[float] = ..., onGridState: _Optional[int] = ..., invPwr: _Optional[float] = ..., onGridPwr: _Optional[float] = ..., backupPwr: _Optional[float] = ..., pv1Pwr: _Optional[float] = ..., pv2Pwr: _Optional[float] = ..., pv3Pwr: _Optional[float] = ..., pv4Pwr: _Optional[float] = ...) -> None: ...

class StreamAC5000PowerPack(_message.Message):
    __slots__ = ("power",)
    POWER_FIELD_NUMBER: _ClassVar[int]
    power: _containers.RepeatedCompositeFieldContainer[StreamAC5000DevicePower]
    def __init__(self, power: _Optional[_Iterable[_Union[StreamAC5000DevicePower, _Mapping]]] = ...) -> None: ...

class StreamAC5000DeviceStat(_message.Message):
    __slots__ = ("sn", "soc", "heatState", "bpPower")
    SN_FIELD_NUMBER: _ClassVar[int]
    SOC_FIELD_NUMBER: _ClassVar[int]
    HEATSTATE_FIELD_NUMBER: _ClassVar[int]
    BPPOWER_FIELD_NUMBER: _ClassVar[int]
    sn: str
    soc: int
    heatState: int
    bpPower: int
    def __init__(self, sn: _Optional[str] = ..., soc: _Optional[int] = ..., heatState: _Optional[int] = ..., bpPower: _Optional[int] = ...) -> None: ...

class StreamAC5000StatPack(_message.Message):
    __slots__ = ("stat",)
    STAT_FIELD_NUMBER: _ClassVar[int]
    stat: _containers.RepeatedCompositeFieldContainer[StreamAC5000DeviceStat]
    def __init__(self, stat: _Optional[_Iterable[_Union[StreamAC5000DeviceStat, _Mapping]]] = ...) -> None: ...

class StreamAC5000Runtime(_message.Message):
    __slots__ = ("deviceCfg", "powerLimits", "acOut", "workMode", "meter", "sysConfig", "bmsPack", "cms", "powerPack", "statPack", "sysEnergyStreamReport", "systemConfig", "bpBackupConfig")
    DEVICECFG_FIELD_NUMBER: _ClassVar[int]
    POWERLIMITS_FIELD_NUMBER: _ClassVar[int]
    ACOUT_FIELD_NUMBER: _ClassVar[int]
    WORKMODE_FIELD_NUMBER: _ClassVar[int]
    METER_FIELD_NUMBER: _ClassVar[int]
    SYSCONFIG_FIELD_NUMBER: _ClassVar[int]
    BMSPACK_FIELD_NUMBER: _ClassVar[int]
    CMS_FIELD_NUMBER: _ClassVar[int]
    POWERPACK_FIELD_NUMBER: _ClassVar[int]
    STATPACK_FIELD_NUMBER: _ClassVar[int]
    SYSENERGYSTREAMREPORT_FIELD_NUMBER: _ClassVar[int]
    SYSTEMCONFIG_FIELD_NUMBER: _ClassVar[int]
    BPBACKUPCONFIG_FIELD_NUMBER: _ClassVar[int]
    deviceCfg: StreamAC5000SetDeviceCfg
    powerLimits: StreamAC5000SetPowerLimits
    acOut: StreamAC5000SetAcOut
    workMode: int
    meter: StreamAC5000Meter
    sysConfig: StreamAC5000SysConfig
    bmsPack: StreamAC5000BmsPack
    cms: StreamAC5000Cms
    powerPack: StreamAC5000PowerPack
    statPack: StreamAC5000StatPack
    sysEnergyStreamReport: StreamAC5000EnergyStream
    systemConfig: StreamAC5000SystemConfig
    bpBackupConfig: StreamAC5000BackupConfig
    def __init__(self, deviceCfg: _Optional[_Union[StreamAC5000SetDeviceCfg, _Mapping]] = ..., powerLimits: _Optional[_Union[StreamAC5000SetPowerLimits, _Mapping]] = ..., acOut: _Optional[_Union[StreamAC5000SetAcOut, _Mapping]] = ..., workMode: _Optional[int] = ..., meter: _Optional[_Union[StreamAC5000Meter, _Mapping]] = ..., sysConfig: _Optional[_Union[StreamAC5000SysConfig, _Mapping]] = ..., bmsPack: _Optional[_Union[StreamAC5000BmsPack, _Mapping]] = ..., cms: _Optional[_Union[StreamAC5000Cms, _Mapping]] = ..., powerPack: _Optional[_Union[StreamAC5000PowerPack, _Mapping]] = ..., statPack: _Optional[_Union[StreamAC5000StatPack, _Mapping]] = ..., sysEnergyStreamReport: _Optional[_Union[StreamAC5000EnergyStream, _Mapping]] = ..., systemConfig: _Optional[_Union[StreamAC5000SystemConfig, _Mapping]] = ..., bpBackupConfig: _Optional[_Union[StreamAC5000BackupConfig, _Mapping]] = ...) -> None: ...

class StreamAC5000Pack(_message.Message):
    __slots__ = ("f32ShowSoc", "version", "bmsSn", "realSoh", "cycleSoh", "calendarSoh", "accuChgCap", "accuDsgCap", "accuChgEnergy", "accuDsgEnergy", "inverterSn")
    F32SHOWSOC_FIELD_NUMBER: _ClassVar[int]
    VERSION_FIELD_NUMBER: _ClassVar[int]
    BMSSN_FIELD_NUMBER: _ClassVar[int]
    REALSOH_FIELD_NUMBER: _ClassVar[int]
    CYCLESOH_FIELD_NUMBER: _ClassVar[int]
    CALENDARSOH_FIELD_NUMBER: _ClassVar[int]
    ACCUCHGCAP_FIELD_NUMBER: _ClassVar[int]
    ACCUDSGCAP_FIELD_NUMBER: _ClassVar[int]
    ACCUCHGENERGY_FIELD_NUMBER: _ClassVar[int]
    ACCUDSGENERGY_FIELD_NUMBER: _ClassVar[int]
    INVERTERSN_FIELD_NUMBER: _ClassVar[int]
    f32ShowSoc: float
    version: str
    bmsSn: str
    realSoh: float
    cycleSoh: float
    calendarSoh: float
    accuChgCap: int
    accuDsgCap: int
    accuChgEnergy: int
    accuDsgEnergy: int
    inverterSn: str
    def __init__(self, f32ShowSoc: _Optional[float] = ..., version: _Optional[str] = ..., bmsSn: _Optional[str] = ..., realSoh: _Optional[float] = ..., cycleSoh: _Optional[float] = ..., calendarSoh: _Optional[float] = ..., accuChgCap: _Optional[int] = ..., accuDsgCap: _Optional[int] = ..., accuChgEnergy: _Optional[int] = ..., accuDsgEnergy: _Optional[int] = ..., inverterSn: _Optional[str] = ...) -> None: ...

class StreamAC5000SetSocLimits(_message.Message):
    __slots__ = ("cmsMaxChgSoc", "cmsMinDsgSoc")
    CMSMAXCHGSOC_FIELD_NUMBER: _ClassVar[int]
    CMSMINDSGSOC_FIELD_NUMBER: _ClassVar[int]
    cmsMaxChgSoc: int
    cmsMinDsgSoc: int
    def __init__(self, cmsMaxChgSoc: _Optional[int] = ..., cmsMinDsgSoc: _Optional[int] = ...) -> None: ...

class StreamAC5000SetPowerLimits(_message.Message):
    __slots__ = ("feedGridModePowLimit", "chgPowLimit", "feedToGridLimitOnOff", "outLimitField4", "outLimitMax")
    FEEDGRIDMODEPOWLIMIT_FIELD_NUMBER: _ClassVar[int]
    CHGPOWLIMIT_FIELD_NUMBER: _ClassVar[int]
    FEEDTOGRIDLIMITONOFF_FIELD_NUMBER: _ClassVar[int]
    OUTLIMITFIELD4_FIELD_NUMBER: _ClassVar[int]
    OUTLIMITMAX_FIELD_NUMBER: _ClassVar[int]
    feedGridModePowLimit: int
    chgPowLimit: int
    feedToGridLimitOnOff: bool
    outLimitField4: int
    outLimitMax: int
    def __init__(self, feedGridModePowLimit: _Optional[int] = ..., chgPowLimit: _Optional[int] = ..., feedToGridLimitOnOff: _Optional[bool] = ..., outLimitField4: _Optional[int] = ..., outLimitMax: _Optional[int] = ...) -> None: ...

class StreamAC5000SetAcOut(_message.Message):
    __slots__ = ("enabled",)
    ENABLED_FIELD_NUMBER: _ClassVar[int]
    enabled: int
    def __init__(self, enabled: _Optional[int] = ...) -> None: ...

class StreamAC5000SetDeviceCfg(_message.Message):
    __slots__ = ("xboostEnabled", "upsEnabled")
    XBOOSTENABLED_FIELD_NUMBER: _ClassVar[int]
    UPSENABLED_FIELD_NUMBER: _ClassVar[int]
    xboostEnabled: int
    upsEnabled: int
    def __init__(self, xboostEnabled: _Optional[int] = ..., upsEnabled: _Optional[int] = ...) -> None: ...

class StreamAC5000SetCommand(_message.Message):
    __slots__ = ("propertyId", "powerLimits", "acOut", "deviceCfg", "workMode", "socLimits", "bpBackupConfig")
    PROPERTYID_FIELD_NUMBER: _ClassVar[int]
    POWERLIMITS_FIELD_NUMBER: _ClassVar[int]
    ACOUT_FIELD_NUMBER: _ClassVar[int]
    DEVICECFG_FIELD_NUMBER: _ClassVar[int]
    WORKMODE_FIELD_NUMBER: _ClassVar[int]
    SOCLIMITS_FIELD_NUMBER: _ClassVar[int]
    BPBACKUPCONFIG_FIELD_NUMBER: _ClassVar[int]
    propertyId: int
    powerLimits: StreamAC5000SetPowerLimits
    acOut: StreamAC5000SetAcOut
    deviceCfg: StreamAC5000SetDeviceCfg
    workMode: int
    socLimits: StreamAC5000SetSocLimits
    bpBackupConfig: StreamAC5000BackupConfig
    def __init__(self, propertyId: _Optional[int] = ..., powerLimits: _Optional[_Union[StreamAC5000SetPowerLimits, _Mapping]] = ..., acOut: _Optional[_Union[StreamAC5000SetAcOut, _Mapping]] = ..., deviceCfg: _Optional[_Union[StreamAC5000SetDeviceCfg, _Mapping]] = ..., workMode: _Optional[int] = ..., socLimits: _Optional[_Union[StreamAC5000SetSocLimits, _Mapping]] = ..., bpBackupConfig: _Optional[_Union[StreamAC5000BackupConfig, _Mapping]] = ...) -> None: ...

class StreamAC5000SetHeader(_message.Message):
    __slots__ = ("pdata", "src", "dest", "d_src", "d_dest", "check_type", "cmd_func", "cmd_id", "data_len", "need_ack", "seq", "version", "payload_ver", "from_", "device_sn", "device_sn_2", "device_sn_3")
    PDATA_FIELD_NUMBER: _ClassVar[int]
    SRC_FIELD_NUMBER: _ClassVar[int]
    DEST_FIELD_NUMBER: _ClassVar[int]
    D_SRC_FIELD_NUMBER: _ClassVar[int]
    D_DEST_FIELD_NUMBER: _ClassVar[int]
    CHECK_TYPE_FIELD_NUMBER: _ClassVar[int]
    CMD_FUNC_FIELD_NUMBER: _ClassVar[int]
    CMD_ID_FIELD_NUMBER: _ClassVar[int]
    DATA_LEN_FIELD_NUMBER: _ClassVar[int]
    NEED_ACK_FIELD_NUMBER: _ClassVar[int]
    SEQ_FIELD_NUMBER: _ClassVar[int]
    VERSION_FIELD_NUMBER: _ClassVar[int]
    PAYLOAD_VER_FIELD_NUMBER: _ClassVar[int]
    FROM__FIELD_NUMBER: _ClassVar[int]
    DEVICE_SN_FIELD_NUMBER: _ClassVar[int]
    DEVICE_SN_2_FIELD_NUMBER: _ClassVar[int]
    DEVICE_SN_3_FIELD_NUMBER: _ClassVar[int]
    pdata: bytes
    src: int
    dest: int
    d_src: int
    d_dest: int
    check_type: int
    cmd_func: int
    cmd_id: int
    data_len: int
    need_ack: int
    seq: int
    version: int
    payload_ver: int
    from_: str
    device_sn: str
    device_sn_2: str
    device_sn_3: str
    def __init__(self, pdata: _Optional[bytes] = ..., src: _Optional[int] = ..., dest: _Optional[int] = ..., d_src: _Optional[int] = ..., d_dest: _Optional[int] = ..., check_type: _Optional[int] = ..., cmd_func: _Optional[int] = ..., cmd_id: _Optional[int] = ..., data_len: _Optional[int] = ..., need_ack: _Optional[int] = ..., seq: _Optional[int] = ..., version: _Optional[int] = ..., payload_ver: _Optional[int] = ..., from_: _Optional[str] = ..., device_sn: _Optional[str] = ..., device_sn_2: _Optional[str] = ..., device_sn_3: _Optional[str] = ...) -> None: ...

class StreamAC5000SendCommandMsg(_message.Message):
    __slots__ = ("msg",)
    MSG_FIELD_NUMBER: _ClassVar[int]
    msg: StreamAC5000SetHeader
    def __init__(self, msg: _Optional[_Union[StreamAC5000SetHeader, _Mapping]] = ...) -> None: ...
