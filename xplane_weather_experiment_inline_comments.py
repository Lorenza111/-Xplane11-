#!/usr/bin/env python3
"""
Batch weather experiment runner for X-Plane.

This script reads case definitions from a CSV file, applies writable weather
datarefs through a backend, samples observed datarefs, and writes results to a
new CSV file for later analysis.

Out of the box it runs in `--dry-run` mode with a mock backend so you can test
the workflow before wiring it to a real X-Plane UDP client.
"""

from __future__ import annotations  # （延迟解析类型注解）

import argparse  # （导入 argparse 模块）
import csv  # （导入 csv 模块）
import math  # （导入 math 模块）
import socket  # （导入 socket 模块）
import statistics  # （导入 statistics 模块）
import struct  # （导入 struct 模块）
import time  # （导入 time 模块）
from dataclasses import dataclass  # （从模块导入所需类或函数）
from pathlib import Path  # （从模块导入所需类或函数）
from typing import Dict, Iterable, List, Sequence  # （从模块导入所需类或函数）


OBSERVED_VERTICAL_WIND = "sim/weather/wind_now_y_msc"  # （定义 OBSERVED_VERTICAL_WIND 常量）
POSITION_LATITUDE = "sim/flightmodel/position/latitude"  # （定义 POSITION_LATITUDE 常量）
POSITION_LONGITUDE = "sim/flightmodel/position/longitude"  # （定义 POSITION_LONGITUDE 常量）
POSITION_LOCAL_X = "sim/flightmodel/position/local_x"  # （定义 POSITION_LOCAL_X 常量）
POSITION_LOCAL_Z = "sim/flightmodel/position/local_z"  # （定义 POSITION_LOCAL_Z 常量）
OBSERVED_DATAREFS = {  # （定义 OBSERVED_DATAREFS 常量）
    "wind_now_y_msc": "sim/weather/wind_now_y_msc",  # （多行结构中的一项）
    "indicated_airspeed": "sim/flightmodel/position/indicated_airspeed",  # （多行结构中的一项）
    "vertical_speed_fpm": "sim/flightmodel/position/vh_ind_fpm",  # （多行结构中的一项）
    "local_y": "sim/flightmodel/position/local_y",  # （多行结构中的一项）
    "latitude_deg": POSITION_LATITUDE,  # （多行结构中的一项）
    "longitude_deg": POSITION_LONGITUDE,  # （多行结构中的一项）
    "local_x": POSITION_LOCAL_X,  # （多行结构中的一项）
    "local_z": POSITION_LOCAL_Z,  # （多行结构中的一项）
    "heading_psi_deg": "sim/flightmodel/position/psi",  # （多行结构中的一项）
    "pitch_theta_deg": "sim/flightmodel/position/theta",  # （多行结构中的一项）
    "roll_phi_deg": "sim/flightmodel/position/phi",  # （多行结构中的一项）
    # For linked controls, X-Plane's official guidance is to use the total_* datarefs.
    "control_pitch_ratio": "sim/cockpit2/controls/total_pitch_ratio",  # （多行结构中的一项）
    "control_roll_ratio": "sim/cockpit2/controls/total_roll_ratio",  # （多行结构中的一项）
    "control_heading_ratio": "sim/cockpit2/controls/total_heading_ratio",  # （多行结构中的一项）
    # C172 is single-engine, so engine 0 throttle is the relevant control input.
    "throttle_ratio_0": "sim/cockpit2/engine/actuators/throttle_ratio[0]",  # （多行结构中的一项）
    "autopilot_state": "sim/cockpit/autopilot/autopilot_state",  # （多行结构中的一项）
}  # （结束多行结构）

# Fill these in with the actual writable DataRef names you confirmed in
# DataRefEditor. The wind-layer items shown below are the ones you already
# surfaced in your screenshots and are good first candidates.
CONTROL_DATAREFS = {  # （定义 CONTROL_DATAREFS 常量）
    "wind_altitude_msl_m_0": "sim/weather/wind_altitude_msl_m[0]",  # （多行结构中的一项）
    "wind_altitude_msl_m_1": "sim/weather/wind_altitude_msl_m[1]",  # （多行结构中的一项）
    "wind_speed_kt_0": "sim/weather/wind_speed_kt[0]",  # （多行结构中的一项）
    "wind_speed_kt_1": "sim/weather/wind_speed_kt[1]",  # （多行结构中的一项）
    "wind_direction_degt_0": "sim/weather/wind_direction_degt[0]",  # （多行结构中的一项）
    "wind_direction_degt_1": "sim/weather/wind_direction_degt[1]",  # （多行结构中的一项）
    "wind_turbulence_percent_0": "sim/weather/wind_turbulence_percent[0]",  # （多行结构中的一项）
    "shear_speed_kt_0": "sim/weather/shear_speed_kt[0]",  # （多行结构中的一项）
    "shear_direction_degt_0": "sim/weather/shear_direction_degt[0]",  # （多行结构中的一项）
    "turbulence_0": "sim/weather/turbulence[0]",  # （多行结构中的一项）
    "thermal_percent": "sim/weather/thermal_percent",  # （多行结构中的一项）
    "thermal_rate_ms": "sim/weather/thermal_rate_ms",  # （多行结构中的一项）
    "thermal_altitude_msl_m": "sim/weather/thermal_altitude_msl_m",  # （多行结构中的一项）
}  # （结束多行结构）


@dataclass  # （声明数据类）
class CaseConfig:  # （定义 CaseConfig 类）
    case_id: str  # （执行具体处理逻辑）
    note: str  # （执行具体处理逻辑）
    settle_seconds: float  # （执行具体处理逻辑）
    sample_seconds: float  # （执行具体处理逻辑）
    sample_hz: float  # （执行具体处理逻辑）
    values: Dict[str, float]  # （执行具体处理逻辑）


@dataclass  # （声明数据类）
class PhaseConfig:  # （定义 PhaseConfig 类）
    scenario_id: str  # （执行具体处理逻辑）
    phase_id: str  # （执行具体处理逻辑）
    note: str  # （执行具体处理逻辑）
    duration_seconds: float  # （执行具体处理逻辑）
    sample_hz: float  # （执行具体处理逻辑）
    distance_start_m: float | None  # （执行具体处理逻辑）
    distance_end_m: float | None  # （执行具体处理逻辑）
    dme_start_nm: float | None  # （执行具体处理逻辑）
    dme_end_nm: float | None  # （执行具体处理逻辑）
    values: Dict[str, float]  # （执行具体处理逻辑）


class BackendError(RuntimeError):  # （定义 BackendError 类）
    pass  # （空操作占位）


class XPlaneBackend:  # （定义 XPlaneBackend 类）
    """Interface for a real X-Plane UDP backend."""  # （执行具体处理逻辑）

    def set_dataref(self, dataref: str, value: float) -> None:  # （定义 set_dataref 函数）
        raise NotImplementedError  # （抛出异常提示错误）

    def get_dataref(self, dataref: str) -> float:  # （定义 get_dataref 函数）
        raise NotImplementedError  # （抛出异常提示错误）

    def close(self) -> None:  # （定义 close 函数）
        """Optional cleanup hook."""  # （执行具体处理逻辑）


class MockBackend(XPlaneBackend):  # （定义 MockBackend 类）
    """
    Mock backend for dry-run testing.

    It simulates `wind_now_y_msc` from the control values so you can verify the
    experiment loop and CSV outputs before connecting to X-Plane.
    """

    def __init__(self) -> None:  # （定义 __init__ 函数）
        self.values: Dict[str, float] = {}  # （保存对象内部状态）

    def set_dataref(self, dataref: str, value: float) -> None:  # （定义 set_dataref 函数）
        self.values[dataref] = value  # （保存对象内部状态）

    def get_dataref(self, dataref: str) -> float:  # （定义 get_dataref 函数）
        if dataref != OBSERVED_VERTICAL_WIND:  # （判断条件并选择执行分支）
            return self.values.get(dataref, 0.0)  # （返回计算结果）

        thermal = self.values.get(CONTROL_DATAREFS["thermal_percent"], 0.0)  # （计算并保存中间变量）
        thermal_rate = self.values.get(CONTROL_DATAREFS["thermal_rate_ms"], 0.0)  # （计算并保存中间变量）
        turb0 = self.values.get(CONTROL_DATAREFS["wind_turbulence_percent_0"], 0.0)  # （计算并保存中间变量）
        turb_layer = self.values.get(CONTROL_DATAREFS["turbulence_0"], 0.0)  # （计算并保存中间变量）
        speed0 = self.values.get(CONTROL_DATAREFS["wind_speed_kt_0"], 0.0)  # （计算并保存中间变量）
        speed1 = self.values.get(CONTROL_DATAREFS["wind_speed_kt_1"], 0.0)  # （计算并保存中间变量）
        shear_speed = self.values.get(CONTROL_DATAREFS["shear_speed_kt_0"], 0.0)  # （计算并保存中间变量）

        base_updraft = 0.015 * thermal + 0.3 * thermal_rate  # （计算并保存中间变量）
        shear_effect = 0.015 * abs(speed1 - speed0) + 0.04 * shear_speed  # （计算并保存中间变量）
        gustiness = 0.005 * turb0 + 0.2 * turb_layer  # （计算并保存中间变量）
        oscillation = math.sin(time.time() * 2.5) * gustiness  # （计算并保存中间变量）
        return base_updraft + shear_effect + oscillation  # （返回计算结果）


class XPlaneUdpBackend(XPlaneBackend):  # （定义 XPlaneUdpBackend 类）
    """
    Minimal native UDP backend for X-Plane's DREF/RREF interface.

    Packet formats are based on the widely used X-Plane UDP DREF/RREF layout:
    - DREF write: `<4sxf500s>`
    - RREF request: `<4sxii400s>`
    - RREF response payload: repeated `<if>` pairs after the 5-byte header
    """

    def __init__(self, host: str, port: int, timeout_seconds: float = 2.0, read_freq_hz: int = 30) -> None:  # （定义 __init__ 函数）
        self.host = host  # （保存对象内部状态）
        self.port = port  # （保存对象内部状态）
        self.timeout_seconds = timeout_seconds  # （保存对象内部状态）
        self.read_freq_hz = read_freq_hz  # （保存对象内部状态）
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)  # （保存对象内部状态）
        self.socket.bind(("", 0))  # （访问或调用对象成员）
        self.socket.settimeout(timeout_seconds)  # （访问或调用对象成员）
        self.subscriptions: Dict[str, int] = {}  # （保存对象内部状态）
        self.index_to_dataref: Dict[int, str] = {}  # （保存对象内部状态）
        self.cache: Dict[str, float] = {}  # （保存对象内部状态）
        self.next_index = 1  # （保存对象内部状态）

    @staticmethod  # （执行具体处理逻辑）
    def _pack_dref(dataref: str, value: float) -> bytes:  # （定义 _pack_dref 函数）
        return struct.pack("<4sxf500s", b"DREF", float(value), dataref.encode("utf-8"))  # （返回计算结果）

    @staticmethod  # （执行具体处理逻辑）
    def _pack_rref(dataref: str, frequency: int, index: int) -> bytes:  # （定义 _pack_rref 函数）
        return struct.pack("<4sxii400s", b"RREF", int(frequency), int(index), dataref.encode("utf-8"))  # （返回计算结果）

    def set_dataref(self, dataref: str, value: float) -> None:  # （定义 set_dataref 函数）
        packet = self._pack_dref(dataref, value)  # （组装 X-Plane UDP 数据包）
        self.socket.sendto(packet, (self.host, self.port))  # （访问或调用对象成员）

    def _ensure_subscription(self, dataref: str) -> int:  # （定义 _ensure_subscription 函数）
        index = self.subscriptions.get(dataref)  # （计算并保存中间变量）
        if index is None:  # （判断条件并选择执行分支）
            index = self.next_index  # （计算并保存中间变量）
            self.next_index += 1  # （保存对象内部状态）
            self.subscriptions[dataref] = index  # （保存对象内部状态）
            self.index_to_dataref[index] = dataref  # （保存对象内部状态）
            packet = self._pack_rref(dataref, self.read_freq_hz, index)  # （组装 X-Plane UDP 数据包）
            self.socket.sendto(packet, (self.host, self.port))  # （访问或调用对象成员）
        return index  # （返回计算结果）

    def _process_rref_packet(self, data: bytes) -> None:  # （定义 _process_rref_packet 函数）
        if data[:4] != b"RREF":  # （判断条件并选择执行分支）
            return  # （返回计算结果）

        payload = data[5:]  # （计算并保存中间变量）
        for offset in range(0, len(payload), 8):  # （遍历数据并循环处理）
            chunk = payload[offset : offset + 8]  # （计算并保存中间变量）
            if len(chunk) < 8:  # （判断条件并选择执行分支）
                continue  # （跳过本轮循环）
            current_index, value = struct.unpack("<if", chunk)  # （计算并保存中间变量）
            dataref = self.index_to_dataref.get(current_index)  # （计算并保存中间变量）
            if dataref is not None:  # （判断条件并选择执行分支）
                self.cache[dataref] = float(value)  # （保存对象内部状态）

    def _drain_socket(self) -> None:  # （定义 _drain_socket 函数）
        original_timeout = self.socket.gettimeout()  # （计算并保存中间变量）
        try:  # （开始异常捕获代码块）
            self.socket.settimeout(0.0)  # （访问或调用对象成员）
            while True:  # （在条件成立时循环执行）
                try:  # （开始异常捕获代码块）
                    data, _ = self.socket.recvfrom(4096)  # （读取或保存数据）
                except (BlockingIOError, socket.timeout):  # （捕获异常并处理）
                    break  # （结束当前循环）
                self._process_rref_packet(data)  # （访问或调用对象成员）
        finally:  # （执行最终清理逻辑）
            self.socket.settimeout(original_timeout)  # （访问或调用对象成员）

    def prime_datarefs(self, datarefs: Sequence[str], wait_seconds: float = 0.5) -> None:  # （定义 prime_datarefs 函数）
        deadline = time.time() + wait_seconds  # （计算并保存中间变量）
        pending = set(datarefs)  # （计算并保存中间变量）
        for dataref in datarefs:  # （遍历数据并循环处理）
            self._ensure_subscription(dataref)  # （访问或调用对象成员）

        while pending and time.time() < deadline:  # （在条件成立时循环执行）
            self._drain_socket()  # （访问或调用对象成员）
            pending = {dataref for dataref in pending if dataref not in self.cache}  # （计算并保存中间变量）
            if pending:  # （判断条件并选择执行分支）
                try:  # （开始异常捕获代码块）
                    data, _ = self.socket.recvfrom(4096)  # （读取或保存数据）
                except socket.timeout:  # （捕获异常并处理）
                    continue  # （跳过本轮循环）
                self._process_rref_packet(data)  # （访问或调用对象成员）

    def get_dataref(self, dataref: str) -> float:  # （定义 get_dataref 函数）
        self._ensure_subscription(dataref)  # （访问或调用对象成员）
        self._drain_socket()  # （访问或调用对象成员）
        if dataref in self.cache:  # （判断条件并选择执行分支）
            return self.cache[dataref]  # （返回计算结果）

        deadline = time.time() + self.timeout_seconds  # （计算并保存中间变量）
        while time.time() < deadline:  # （在条件成立时循环执行）
            try:  # （开始异常捕获代码块）
                data, _ = self.socket.recvfrom(4096)  # （读取或保存数据）
            except socket.timeout as exc:  # （捕获异常并处理）
                raise BackendError(f"Timed out waiting for RREF data for {dataref}") from exc  # （抛出异常提示错误）

            self._process_rref_packet(data)  # （访问或调用对象成员）
            if dataref in self.cache:  # （判断条件并选择执行分支）
                return self.cache[dataref]  # （返回计算结果）

        raise BackendError(f"Did not receive RREF value for {dataref} before timeout")  # （抛出异常提示错误）

    def close(self) -> None:  # （定义 close 函数）
        for dataref, index in list(self.subscriptions.items()):  # （遍历数据并循环处理）
            packet = self._pack_rref(dataref, 0, index)  # （组装 X-Plane UDP 数据包）
            try:  # （开始异常捕获代码块）
                self.socket.sendto(packet, (self.host, self.port))  # （访问或调用对象成员）
            except OSError:  # （捕获异常并处理）
                pass  # （空操作占位）
        self.subscriptions.clear()  # （访问或调用对象成员）
        self.socket.close()  # （访问或调用对象成员）


def parse_args() -> argparse.Namespace:  # （定义 parse_args 函数）
    parser = argparse.ArgumentParser(description="Run repeatable X-Plane weather experiments.")  # （计算并保存中间变量）
    parser.add_argument("--cases", default="weather_cases_template.csv", help="Input case CSV.")  # （注册命令行参数）
    parser.add_argument("--output", default="weather_results.csv", help="Output results CSV.")  # （注册命令行参数）
    parser.add_argument("--host", default="127.0.0.1", help="X-Plane UDP host.")  # （注册命令行参数）
    parser.add_argument("--port", type=int, default=49000, help="X-Plane UDP port.")  # （注册命令行参数）
    parser.add_argument("--timeout", type=float, default=2.0, help="UDP read timeout in seconds.")  # （注册命令行参数）
    parser.add_argument("--read-freq", type=int, default=30, help="Requested RREF update rate in Hz.")  # （注册命令行参数）
    parser.add_argument("--test-dataref", help="Write one DataRef once for connectivity testing.")  # （注册命令行参数）
    parser.add_argument("--test-value", type=float, help="Value used with --test-dataref.")  # （注册命令行参数）
    parser.add_argument(  # （注册命令行参数）
        "--watch-dataref",  # （多行结构中的一项）
        default=OBSERVED_VERTICAL_WIND,  # （计算并保存中间变量）
        help="Observed DataRef to print during --test-dataref mode.",  # （计算并保存中间变量）
    )  # （结束多行结构）
    parser.add_argument(  # （注册命令行参数）
        "--watch-seconds",  # （多行结构中的一项）
        type=float,  # （计算并保存中间变量）
        default=5.0,  # （计算并保存中间变量）
        help="How long to watch the observed DataRef in --test-dataref mode.",  # （计算并保存中间变量）
    )  # （结束多行结构）
    parser.add_argument("--phase-scenario", help="CSV file for multi-phase approach scenario mode.")  # （注册命令行参数）
    parser.add_argument(  # （注册命令行参数）
        "--phase-transition-seconds",  # （多行结构中的一项）
        type=float,  # （计算并保存中间变量）
        default=4.0,  # （计算并保存中间变量）
        help="Seconds used to smoothly interpolate between consecutive phases.",  # （计算并保存中间变量）
    )  # （结束多行结构）
    parser.add_argument(  # （注册命令行参数）
        "--distance-trigger",  # （多行结构中的一项）
        action="store_true",  # （计算并保存中间变量）
        help="Trigger phases by aircraft distance to runway threshold instead of fixed time blocks.",  # （计算并保存中间变量）
    )  # （结束多行结构）
    parser.add_argument(  # （注册命令行参数）
        "--dme-trigger",  # （多行结构中的一项）
        action="store_true",  # （计算并保存中间变量）
        help="Trigger phases by DME distance in nautical miles instead of runway-threshold distance.",  # （计算并保存中间变量）
    )  # （结束多行结构）
    parser.add_argument(  # （注册命令行参数）
        "--phase-transition-distance-m",  # （多行结构中的一项）
        type=float,  # （计算并保存中间变量）
        default=150.0,  # （计算并保存中间变量）
        help="Distance window in meters used to smoothly interpolate between adjacent phases in distance-trigger mode.",  # （计算并保存中间变量）
    )  # （结束多行结构）
    parser.add_argument("--threshold-local-x", type=float, help="Runway threshold local_x in X-Plane local coordinates.")  # （注册命令行参数）
    parser.add_argument("--threshold-local-z", type=float, help="Runway threshold local_z in X-Plane local coordinates.")  # （注册命令行参数）
    parser.add_argument("--threshold-lat", type=float, help="Runway threshold latitude in degrees.")  # （注册命令行参数）
    parser.add_argument("--threshold-lon", type=float, help="Runway threshold longitude in degrees.")  # （注册命令行参数）
    parser.add_argument("--dme-lat", type=float, help="DME station latitude in degrees.")  # （注册命令行参数）
    parser.add_argument("--dme-lon", type=float, help="DME station longitude in degrees.")  # （注册命令行参数）
    parser.add_argument("--runway-heading-deg", type=float, help="Landing runway heading in degrees true.")  # （注册命令行参数）
    parser.add_argument(  # （注册命令行参数）
        "--watch-runway-distance",  # （多行结构中的一项）
        type=float,  # （计算并保存中间变量）
        help="Print distance_to_threshold and lateral_offset for the given number of seconds, then exit.",  # （计算并保存中间变量）
    )  # （结束多行结构）
    parser.add_argument(  # （注册命令行参数）
        "--distance-poll-hz",  # （多行结构中的一项）
        type=float,  # （计算并保存中间变量）
        default=5.0,  # （计算并保存中间变量）
        help="Polling rate while waiting for the aircraft to enter the first distance-trigger phase.",  # （计算并保存中间变量）
    )  # （结束多行结构）
    parser.add_argument(  # （注册命令行参数）
        "--status-interval-seconds",  # （多行结构中的一项）
        type=float,  # （计算并保存中间变量）
        default=1.0,  # （计算并保存中间变量）
        help="How often to print live runway-distance status during distance-trigger scenarios.",  # （计算并保存中间变量）
    )  # （结束多行结构）
    parser.add_argument(  # （注册命令行参数）
        "--telemetry-output",  # （多行结构中的一项）
        help=(  # （计算并保存中间变量）
            "Optional per-time-step telemetry CSV. When set, the script writes aircraft "  # （执行具体处理逻辑）
            "dependent variables continuously during the active weather event."  # （执行具体处理逻辑）
        ),  # （结束多行结构）
    )  # （结束多行结构）
    parser.add_argument(  # （注册命令行参数）
        "--telemetry-interval-seconds",  # （多行结构中的一项）
        type=float,  # （计算并保存中间变量）
        default=1.0,  # （计算并保存中间变量）
        help="Minimum interval between telemetry rows. Use 1 for one row per second, or 0 to save every sample.",  # （计算并保存中间变量）
    )  # （结束多行结构）
    parser.add_argument(  # （注册命令行参数）
        "--dry-run",  # （多行结构中的一项）
        action="store_true",  # （计算并保存中间变量）
        help="Use a mock backend instead of talking to X-Plane.",  # （计算并保存中间变量）
    )  # （结束多行结构）
    return parser.parse_args()  # （返回计算结果）


def load_cases(path: Path) -> List[CaseConfig]:  # （定义 load_cases 函数）
    with path.open("r", encoding="utf-8-sig", newline="") as handle:  # （使用上下文管理资源）
        reader = csv.DictReader(handle)  # （计算并保存中间变量）
        cases: List[CaseConfig] = []  # （声明带类型提示的变量或字段）
        for row in reader:  # （遍历数据并循环处理）
            case_id = row.pop("case_id").strip()  # （计算并保存中间变量）
            note = row.pop("note", "").strip()  # （计算并保存中间变量）
            settle_seconds = float(row.pop("settle_seconds"))  # （计算并保存中间变量）
            sample_seconds = float(row.pop("sample_seconds"))  # （计算并保存中间变量）
            sample_hz = float(row.pop("sample_hz"))  # （计算并保存中间变量）
            values = {key: float(value) for key, value in row.items() if value not in ("", None)}  # （保存待写入的天气参数）
            cases.append(  # （执行具体处理逻辑）
                CaseConfig(  # （执行具体处理逻辑）
                    case_id=case_id,  # （计算并保存中间变量）
                    note=note,  # （计算并保存中间变量）
                    settle_seconds=settle_seconds,  # （计算并保存中间变量）
                    sample_seconds=sample_seconds,  # （计算并保存中间变量）
                    sample_hz=sample_hz,  # （计算并保存中间变量）
                    values=values,  # （保存待写入的天气参数）
                )  # （结束多行结构）
            )  # （结束多行结构）
    return cases  # （返回计算结果）


def load_phases(path: Path) -> List[PhaseConfig]:  # （定义 load_phases 函数）
    with path.open("r", encoding="utf-8-sig", newline="") as handle:  # （使用上下文管理资源）
        reader = csv.DictReader(handle)  # （计算并保存中间变量）
        phases: List[PhaseConfig] = []  # （声明带类型提示的变量或字段）
        for row in reader:  # （遍历数据并循环处理）
            scenario_id = row.pop("scenario_id").strip()  # （计算并保存中间变量）
            phase_id = row.pop("phase_id").strip()  # （计算并保存中间变量）
            note = row.pop("note", "").strip()  # （计算并保存中间变量）
            duration_seconds = float(row.pop("duration_seconds"))  # （计算并保存中间变量）
            sample_hz = float(row.pop("sample_hz"))  # （计算并保存中间变量）
            distance_start_raw = row.pop("distance_start_m", "")  # （计算并保存中间变量）
            distance_end_raw = row.pop("distance_end_m", "")  # （计算并保存中间变量）
            dme_start_raw = row.pop("dme_start_nm", "")  # （计算并保存中间变量）
            dme_end_raw = row.pop("dme_end_nm", "")  # （计算并保存中间变量）
            values = {key: float(value) for key, value in row.items() if value not in ("", None)}  # （保存待写入的天气参数）
            phases.append(  # （执行具体处理逻辑）
                PhaseConfig(  # （执行具体处理逻辑）
                    scenario_id=scenario_id,  # （计算并保存中间变量）
                    phase_id=phase_id,  # （计算并保存中间变量）
                    note=note,  # （计算并保存中间变量）
                    duration_seconds=duration_seconds,  # （计算并保存中间变量）
                    sample_hz=sample_hz,  # （计算并保存中间变量）
                    distance_start_m=float(distance_start_raw) if distance_start_raw not in ("", None) else None,  # （计算并保存中间变量）
                    distance_end_m=float(distance_end_raw) if distance_end_raw not in ("", None) else None,  # （计算并保存中间变量）
                    dme_start_nm=float(dme_start_raw) if dme_start_raw not in ("", None) else None,  # （计算并保存中间变量）
                    dme_end_nm=float(dme_end_raw) if dme_end_raw not in ("", None) else None,  # （计算并保存中间变量）
                    values=values,  # （保存待写入的天气参数）
                )  # （结束多行结构）
            )  # （结束多行结构）
    return phases  # （返回计算结果）


def apply_case(backend: XPlaneBackend, case: CaseConfig) -> None:  # （定义 apply_case 函数）
    for column_name, value in case.values.items():  # （遍历数据并循环处理）
        if column_name not in CONTROL_DATAREFS:  # （判断条件并选择执行分支）
            raise BackendError(f"Unknown control column in CSV: {column_name}")  # （抛出异常提示错误）
        dataref = CONTROL_DATAREFS[column_name]  # （计算并保存中间变量）
        if dataref.startswith("REPLACE_WITH_") and not isinstance(backend, MockBackend):  # （判断条件并选择执行分支）
            raise BackendError(  # （抛出异常提示错误）
                f"CSV column '{column_name}' maps to a placeholder DataRef. "  # （执行具体处理逻辑）
                "Confirm the real DataRef in DataRefEditor first."  # （执行具体处理逻辑）
            )  # （结束多行结构）
        backend.set_dataref(dataref, value)  # （执行具体处理逻辑）


def apply_values(backend: XPlaneBackend, values: Dict[str, float]) -> None:  # （定义 apply_values 函数）
    for column_name, value in values.items():  # （遍历数据并循环处理）
        if column_name not in CONTROL_DATAREFS:  # （判断条件并选择执行分支）
            raise BackendError(f"Unknown control column in CSV: {column_name}")  # （抛出异常提示错误）
        dataref = CONTROL_DATAREFS[column_name]  # （计算并保存中间变量）
        backend.set_dataref(dataref, value)  # （执行具体处理逻辑）


def sample_vertical_wind(backend: XPlaneBackend, duration: float, sample_hz: float) -> List[float]:  # （定义 sample_vertical_wind 函数）
    interval = 1.0 / sample_hz  # （计算并保存中间变量）
    sample_count = max(1, int(duration * sample_hz))  # （计算并保存中间变量）
    samples: List[float] = []  # （保存采样数据）
    for _ in range(sample_count):  # （遍历数据并循环处理）
        samples.append(float(backend.get_dataref(OBSERVED_VERTICAL_WIND)))  # （执行具体处理逻辑）
        time.sleep(interval)  # （暂停等待采样或状态稳定）
    return samples  # （返回计算结果）


def sample_observed_datarefs(  # （定义 sample_observed_datarefs 函数）
    backend: XPlaneBackend, duration: float, sample_hz: float, observed: Dict[str, str]  # （执行具体处理逻辑）
) -> Dict[str, List[float]]:  # （开始一个代码块）
    interval = 1.0 / sample_hz  # （计算并保存中间变量）
    sample_count = max(1, int(duration * sample_hz))  # （计算并保存中间变量）
    samples = {name: [] for name in observed}  # （保存采样数据）
    for _ in range(sample_count):  # （遍历数据并循环处理）
        for name, dataref in observed.items():  # （遍历数据并循环处理）
            samples[name].append(float(backend.get_dataref(dataref)))  # （执行具体处理逻辑）
        time.sleep(interval)  # （暂停等待采样或状态稳定）
    return samples  # （返回计算结果）


def prime_observed_datarefs(backend: XPlaneBackend, observed: Dict[str, str]) -> None:  # （定义 prime_observed_datarefs 函数）
    prime_method = getattr(backend, "prime_datarefs", None)  # （计算并保存中间变量）
    if callable(prime_method):  # （判断条件并选择执行分支）
        prime_method(list(observed.values()))  # （执行具体处理逻辑）


def classify_vertical_wind(mean_y: float, std_y: float, max_abs_y: float) -> str:  # （定义 classify_vertical_wind 函数）
    if std_y > 1.0 and max_abs_y > 2.0:  # （判断条件并选择执行分支）
        return "strong_vertical_shear"  # （返回计算结果）
    if mean_y > 1.0 and std_y < 0.5:  # （判断条件并选择执行分支）
        return "sustained_updraft"  # （返回计算结果）
    if mean_y < -1.0 and std_y < 0.5:  # （判断条件并选择执行分支）
        return "sustained_downdraft"  # （返回计算结果）
    if max_abs_y < 0.5:  # （判断条件并选择执行分支）
        return "weak"  # （返回计算结果）
    return "mixed"  # （返回计算结果）


def compute_impact_score(summary: Dict[str, float | str]) -> float:  # （定义 compute_impact_score 函数）
    vertical_speed_component = abs(float(summary.get("vertical_speed_fpm_delta", 0.0))) / 500.0  # （计算并保存中间变量）
    airspeed_component = abs(float(summary.get("indicated_airspeed_delta", 0.0))) / 10.0  # （计算并保存中间变量）
    local_y_component = abs(float(summary.get("local_y_delta", 0.0))) / 50.0  # （计算并保存中间变量）
    heading_component = abs(float(summary.get("heading_psi_deg_delta", 0.0))) / 5.0  # （计算并保存中间变量）
    pitch_component = abs(float(summary.get("pitch_theta_deg_delta", 0.0)))  # （计算并保存中间变量）
    roll_component = abs(float(summary.get("roll_phi_deg_delta", 0.0)))  # （计算并保存中间变量）
    return round(  # （返回计算结果）
        vertical_speed_component  # （执行具体处理逻辑）
        + airspeed_component  # （执行具体处理逻辑）
        + local_y_component  # （执行具体处理逻辑）
        + heading_component  # （执行具体处理逻辑）
        + pitch_component  # （执行具体处理逻辑）
        + roll_component,  # （多行结构中的一项）
        4,  # （多行结构中的一项）
    )  # （结束多行结构）


def classify_aircraft_response(impact_score: float) -> str:  # （定义 classify_aircraft_response 函数）
    if impact_score < 3.0:  # （判断条件并选择执行分支）
        return "weak_response"  # （返回计算结果）
    if impact_score < 8.0:  # （判断条件并选择执行分支）
        return "moderate_response"  # （返回计算结果）
    if impact_score < 15.0:  # （判断条件并选择执行分支）
        return "strong_response"  # （返回计算结果）
    return "severe_response"  # （返回计算结果）


def summarize(case: CaseConfig, samples: Sequence[float]) -> Dict[str, float | str]:  # （定义 summarize 函数）
    mean_y = statistics.fmean(samples)  # （计算并保存中间变量）
    std_y = statistics.pstdev(samples) if len(samples) > 1 else 0.0  # （计算并保存中间变量）
    max_abs_y = max(abs(value) for value in samples)  # （计算并保存中间变量）
    return {  # （返回计算结果）
        "case_id": case.case_id,  # （多行结构中的一项）
        "note": case.note,  # （多行结构中的一项）
        "samples": len(samples),  # （多行结构中的一项）
        "mean_y_mps": round(mean_y, 4),  # （多行结构中的一项）
        "std_y_mps": round(std_y, 4),  # （多行结构中的一项）
        "max_abs_y_mps": round(max_abs_y, 4),  # （多行结构中的一项）
        "wvsi": round(0.5 * abs(mean_y) + 0.5 * std_y, 4),  # （多行结构中的一项）
        "classification": classify_vertical_wind(mean_y, std_y, max_abs_y),  # （多行结构中的一项）
    }  # （结束多行结构）


def summarize_observed(samples_by_name: Dict[str, Sequence[float]]) -> Dict[str, float]:  # （定义 summarize_observed 函数）
    summary: Dict[str, float] = {}  # （保存结果汇总数据）
    for name, samples in samples_by_name.items():  # （遍历数据并循环处理）
        if not samples:  # （判断条件并选择执行分支）
            continue  # （跳过本轮循环）
        delta = samples[-1] - samples[0]  # （计算并保存中间变量）
        if name == "heading_psi_deg":  # （判断条件并选择执行分支）
            # Keep heading deltas on the shortest wrapped path, e.g. 359 -> 2 is +3 deg.
            delta = ((delta + 180.0) % 360.0) - 180.0  # （计算并保存中间变量）
        summary[f"{name}_start"] = round(samples[0], 4)  # （保存结果汇总数据）
        summary[f"{name}_end"] = round(samples[-1], 4)  # （保存结果汇总数据）
        summary[f"{name}_delta"] = round(delta, 4)  # （保存结果汇总数据）
        summary[f"{name}_mean"] = round(statistics.fmean(samples), 4)  # （保存结果汇总数据）
        summary[f"{name}_max_abs"] = round(max(abs(value) for value in samples), 4)  # （保存结果汇总数据）
    return summary  # （返回计算结果）


def get_distance_and_lateral_offset(  # （定义 get_distance_and_lateral_offset 函数）
    backend: XPlaneBackend,  # （多行结构中的一项）
    threshold_local_x: float,  # （多行结构中的一项）
    threshold_local_z: float,  # （多行结构中的一项）
    runway_heading_deg: float,  # （多行结构中的一项）
) -> tuple[float, float]:  # （开始一个代码块）
    local_x = float(backend.get_dataref(POSITION_LOCAL_X))  # （计算并保存中间变量）
    local_z = float(backend.get_dataref(POSITION_LOCAL_Z))  # （计算并保存中间变量）
    delta_x = local_x - threshold_local_x  # （计算并保存中间变量）
    delta_z = local_z - threshold_local_z  # （计算并保存中间变量）

    heading_rad = math.radians(runway_heading_deg)  # （计算并保存中间变量）
    outward_x = -math.sin(heading_rad)  # （计算并保存中间变量）
    outward_z = math.cos(heading_rad)  # （计算并保存中间变量）
    lateral_x = math.cos(heading_rad)  # （计算并保存中间变量）
    lateral_z = math.sin(heading_rad)  # （计算并保存中间变量）

    distance_to_threshold = delta_x * outward_x + delta_z * outward_z  # （计算并保存中间变量）
    lateral_offset = delta_x * lateral_x + delta_z * lateral_z  # （计算并保存中间变量）
    return distance_to_threshold, lateral_offset  # （返回计算结果）


def get_distance_and_lateral_offset_geo(  # （定义 get_distance_and_lateral_offset_geo 函数）
    backend: XPlaneBackend,  # （多行结构中的一项）
    threshold_lat_deg: float,  # （多行结构中的一项）
    threshold_lon_deg: float,  # （多行结构中的一项）
    runway_heading_deg: float,  # （多行结构中的一项）
) -> tuple[float, float]:  # （开始一个代码块）
    latitude_deg = float(backend.get_dataref(POSITION_LATITUDE))  # （计算并保存中间变量）
    longitude_deg = float(backend.get_dataref(POSITION_LONGITUDE))  # （计算并保存中间变量）

    earth_radius_m = 6371000.0  # （计算并保存中间变量）
    lat0 = math.radians(threshold_lat_deg)  # （计算并保存中间变量）
    lon0 = math.radians(threshold_lon_deg)  # （计算并保存中间变量）
    lat1 = math.radians(latitude_deg)  # （计算并保存中间变量）
    lon1 = math.radians(longitude_deg)  # （计算并保存中间变量）

    north_m = (lat1 - lat0) * earth_radius_m  # （计算并保存中间变量）
    east_m = (lon1 - lon0) * earth_radius_m * math.cos((lat0 + lat1) / 2.0)  # （计算并保存中间变量）

    heading_rad = math.radians(runway_heading_deg)  # （计算并保存中间变量）
    # For geographic coordinates we use the local ENU frame, so the approach
    # direction from the threshold outward is opposite the landing runway
    # heading in both east and north components.
    outward_east = -math.sin(heading_rad)  # （计算并保存中间变量）
    outward_north = -math.cos(heading_rad)  # （计算并保存中间变量）
    lateral_east = math.cos(heading_rad)  # （计算并保存中间变量）
    lateral_north = math.sin(heading_rad)  # （计算并保存中间变量）

    distance_to_threshold = east_m * outward_east + north_m * outward_north  # （计算并保存中间变量）
    lateral_offset = east_m * lateral_east + north_m * lateral_north  # （计算并保存中间变量）
    return distance_to_threshold, lateral_offset  # （返回计算结果）


def get_dme_distance_nm_geo(  # （定义 get_dme_distance_nm_geo 函数）
    backend: XPlaneBackend,  # （多行结构中的一项）
    dme_lat_deg: float,  # （多行结构中的一项）
    dme_lon_deg: float,  # （多行结构中的一项）
) -> float:  # （开始一个代码块）
    latitude_deg = float(backend.get_dataref(POSITION_LATITUDE))  # （计算并保存中间变量）
    longitude_deg = float(backend.get_dataref(POSITION_LONGITUDE))  # （计算并保存中间变量）

    earth_radius_m = 6371000.0  # （计算并保存中间变量）
    lat0 = math.radians(dme_lat_deg)  # （计算并保存中间变量）
    lon0 = math.radians(dme_lon_deg)  # （计算并保存中间变量）
    lat1 = math.radians(latitude_deg)  # （计算并保存中间变量）
    lon1 = math.radians(longitude_deg)  # （计算并保存中间变量）

    north_m = (lat1 - lat0) * earth_radius_m  # （计算并保存中间变量）
    east_m = (lon1 - lon0) * earth_radius_m * math.cos((lat0 + lat1) / 2.0)  # （计算并保存中间变量）
    horizontal_distance_m = math.hypot(north_m, east_m)  # （计算并保存中间变量）
    return horizontal_distance_m / 1852.0  # （返回计算结果）


def summarize_series(samples: Sequence[float], label: str) -> Dict[str, float]:  # （定义 summarize_series 函数）
    if not samples:  # （判断条件并选择执行分支）
        return {}  # （返回计算结果）
    return {  # （返回计算结果）
        f"{label}_start": round(samples[0], 4),  # （多行结构中的一项）
        f"{label}_end": round(samples[-1], 4),  # （多行结构中的一项）
        f"{label}_delta": round(samples[-1] - samples[0], 4),  # （多行结构中的一项）
        f"{label}_mean": round(statistics.fmean(samples), 4),  # （多行结构中的一项）
        f"{label}_max_abs": round(max(abs(value) for value in samples), 4),  # （多行结构中的一项）
    }  # （结束多行结构）


def watch_runway_distance(  # （定义 watch_runway_distance 函数）
    backend: XPlaneBackend,  # （多行结构中的一项）
    watch_seconds: float,  # （多行结构中的一项）
    distance_poll_hz: float,  # （多行结构中的一项）
    runway_heading_deg: float,  # （多行结构中的一项）
    threshold_local_x: float | None = None,  # （声明带类型提示的变量或字段）
    threshold_local_z: float | None = None,  # （声明带类型提示的变量或字段）
    threshold_lat: float | None = None,  # （声明带类型提示的变量或字段）
    threshold_lon: float | None = None,  # （声明带类型提示的变量或字段）
    dme_lat: float | None = None,  # （声明带类型提示的变量或字段）
    dme_lon: float | None = None,  # （声明带类型提示的变量或字段）
) -> None:  # （开始一个代码块）
    if isinstance(backend, MockBackend):  # （判断条件并选择执行分支）
        raise BackendError("Runway distance watch requires a live X-Plane backend.")  # （抛出异常提示错误）

    if threshold_local_x is not None and threshold_local_z is not None:  # （判断条件并选择执行分支）
        distance_provider = lambda: get_distance_and_lateral_offset(  # （计算并保存中间变量）
            backend, threshold_local_x, threshold_local_z, runway_heading_deg  # （执行具体处理逻辑）
        )  # （结束多行结构）
    elif threshold_lat is not None and threshold_lon is not None:  # （继续判断其他条件）
        distance_provider = lambda: get_distance_and_lateral_offset_geo(  # （计算并保存中间变量）
            backend, threshold_lat, threshold_lon, runway_heading_deg  # （执行具体处理逻辑）
        )  # （结束多行结构）
    else:  # （处理默认分支）
        raise BackendError(  # （抛出异常提示错误）
            "Runway distance watch requires either threshold local coordinates or threshold latitude/longitude."  # （执行具体处理逻辑）
        )  # （结束多行结构）

    interval = 1.0 / max(distance_poll_hz, 0.1)  # （计算并保存中间变量）
    deadline = time.time() + watch_seconds  # （计算并保存中间变量）
    while time.time() < deadline:  # （在条件成立时循环执行）
        distance_to_threshold_m, lateral_offset_m = distance_provider()  # （计算并保存中间变量）
        latitude_deg = float(backend.get_dataref(POSITION_LATITUDE))  # （计算并保存中间变量）
        longitude_deg = float(backend.get_dataref(POSITION_LONGITUDE))  # （计算并保存中间变量）
        message = (  # （计算并保存中间变量）
            f"distance_to_threshold_m={distance_to_threshold_m:.1f}, "  # （计算并保存中间变量）
            f"lateral_offset_m={lateral_offset_m:.1f}, "  # （计算并保存中间变量）
            f"lat={latitude_deg:.7f}, lon={longitude_deg:.7f}"  # （计算并保存中间变量）
        )  # （结束多行结构）
        if dme_lat is not None and dme_lon is not None:  # （判断条件并选择执行分支）
            dme_distance_nm = get_dme_distance_nm_geo(backend, dme_lat, dme_lon)  # （计算并保存中间变量）
            message += f", dme_distance_nm={dme_distance_nm:.2f}"  # （计算并保存中间变量）
        print(message)  # （输出运行状态或结果）
        time.sleep(interval)  # （暂停等待采样或状态稳定）


def write_results(path: Path, rows: Iterable[Dict[str, float | str]]) -> None:  # （定义 write_results 函数）
    rows = list(rows)  # （保存输出结果行）
    if not rows:  # （判断条件并选择执行分支）
        return  # （返回计算结果）
    fieldnames = list(rows[0].keys())  # （确定 CSV 输出列名）
    with path.open("w", encoding="utf-8", newline="") as handle:  # （使用上下文管理资源）
        writer = csv.DictWriter(handle, fieldnames=fieldnames)  # （计算并保存中间变量）
        writer.writeheader()  # （进行 CSV 读写操作）
        writer.writerows(rows)  # （进行 CSV 读写操作）


class TelemetryRecorder:  # （定义 TelemetryRecorder 类）
    """Continuously writes time-series aircraft response rows for later plotting."""  # （执行具体处理逻辑）

    def __init__(self, path: Path, interval_seconds: float = 1.0) -> None:  # （定义 __init__ 函数）
        self.path = path  # （保存对象内部状态）
        self.interval_seconds = max(float(interval_seconds), 0.0)  # （保存对象内部状态）
        self.start_time: float | None = None  # （保存对象内部状态）
        self.last_write_elapsed: float | None = None  # （保存对象内部状态）
        self.sample_index = 0  # （保存对象内部状态）
        self.path.parent.mkdir(parents=True, exist_ok=True)  # （保存对象内部状态）
        self.handle = self.path.open("w", encoding="utf-8-sig", newline="")  # （保存对象内部状态）
        self.fieldnames = [  # （保存对象内部状态）
            "timestamp_local",  # （多行结构中的一项）
            "elapsed_seconds",  # （多行结构中的一项）
            "telemetry_index",  # （多行结构中的一项）
            "scenario_id",  # （多行结构中的一项）
            "phase_id",  # （多行结构中的一项）
            "note",  # （多行结构中的一项）
            "dme_distance_nm",  # （多行结构中的一项）
            "distance_to_threshold_m",  # （多行结构中的一项）
            "lateral_offset_m",  # （多行结构中的一项）
            *OBSERVED_DATAREFS.keys(),  # （多行结构中的一项）
            *[f"active_{name}" for name in CONTROL_DATAREFS.keys()],  # （多行结构中的一项）
        ]  # （结束多行结构）
        self.writer = csv.DictWriter(self.handle, fieldnames=self.fieldnames)  # （保存对象内部状态）
        self.writer.writeheader()  # （访问或调用对象成员）

    def maybe_record(  # （定义 maybe_record 函数）
        self,  # （多行结构中的一项）
        *,  # （多行结构中的一项）
        scenario_id: str,  # （多行结构中的一项）
        phase_id: str,  # （多行结构中的一项）
        note: str,  # （多行结构中的一项）
        observed_values: Dict[str, float],  # （多行结构中的一项）
        active_values: Dict[str, float] | None = None,  # （声明带类型提示的变量或字段）
        dme_distance_nm: float | None = None,  # （声明带类型提示的变量或字段）
        distance_to_threshold_m: float | None = None,  # （声明带类型提示的变量或字段）
        lateral_offset_m: float | None = None,  # （声明带类型提示的变量或字段）
        force: bool = False,  # （声明带类型提示的变量或字段）
    ) -> None:  # （开始一个代码块）
        now = time.time()  # （计算并保存中间变量）
        if self.start_time is None:  # （判断条件并选择执行分支）
            self.start_time = now  # （保存对象内部状态）
        elapsed_seconds = now - self.start_time  # （计算并保存中间变量）
        if (  # （判断条件并选择执行分支）
            not force  # （执行具体处理逻辑）
            and self.last_write_elapsed is not None  # （执行具体处理逻辑）
            and self.interval_seconds > 0  # （执行具体处理逻辑）
            and (elapsed_seconds - self.last_write_elapsed) < self.interval_seconds  # （执行具体处理逻辑）
        ):  # （开始一个代码块）
            return  # （返回计算结果）

        row: Dict[str, float | str] = {  # （声明带类型提示的变量或字段）
            "timestamp_local": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),  # （多行结构中的一项）
            "elapsed_seconds": round(elapsed_seconds, 3),  # （多行结构中的一项）
            "telemetry_index": self.sample_index,  # （多行结构中的一项）
            "scenario_id": scenario_id,  # （多行结构中的一项）
            "phase_id": phase_id,  # （多行结构中的一项）
            "note": note,  # （多行结构中的一项）
            "dme_distance_nm": "" if dme_distance_nm is None else round(dme_distance_nm, 5),  # （多行结构中的一项）
            "distance_to_threshold_m": "" if distance_to_threshold_m is None else round(distance_to_threshold_m, 3),  # （多行结构中的一项）
            "lateral_offset_m": "" if lateral_offset_m is None else round(lateral_offset_m, 3),  # （多行结构中的一项）
        }  # （结束多行结构）
        for name in OBSERVED_DATAREFS:  # （遍历数据并循环处理）
            value = observed_values.get(name)  # （计算并保存中间变量）
            row[name] = "" if value is None else round(value, 5)  # （计算并保存中间变量）
        if active_values:  # （判断条件并选择执行分支）
            for name in CONTROL_DATAREFS:  # （遍历数据并循环处理）
                value = active_values.get(name)  # （计算并保存中间变量）
                row[f"active_{name}"] = "" if value is None else round(value, 5)  # （计算并保存中间变量）

        self.writer.writerow(row)  # （访问或调用对象成员）
        self.handle.flush()  # （访问或调用对象成员）
        self.last_write_elapsed = elapsed_seconds  # （保存对象内部状态）
        self.sample_index += 1  # （保存对象内部状态）

    def close(self) -> None:  # （定义 close 函数）
        self.handle.close()  # （访问或调用对象成员）


def make_backend(args: argparse.Namespace) -> XPlaneBackend:  # （定义 make_backend 函数）
    if args.dry_run:  # （判断条件并选择执行分支）
        return MockBackend()  # （返回计算结果）
    return XPlaneUdpBackend(args.host, args.port, args.timeout, args.read_freq)  # （返回计算结果）


def run_single_dataref_test(backend: XPlaneBackend, dataref: str, value: float, watch_dataref: str, watch_seconds: float) -> None:  # （定义 run_single_dataref_test 函数）
    print(f"Writing {dataref} = {value}")  # （输出运行状态或结果）
    backend.set_dataref(dataref, value)  # （执行具体处理逻辑）
    end_time = time.time() + watch_seconds  # （计算并保存中间变量）
    while time.time() < end_time:  # （在条件成立时循环执行）
        observed = backend.get_dataref(watch_dataref)  # （计算并保存中间变量）
        print(f"{watch_dataref} = {observed:.4f}")  # （输出运行状态或结果）
        time.sleep(0.5)  # （暂停等待采样或状态稳定）


def interpolate_values(start: Dict[str, float], end: Dict[str, float], ratio: float) -> Dict[str, float]:  # （定义 interpolate_values 函数）
    keys = set(start) | set(end)  # （计算并保存中间变量）
    values: Dict[str, float] = {}  # （保存待写入的天气参数）
    for key in keys:  # （遍历数据并循环处理）
        start_value = start.get(key, 0.0)  # （计算并保存中间变量）
        end_value = end.get(key, 0.0)  # （计算并保存中间变量）
        values[key] = start_value + (end_value - start_value) * ratio  # （保存待写入的天气参数）
    return values  # （返回计算结果）


def sample_transition(  # （定义 sample_transition 函数）
    backend: XPlaneBackend,  # （多行结构中的一项）
    start_values: Dict[str, float],  # （多行结构中的一项）
    end_values: Dict[str, float],  # （多行结构中的一项）
    duration_seconds: float,  # （多行结构中的一项）
    sample_hz: float,  # （多行结构中的一项）
) -> Dict[str, List[float]]:  # （开始一个代码块）
    if duration_seconds <= 0:  # （判断条件并选择执行分支）
        return {name: [] for name in OBSERVED_DATAREFS}  # （返回计算结果）

    interval = 1.0 / sample_hz  # （计算并保存中间变量）
    step_count = max(1, int(duration_seconds * sample_hz))  # （计算并保存中间变量）
    observed_samples = {name: [] for name in OBSERVED_DATAREFS}  # （计算并保存中间变量）

    for step in range(step_count):  # （遍历数据并循环处理）
        ratio = (step + 1) / step_count  # （计算并保存中间变量）
        apply_values(backend, interpolate_values(start_values, end_values, ratio))  # （执行具体处理逻辑）
        for name, dataref in OBSERVED_DATAREFS.items():  # （遍历数据并循环处理）
            observed_samples[name].append(float(backend.get_dataref(dataref)))  # （执行具体处理逻辑）
        time.sleep(interval)  # （暂停等待采样或状态稳定）

    return observed_samples  # （返回计算结果）


def run_phase_scenario(  # （定义 run_phase_scenario 函数）
    backend: XPlaneBackend,  # （多行结构中的一项）
    phases_path: Path,  # （多行结构中的一项）
    transition_seconds: float,  # （多行结构中的一项）
) -> List[Dict[str, float | str]]:  # （开始一个代码块）
    phases = load_phases(phases_path)  # （读取阶段场景配置）
    if not phases:  # （判断条件并选择执行分支）
        raise BackendError(f"No phases found in {phases_path}")  # （抛出异常提示错误）
    prime_observed_datarefs(backend, OBSERVED_DATAREFS)  # （执行具体处理逻辑）

    results: List[Dict[str, float | str]] = []  # （声明带类型提示的变量或字段）
    aggregate_samples = {name: [] for name in OBSERVED_DATAREFS}  # （计算并保存中间变量）
    previous_phase: PhaseConfig | None = None  # （声明带类型提示的变量或字段）

    for phase in phases:  # （遍历数据并循环处理）
        if previous_phase is not None and transition_seconds > 0:  # （判断条件并选择执行分支）
            transition_label = f"{previous_phase.phase_id}_to_{phase.phase_id}"  # （计算并保存中间变量）
            print(f"Running {phase.scenario_id}/{transition_label} ...")  # （输出运行状态或结果）
            transition_samples = sample_transition(  # （计算并保存中间变量）
                backend,  # （多行结构中的一项）
                previous_phase.values,  # （多行结构中的一项）
                phase.values,  # （多行结构中的一项）
                transition_seconds,  # （多行结构中的一项）
                phase.sample_hz,  # （多行结构中的一项）
            )  # （结束多行结构）
            for name, series in transition_samples.items():  # （遍历数据并循环处理）
                aggregate_samples[name].extend(series)  # （执行具体处理逻辑）

            transition_summary: Dict[str, float | str] = {  # （声明带类型提示的变量或字段）
                "scenario_id": phase.scenario_id,  # （多行结构中的一项）
                "phase_id": transition_label,  # （多行结构中的一项）
                "note": "Smooth transition between consecutive downburst phases",  # （多行结构中的一项）
                "samples": len(transition_samples["wind_now_y_msc"]),  # （多行结构中的一项）
            }  # （结束多行结构）
            transition_summary.update(summarize_series(transition_samples["wind_now_y_msc"], "wind_now_y_msc"))  # （执行具体处理逻辑）
            transition_summary.update(summarize_observed(transition_samples))  # （执行具体处理逻辑）
            transition_impact = compute_impact_score(transition_summary)  # （计算并保存中间变量）
            transition_summary["impact_score"] = transition_impact  # （计算并保存中间变量）
            transition_summary["response_classification"] = classify_aircraft_response(transition_impact)  # （计算并保存中间变量）
            results.append(transition_summary)  # （执行具体处理逻辑）
            print(transition_summary)  # （输出运行状态或结果）

        print(f"Running {phase.scenario_id}/{phase.phase_id} ...")  # （输出运行状态或结果）
        apply_values(backend, phase.values)  # （执行具体处理逻辑）
        observed_samples = sample_observed_datarefs(  # （计算并保存中间变量）
            backend, phase.duration_seconds, phase.sample_hz, OBSERVED_DATAREFS  # （执行具体处理逻辑）
        )  # （结束多行结构）
        for name, series in observed_samples.items():  # （遍历数据并循环处理）
            aggregate_samples[name].extend(series)  # （执行具体处理逻辑）

        summary: Dict[str, float | str] = {  # （保存结果汇总数据）
            "scenario_id": phase.scenario_id,  # （多行结构中的一项）
            "phase_id": phase.phase_id,  # （多行结构中的一项）
            "note": phase.note,  # （多行结构中的一项）
            "samples": len(observed_samples["wind_now_y_msc"]),  # （多行结构中的一项）
        }  # （结束多行结构）
        summary.update(summarize_series(observed_samples["wind_now_y_msc"], "wind_now_y_msc"))  # （执行具体处理逻辑）
        summary.update(summarize_observed(observed_samples))  # （执行具体处理逻辑）
        impact_score = compute_impact_score(summary)  # （计算并保存中间变量）
        summary["impact_score"] = impact_score  # （保存结果汇总数据）
        summary["response_classification"] = classify_aircraft_response(impact_score)  # （保存结果汇总数据）
        results.append(summary)  # （执行具体处理逻辑）
        print(summary)  # （输出运行状态或结果）
        previous_phase = phase  # （计算并保存中间变量）

    final_summary: Dict[str, float | str] = {  # （声明带类型提示的变量或字段）
        "scenario_id": phases[0].scenario_id,  # （多行结构中的一项）
        "phase_id": "all_phases",  # （多行结构中的一项）
        "note": "Aggregate response across the full three-phase approach",  # （多行结构中的一项）
        "samples": len(aggregate_samples["wind_now_y_msc"]),  # （多行结构中的一项）
    }  # （结束多行结构）
    final_summary.update(summarize_series(aggregate_samples["wind_now_y_msc"], "wind_now_y_msc"))  # （执行具体处理逻辑）
    final_summary.update(summarize_observed(aggregate_samples))  # （执行具体处理逻辑）
    impact_score = compute_impact_score(final_summary)  # （计算并保存中间变量）
    final_summary["impact_score"] = impact_score  # （计算并保存中间变量）
    final_summary["response_classification"] = classify_aircraft_response(impact_score)  # （计算并保存中间变量）
    results.append(final_summary)  # （执行具体处理逻辑）
    print(final_summary)  # （输出运行状态或结果）
    return results  # （返回计算结果）


def validate_distance_phases(phases: Sequence[PhaseConfig]) -> None:  # （定义 validate_distance_phases 函数）
    for phase in phases:  # （遍历数据并循环处理）
        if phase.distance_start_m is None or phase.distance_end_m is None:  # （判断条件并选择执行分支）
            raise BackendError(  # （抛出异常提示错误）
                "Distance-trigger mode requires every phase row to include distance_start_m and distance_end_m columns."  # （执行具体处理逻辑）
            )  # （结束多行结构）
        if phase.distance_start_m <= phase.distance_end_m:  # （判断条件并选择执行分支）
            raise BackendError(  # （抛出异常提示错误）
                f"Phase {phase.phase_id} must satisfy distance_start_m > distance_end_m for inbound approach triggering."  # （执行具体处理逻辑）
            )  # （结束多行结构）


def validate_dme_phases(phases: Sequence[PhaseConfig]) -> None:  # （定义 validate_dme_phases 函数）
    for phase in phases:  # （遍历数据并循环处理）
        if phase.dme_start_nm is None or phase.dme_end_nm is None:  # （判断条件并选择执行分支）
            raise BackendError(  # （抛出异常提示错误）
                "DME-trigger mode requires every phase row to include dme_start_nm and dme_end_nm columns."  # （执行具体处理逻辑）
            )  # （结束多行结构）
        if phase.dme_start_nm <= phase.dme_end_nm:  # （判断条件并选择执行分支）
            raise BackendError(  # （抛出异常提示错误）
                f"Phase {phase.phase_id} must satisfy dme_start_nm > dme_end_nm for inbound approach triggering."  # （执行具体处理逻辑）
            )  # （结束多行结构）


def compute_active_segment(  # （定义 compute_active_segment 函数）
    phases: Sequence[PhaseConfig],  # （多行结构中的一项）
    remaining_distance_m: float,  # （多行结构中的一项）
    transition_distance_m: float,  # （多行结构中的一项）
) -> tuple[str | None, str, str, Dict[str, float] | None]:  # （开始一个代码块）
    half_window = max(transition_distance_m / 2.0, 0.0)  # （计算并保存中间变量）

    for index, phase in enumerate(phases[:-1]):  # （遍历数据并循环处理）
        next_phase = phases[index + 1]  # （计算并保存中间变量）
        boundary = float(phase.distance_end_m)  # （计算并保存中间变量）
        if half_window > 0 and (boundary - half_window) <= remaining_distance_m <= (boundary + half_window):  # （判断条件并选择执行分支）
            ratio = (boundary + half_window - remaining_distance_m) / max(transition_distance_m, 1e-6)  # （计算并保存中间变量）
            ratio = max(0.0, min(1.0, ratio))  # （计算并保存中间变量）
            return (  # （返回计算结果）
                f"{phase.phase_id}_to_{next_phase.phase_id}",  # （多行结构中的一项）
                "Smooth transition by runway distance between consecutive downburst phases",  # （多行结构中的一项）
                phase.scenario_id,  # （多行结构中的一项）
                interpolate_values(phase.values, next_phase.values, ratio),  # （多行结构中的一项）
            )  # （结束多行结构）

    for phase in phases:  # （遍历数据并循环处理）
        if float(phase.distance_end_m) <= remaining_distance_m <= float(phase.distance_start_m):  # （判断条件并选择执行分支）
            return phase.phase_id, phase.note, phase.scenario_id, dict(phase.values)  # （返回计算结果）

    return None, "", phases[0].scenario_id, None  # （返回计算结果）


def compute_active_segment_dme(  # （定义 compute_active_segment_dme 函数）
    phases: Sequence[PhaseConfig],  # （多行结构中的一项）
    current_dme_nm: float,  # （多行结构中的一项）
    transition_window_nm: float,  # （多行结构中的一项）
) -> tuple[str | None, str, str, Dict[str, float] | None]:  # （开始一个代码块）
    half_window = max(transition_window_nm / 2.0, 0.0)  # （计算并保存中间变量）

    for index, phase in enumerate(phases[:-1]):  # （遍历数据并循环处理）
        next_phase = phases[index + 1]  # （计算并保存中间变量）
        boundary = float(phase.dme_end_nm)  # （计算并保存中间变量）
        if half_window > 0 and (boundary - half_window) <= current_dme_nm <= (boundary + half_window):  # （判断条件并选择执行分支）
            ratio = (boundary + half_window - current_dme_nm) / max(transition_window_nm, 1e-6)  # （计算并保存中间变量）
            ratio = max(0.0, min(1.0, ratio))  # （计算并保存中间变量）
            return (  # （返回计算结果）
                f"{phase.phase_id}_to_{next_phase.phase_id}",  # （多行结构中的一项）
                "Smooth transition by DME distance between consecutive downburst phases",  # （多行结构中的一项）
                phase.scenario_id,  # （多行结构中的一项）
                interpolate_values(phase.values, next_phase.values, ratio),  # （多行结构中的一项）
            )  # （结束多行结构）

    for phase in phases:  # （遍历数据并循环处理）
        if float(phase.dme_end_nm) <= current_dme_nm <= float(phase.dme_start_nm):  # （判断条件并选择执行分支）
            return phase.phase_id, phase.note, phase.scenario_id, dict(phase.values)  # （返回计算结果）

    return None, "", phases[0].scenario_id, None  # （返回计算结果）


def run_distance_phase_scenario(  # （定义 run_distance_phase_scenario 函数）
    backend: XPlaneBackend,  # （多行结构中的一项）
    phases_path: Path,  # （多行结构中的一项）
    transition_distance_m: float,  # （多行结构中的一项）
    runway_heading_deg: float,  # （多行结构中的一项）
    distance_poll_hz: float,  # （多行结构中的一项）
    status_interval_seconds: float,  # （多行结构中的一项）
    threshold_local_x: float | None = None,  # （声明带类型提示的变量或字段）
    threshold_local_z: float | None = None,  # （声明带类型提示的变量或字段）
    threshold_lat: float | None = None,  # （声明带类型提示的变量或字段）
    threshold_lon: float | None = None,  # （声明带类型提示的变量或字段）
    telemetry_recorder: TelemetryRecorder | None = None,  # （声明带类型提示的变量或字段）
) -> List[Dict[str, float | str]]:  # （开始一个代码块）
    phases = load_phases(phases_path)  # （读取阶段场景配置）
    if not phases:  # （判断条件并选择执行分支）
        raise BackendError(f"No phases found in {phases_path}")  # （抛出异常提示错误）
    validate_distance_phases(phases)  # （执行具体处理逻辑）

    first_start = float(phases[0].distance_start_m)  # （计算并保存中间变量）
    last_end = float(phases[-1].distance_end_m)  # （计算并保存中间变量）
    sample_hz = phases[0].sample_hz  # （计算并保存中间变量）
    interval = 1.0 / sample_hz  # （计算并保存中间变量）
    wait_interval = 1.0 / max(distance_poll_hz, 0.1)  # （计算并保存中间变量）

    if isinstance(backend, MockBackend):  # （判断条件并选择执行分支）
        raise BackendError("Distance-trigger mode requires a live X-Plane backend because it depends on aircraft position.")  # （抛出异常提示错误）
    prime_observed_datarefs(backend, OBSERVED_DATAREFS)  # （执行具体处理逻辑）

    if threshold_local_x is not None and threshold_local_z is not None:  # （判断条件并选择执行分支）
        distance_provider = lambda: get_distance_and_lateral_offset(  # （计算并保存中间变量）
            backend, threshold_local_x, threshold_local_z, runway_heading_deg  # （执行具体处理逻辑）
        )  # （结束多行结构）
    elif threshold_lat is not None and threshold_lon is not None:  # （继续判断其他条件）
        distance_provider = lambda: get_distance_and_lateral_offset_geo(  # （计算并保存中间变量）
            backend, threshold_lat, threshold_lon, runway_heading_deg  # （执行具体处理逻辑）
        )  # （结束多行结构）
    else:  # （处理默认分支）
        raise BackendError(  # （抛出异常提示错误）
            "Distance-trigger mode requires either threshold local coordinates or threshold latitude/longitude."  # （执行具体处理逻辑）
        )  # （结束多行结构）

    print(  # （输出运行状态或结果）
        f"Waiting for aircraft to enter first phase at <= {first_start:.1f} m from runway threshold..."  # （计算并保存中间变量）
    )  # （结束多行结构）
    while True:  # （在条件成立时循环执行）
        remaining_distance_m, lateral_offset_m = distance_provider()  # （计算并保存中间变量）
        if remaining_distance_m <= first_start:  # （判断条件并选择执行分支）
            print(  # （输出运行状态或结果）
                f"Entered downburst event: distance_to_threshold_m={remaining_distance_m:.1f}, lateral_offset_m={lateral_offset_m:.1f}"  # （声明带类型提示的变量或字段）
            )  # （结束多行结构）
            break  # （结束当前循环）
        time.sleep(wait_interval)  # （暂停等待采样或状态稳定）

    segment_samples: Dict[str, Dict[str, List[float]]] = {}  # （声明带类型提示的变量或字段）
    segment_notes: Dict[str, str] = {}  # （声明带类型提示的变量或字段）
    segment_scenarios: Dict[str, str] = {}  # （声明带类型提示的变量或字段）
    segment_entry_distance: Dict[str, float] = {}  # （声明带类型提示的变量或字段）
    segment_entry_lateral: Dict[str, float] = {}  # （声明带类型提示的变量或字段）
    aggregate_samples = {name: [] for name in OBSERVED_DATAREFS}  # （计算并保存中间变量）
    aggregate_samples["distance_to_threshold_m"] = []  # （计算并保存中间变量）
    aggregate_samples["lateral_offset_m"] = []  # （计算并保存中间变量）
    last_segment_id: str | None = None  # （声明带类型提示的变量或字段）
    last_status_time = 0.0  # （计算并保存中间变量）

    while True:  # （在条件成立时循环执行）
        remaining_distance_m, lateral_offset_m = distance_provider()  # （计算并保存中间变量）
        if remaining_distance_m <= last_end:  # （判断条件并选择执行分支）
            print(  # （输出运行状态或结果）
                f"[EVENT] Completed downburst event: distance_to_threshold_m={remaining_distance_m:.1f}, "  # （声明带类型提示的变量或字段）
                f"lateral_offset_m={lateral_offset_m:.1f}"  # （计算并保存中间变量）
            )  # （结束多行结构）
            break  # （结束当前循环）

        segment_id, note, scenario_id, active_values = compute_active_segment(  # （计算并保存中间变量）
            phases, remaining_distance_m, transition_distance_m  # （执行具体处理逻辑）
        )  # （结束多行结构）
        if segment_id is None or active_values is None:  # （判断条件并选择执行分支）
            time.sleep(interval)  # （暂停等待采样或状态稳定）
            continue  # （跳过本轮循环）

        apply_values(backend, active_values)  # （执行具体处理逻辑）
        if segment_id not in segment_samples:  # （判断条件并选择执行分支）
            segment_samples[segment_id] = {name: [] for name in OBSERVED_DATAREFS}  # （计算并保存中间变量）
            segment_samples[segment_id]["distance_to_threshold_m"] = []  # （计算并保存中间变量）
            segment_samples[segment_id]["lateral_offset_m"] = []  # （计算并保存中间变量）
            segment_notes[segment_id] = note  # （计算并保存中间变量）
            segment_scenarios[segment_id] = scenario_id  # （计算并保存中间变量）
            segment_entry_distance[segment_id] = remaining_distance_m  # （计算并保存中间变量）
            segment_entry_lateral[segment_id] = lateral_offset_m  # （计算并保存中间变量）

        now = time.time()  # （计算并保存中间变量）
        if segment_id != last_segment_id:  # （判断条件并选择执行分支）
            print(  # （输出运行状态或结果）
                f"[EVENT] Entered {segment_id}: distance_to_threshold_m={remaining_distance_m:.1f}, "  # （声明带类型提示的变量或字段）
                f"lateral_offset_m={lateral_offset_m:.1f}"  # （计算并保存中间变量）
            )  # （结束多行结构）
            last_segment_id = segment_id  # （计算并保存中间变量）
            last_status_time = now  # （计算并保存中间变量）
        elif (now - last_status_time) >= max(status_interval_seconds, 0.0):  # （继续判断其他条件）
            print(  # （输出运行状态或结果）
                f"[STATUS] segment={segment_id}, distance_to_threshold_m={remaining_distance_m:.1f}, "  # （计算并保存中间变量）
                f"lateral_offset_m={lateral_offset_m:.1f}"  # （计算并保存中间变量）
            )  # （结束多行结构）
            last_status_time = now  # （计算并保存中间变量）

        observed_values: Dict[str, float] = {}  # （声明带类型提示的变量或字段）
        for name, dataref in OBSERVED_DATAREFS.items():  # （遍历数据并循环处理）
            value = float(backend.get_dataref(dataref))  # （计算并保存中间变量）
            observed_values[name] = value  # （计算并保存中间变量）
            segment_samples[segment_id][name].append(value)  # （执行具体处理逻辑）
            aggregate_samples[name].append(value)  # （执行具体处理逻辑）
        segment_samples[segment_id]["distance_to_threshold_m"].append(remaining_distance_m)  # （执行具体处理逻辑）
        segment_samples[segment_id]["lateral_offset_m"].append(lateral_offset_m)  # （执行具体处理逻辑）
        aggregate_samples["distance_to_threshold_m"].append(remaining_distance_m)  # （执行具体处理逻辑）
        aggregate_samples["lateral_offset_m"].append(lateral_offset_m)  # （执行具体处理逻辑）
        if telemetry_recorder is not None:  # （判断条件并选择执行分支）
            telemetry_recorder.maybe_record(  # （执行具体处理逻辑）
                scenario_id=scenario_id,  # （计算并保存中间变量）
                phase_id=segment_id,  # （计算并保存中间变量）
                note=note,  # （计算并保存中间变量）
                observed_values=observed_values,  # （计算并保存中间变量）
                active_values=active_values,  # （计算并保存中间变量）
                distance_to_threshold_m=remaining_distance_m,  # （计算并保存中间变量）
                lateral_offset_m=lateral_offset_m,  # （计算并保存中间变量）
            )  # （结束多行结构）
        time.sleep(interval)  # （暂停等待采样或状态稳定）

    # Build explicit order matching approach progression.
    progression_labels: List[str] = []  # （声明带类型提示的变量或字段）
    for idx, phase in enumerate(phases):  # （遍历数据并循环处理）
        progression_labels.append(phase.phase_id)  # （执行具体处理逻辑）
        if idx < len(phases) - 1:  # （判断条件并选择执行分支）
            progression_labels.append(f"{phase.phase_id}_to_{phases[idx + 1].phase_id}")  # （执行具体处理逻辑）

    results: List[Dict[str, float | str]] = []  # （声明带类型提示的变量或字段）
    for label in progression_labels:  # （遍历数据并循环处理）
        samples = segment_samples.get(label)  # （保存采样数据）
        if not samples:  # （判断条件并选择执行分支）
            continue  # （跳过本轮循环）
        summary: Dict[str, float | str] = {  # （保存结果汇总数据）
            "scenario_id": segment_scenarios[label],  # （多行结构中的一项）
            "phase_id": label,  # （多行结构中的一项）
            "note": segment_notes[label],  # （多行结构中的一项）
            "samples": len(samples["wind_now_y_msc"]),  # （多行结构中的一项）
            "segment_entry_distance_m": round(segment_entry_distance[label], 1),  # （多行结构中的一项）
            "segment_entry_lateral_offset_m": round(segment_entry_lateral[label], 1),  # （多行结构中的一项）
        }  # （结束多行结构）
        summary.update(summarize_series(samples["wind_now_y_msc"], "wind_now_y_msc"))  # （执行具体处理逻辑）
        summary.update(summarize_observed(samples))  # （执行具体处理逻辑）
        impact_score = compute_impact_score(summary)  # （计算并保存中间变量）
        summary["impact_score"] = impact_score  # （保存结果汇总数据）
        summary["response_classification"] = classify_aircraft_response(impact_score)  # （保存结果汇总数据）
        results.append(summary)  # （执行具体处理逻辑）
        print(summary)  # （输出运行状态或结果）

    final_summary: Dict[str, float | str] = {  # （声明带类型提示的变量或字段）
        "scenario_id": phases[0].scenario_id,  # （多行结构中的一项）
        "phase_id": "all_phases",  # （多行结构中的一项）
        "note": "Aggregate response across the full distance-triggered three-phase approach",  # （多行结构中的一项）
        "samples": len(aggregate_samples["wind_now_y_msc"]),  # （多行结构中的一项）
    }  # （结束多行结构）
    final_summary.update(summarize_series(aggregate_samples["wind_now_y_msc"], "wind_now_y_msc"))  # （执行具体处理逻辑）
    final_summary.update(summarize_observed(aggregate_samples))  # （执行具体处理逻辑）
    final_impact = compute_impact_score(final_summary)  # （计算并保存中间变量）
    final_summary["impact_score"] = final_impact  # （计算并保存中间变量）
    final_summary["response_classification"] = classify_aircraft_response(final_impact)  # （计算并保存中间变量）
    results.append(final_summary)  # （执行具体处理逻辑）
    print(final_summary)  # （输出运行状态或结果）
    return results  # （返回计算结果）


def run_dme_phase_scenario(  # （定义 run_dme_phase_scenario 函数）
    backend: XPlaneBackend,  # （多行结构中的一项）
    phases_path: Path,  # （多行结构中的一项）
    dme_lat: float,  # （多行结构中的一项）
    dme_lon: float,  # （多行结构中的一项）
    transition_distance_m: float,  # （多行结构中的一项）
    distance_poll_hz: float,  # （多行结构中的一项）
    status_interval_seconds: float,  # （多行结构中的一项）
    runway_heading_deg: float | None = None,  # （声明带类型提示的变量或字段）
    threshold_local_x: float | None = None,  # （声明带类型提示的变量或字段）
    threshold_local_z: float | None = None,  # （声明带类型提示的变量或字段）
    threshold_lat: float | None = None,  # （声明带类型提示的变量或字段）
    threshold_lon: float | None = None,  # （声明带类型提示的变量或字段）
    telemetry_recorder: TelemetryRecorder | None = None,  # （声明带类型提示的变量或字段）
) -> List[Dict[str, float | str]]:  # （开始一个代码块）
    phases = load_phases(phases_path)  # （读取阶段场景配置）
    if not phases:  # （判断条件并选择执行分支）
        raise BackendError(f"No phases found in {phases_path}")  # （抛出异常提示错误）
    validate_dme_phases(phases)  # （执行具体处理逻辑）

    first_start = float(phases[0].dme_start_nm)  # （计算并保存中间变量）
    last_end = float(phases[-1].dme_end_nm)  # （计算并保存中间变量）
    wait_interval = 1.0 / max(distance_poll_hz, 0.1)  # （计算并保存中间变量）
    sample_hz = phases[0].sample_hz  # （计算并保存中间变量）
    interval = 1.0 / sample_hz  # （计算并保存中间变量）
    transition_window_nm = transition_distance_m / 1852.0  # （计算并保存中间变量）

    if isinstance(backend, MockBackend):  # （判断条件并选择执行分支）
        raise BackendError("DME-trigger mode requires a live X-Plane backend because it depends on aircraft position.")  # （抛出异常提示错误）
    prime_observed_datarefs(backend, OBSERVED_DATAREFS)  # （执行具体处理逻辑）

    dme_provider = lambda: get_dme_distance_nm_geo(backend, dme_lat, dme_lon)  # （计算并保存中间变量）

    distance_provider = None  # （计算并保存中间变量）
    if runway_heading_deg is not None:  # （判断条件并选择执行分支）
        if threshold_local_x is not None and threshold_local_z is not None:  # （判断条件并选择执行分支）
            distance_provider = lambda: get_distance_and_lateral_offset(  # （计算并保存中间变量）
                backend, threshold_local_x, threshold_local_z, runway_heading_deg  # （执行具体处理逻辑）
            )  # （结束多行结构）
        elif threshold_lat is not None and threshold_lon is not None:  # （继续判断其他条件）
            distance_provider = lambda: get_distance_and_lateral_offset_geo(  # （计算并保存中间变量）
                backend, threshold_lat, threshold_lon, runway_heading_deg  # （执行具体处理逻辑）
            )  # （结束多行结构）

    print(f"Waiting for aircraft to enter first phase at <= {first_start:.2f} NM DME...")  # （输出运行状态或结果）
    while True:  # （在条件成立时循环执行）
        current_dme_nm = dme_provider()  # （计算并保存中间变量）
        if current_dme_nm <= first_start:  # （判断条件并选择执行分支）
            event_message = f"Entered downburst event: dme_distance_nm={current_dme_nm:.2f}"  # （计算并保存中间变量）
            if distance_provider is not None:  # （判断条件并选择执行分支）
                remaining_distance_m, lateral_offset_m = distance_provider()  # （计算并保存中间变量）
                event_message += (  # （计算并保存中间变量）
                    f", distance_to_threshold_m={remaining_distance_m:.1f}, "  # （计算并保存中间变量）
                    f"lateral_offset_m={lateral_offset_m:.1f}"  # （计算并保存中间变量）
                )  # （结束多行结构）
            print(event_message)  # （输出运行状态或结果）
            break  # （结束当前循环）
        time.sleep(wait_interval)  # （暂停等待采样或状态稳定）

    segment_samples: Dict[str, Dict[str, List[float]]] = {}  # （声明带类型提示的变量或字段）
    segment_notes: Dict[str, str] = {}  # （声明带类型提示的变量或字段）
    segment_scenarios: Dict[str, str] = {}  # （声明带类型提示的变量或字段）
    segment_entry_dme: Dict[str, float] = {}  # （声明带类型提示的变量或字段）
    segment_entry_distance: Dict[str, float] = {}  # （声明带类型提示的变量或字段）
    segment_entry_lateral: Dict[str, float] = {}  # （声明带类型提示的变量或字段）
    aggregate_samples = {name: [] for name in OBSERVED_DATAREFS}  # （计算并保存中间变量）
    aggregate_samples["dme_distance_nm"] = []  # （计算并保存中间变量）
    if distance_provider is not None:  # （判断条件并选择执行分支）
        aggregate_samples["distance_to_threshold_m"] = []  # （计算并保存中间变量）
        aggregate_samples["lateral_offset_m"] = []  # （计算并保存中间变量）
    last_segment_id: str | None = None  # （声明带类型提示的变量或字段）
    last_status_time = 0.0  # （计算并保存中间变量）

    while True:  # （在条件成立时循环执行）
        current_dme_nm = dme_provider()  # （计算并保存中间变量）
        if current_dme_nm <= last_end:  # （判断条件并选择执行分支）
            completion_message = f"[EVENT] Completed downburst event: dme_distance_nm={current_dme_nm:.2f}"  # （计算并保存中间变量）
            if distance_provider is not None:  # （判断条件并选择执行分支）
                remaining_distance_m, lateral_offset_m = distance_provider()  # （计算并保存中间变量）
                completion_message += (  # （计算并保存中间变量）
                    f", distance_to_threshold_m={remaining_distance_m:.1f}, "  # （计算并保存中间变量）
                    f"lateral_offset_m={lateral_offset_m:.1f}"  # （计算并保存中间变量）
                )  # （结束多行结构）
            print(completion_message)  # （输出运行状态或结果）
            break  # （结束当前循环）

        segment_id, note, scenario_id, active_values = compute_active_segment_dme(  # （计算并保存中间变量）
            phases, current_dme_nm, transition_window_nm  # （执行具体处理逻辑）
        )  # （结束多行结构）
        if segment_id is None or active_values is None:  # （判断条件并选择执行分支）
            time.sleep(interval)  # （暂停等待采样或状态稳定）
            continue  # （跳过本轮循环）

        remaining_distance_m = None  # （计算并保存中间变量）
        lateral_offset_m = None  # （计算并保存中间变量）
        if distance_provider is not None:  # （判断条件并选择执行分支）
            remaining_distance_m, lateral_offset_m = distance_provider()  # （计算并保存中间变量）

        apply_values(backend, active_values)  # （执行具体处理逻辑）
        if segment_id not in segment_samples:  # （判断条件并选择执行分支）
            segment_samples[segment_id] = {name: [] for name in OBSERVED_DATAREFS}  # （计算并保存中间变量）
            segment_samples[segment_id]["dme_distance_nm"] = []  # （计算并保存中间变量）
            if distance_provider is not None:  # （判断条件并选择执行分支）
                segment_samples[segment_id]["distance_to_threshold_m"] = []  # （计算并保存中间变量）
                segment_samples[segment_id]["lateral_offset_m"] = []  # （计算并保存中间变量）
            segment_notes[segment_id] = note  # （计算并保存中间变量）
            segment_scenarios[segment_id] = scenario_id  # （计算并保存中间变量）
            segment_entry_dme[segment_id] = current_dme_nm  # （计算并保存中间变量）
            if remaining_distance_m is not None and lateral_offset_m is not None:  # （判断条件并选择执行分支）
                segment_entry_distance[segment_id] = remaining_distance_m  # （计算并保存中间变量）
                segment_entry_lateral[segment_id] = lateral_offset_m  # （计算并保存中间变量）

        now = time.time()  # （计算并保存中间变量）
        if segment_id != last_segment_id:  # （判断条件并选择执行分支）
            event_message = f"[EVENT] Entered {segment_id}: dme_distance_nm={current_dme_nm:.2f}"  # （计算并保存中间变量）
            if remaining_distance_m is not None and lateral_offset_m is not None:  # （判断条件并选择执行分支）
                event_message += (  # （计算并保存中间变量）
                    f", distance_to_threshold_m={remaining_distance_m:.1f}, "  # （计算并保存中间变量）
                    f"lateral_offset_m={lateral_offset_m:.1f}"  # （计算并保存中间变量）
                )  # （结束多行结构）
            print(event_message)  # （输出运行状态或结果）
            last_segment_id = segment_id  # （计算并保存中间变量）
            last_status_time = now  # （计算并保存中间变量）
        elif (now - last_status_time) >= max(status_interval_seconds, 0.0):  # （继续判断其他条件）
            status_message = f"[STATUS] segment={segment_id}, dme_distance_nm={current_dme_nm:.2f}"  # （计算并保存中间变量）
            if remaining_distance_m is not None and lateral_offset_m is not None:  # （判断条件并选择执行分支）
                status_message += (  # （计算并保存中间变量）
                    f", distance_to_threshold_m={remaining_distance_m:.1f}, "  # （计算并保存中间变量）
                    f"lateral_offset_m={lateral_offset_m:.1f}"  # （计算并保存中间变量）
                )  # （结束多行结构）
            print(status_message)  # （输出运行状态或结果）
            last_status_time = now  # （计算并保存中间变量）

        observed_values: Dict[str, float] = {}  # （声明带类型提示的变量或字段）
        for name, dataref in OBSERVED_DATAREFS.items():  # （遍历数据并循环处理）
            value = float(backend.get_dataref(dataref))  # （计算并保存中间变量）
            observed_values[name] = value  # （计算并保存中间变量）
            segment_samples[segment_id][name].append(value)  # （执行具体处理逻辑）
            aggregate_samples[name].append(value)  # （执行具体处理逻辑）
        segment_samples[segment_id]["dme_distance_nm"].append(current_dme_nm)  # （执行具体处理逻辑）
        aggregate_samples["dme_distance_nm"].append(current_dme_nm)  # （执行具体处理逻辑）
        if remaining_distance_m is not None and lateral_offset_m is not None:  # （判断条件并选择执行分支）
            segment_samples[segment_id]["distance_to_threshold_m"].append(remaining_distance_m)  # （执行具体处理逻辑）
            segment_samples[segment_id]["lateral_offset_m"].append(lateral_offset_m)  # （执行具体处理逻辑）
            aggregate_samples["distance_to_threshold_m"].append(remaining_distance_m)  # （执行具体处理逻辑）
            aggregate_samples["lateral_offset_m"].append(lateral_offset_m)  # （执行具体处理逻辑）
        if telemetry_recorder is not None:  # （判断条件并选择执行分支）
            telemetry_recorder.maybe_record(  # （执行具体处理逻辑）
                scenario_id=scenario_id,  # （计算并保存中间变量）
                phase_id=segment_id,  # （计算并保存中间变量）
                note=note,  # （计算并保存中间变量）
                observed_values=observed_values,  # （计算并保存中间变量）
                active_values=active_values,  # （计算并保存中间变量）
                dme_distance_nm=current_dme_nm,  # （计算并保存中间变量）
                distance_to_threshold_m=remaining_distance_m,  # （计算并保存中间变量）
                lateral_offset_m=lateral_offset_m,  # （计算并保存中间变量）
            )  # （结束多行结构）
        time.sleep(interval)  # （暂停等待采样或状态稳定）

    progression_labels: List[str] = []  # （声明带类型提示的变量或字段）
    for idx, phase in enumerate(phases):  # （遍历数据并循环处理）
        progression_labels.append(phase.phase_id)  # （执行具体处理逻辑）
        if idx < len(phases) - 1:  # （判断条件并选择执行分支）
            progression_labels.append(f"{phase.phase_id}_to_{phases[idx + 1].phase_id}")  # （执行具体处理逻辑）

    results: List[Dict[str, float | str]] = []  # （声明带类型提示的变量或字段）
    for label in progression_labels:  # （遍历数据并循环处理）
        samples = segment_samples.get(label)  # （保存采样数据）
        if not samples:  # （判断条件并选择执行分支）
            continue  # （跳过本轮循环）
        summary: Dict[str, float | str] = {  # （保存结果汇总数据）
            "scenario_id": segment_scenarios[label],  # （多行结构中的一项）
            "phase_id": label,  # （多行结构中的一项）
            "note": segment_notes[label],  # （多行结构中的一项）
            "samples": len(samples["wind_now_y_msc"]),  # （多行结构中的一项）
            "segment_entry_dme_nm": round(segment_entry_dme[label], 2),  # （多行结构中的一项）
        }  # （结束多行结构）
        if label in segment_entry_distance and label in segment_entry_lateral:  # （判断条件并选择执行分支）
            summary["segment_entry_distance_m"] = round(segment_entry_distance[label], 1)  # （保存结果汇总数据）
            summary["segment_entry_lateral_offset_m"] = round(segment_entry_lateral[label], 1)  # （保存结果汇总数据）
        summary.update(summarize_series(samples["wind_now_y_msc"], "wind_now_y_msc"))  # （执行具体处理逻辑）
        summary.update(summarize_observed(samples))  # （执行具体处理逻辑）
        impact_score = compute_impact_score(summary)  # （计算并保存中间变量）
        summary["impact_score"] = impact_score  # （保存结果汇总数据）
        summary["response_classification"] = classify_aircraft_response(impact_score)  # （保存结果汇总数据）
        results.append(summary)  # （执行具体处理逻辑）
        print(summary)  # （输出运行状态或结果）

    final_summary: Dict[str, float | str] = {  # （声明带类型提示的变量或字段）
        "scenario_id": phases[0].scenario_id,  # （多行结构中的一项）
        "phase_id": "all_phases",  # （多行结构中的一项）
        "note": "Aggregate response across the full DME-triggered three-phase approach",  # （多行结构中的一项）
        "samples": len(aggregate_samples["wind_now_y_msc"]),  # （多行结构中的一项）
    }  # （结束多行结构）
    final_summary.update(summarize_series(aggregate_samples["wind_now_y_msc"], "wind_now_y_msc"))  # （执行具体处理逻辑）
    final_summary.update(summarize_observed(aggregate_samples))  # （执行具体处理逻辑）
    final_impact = compute_impact_score(final_summary)  # （计算并保存中间变量）
    final_summary["impact_score"] = final_impact  # （计算并保存中间变量）
    final_summary["response_classification"] = classify_aircraft_response(final_impact)  # （计算并保存中间变量）
    results.append(final_summary)  # （执行具体处理逻辑）
    print(final_summary)  # （输出运行状态或结果）
    return results  # （返回计算结果）


def main() -> None:  # （定义 main 函数）
    args = parse_args()  # （解析命令行参数）
    cases_path = Path(args.cases)  # （计算并保存中间变量）
    output_path = Path(args.output)  # （计算并保存中间变量）
    phase_scenario_path = Path(args.phase_scenario) if getattr(args, "phase_scenario", None) else None  # （计算并保存中间变量）
    telemetry_recorder = (  # （计算并保存中间变量）
        TelemetryRecorder(Path(args.telemetry_output), args.telemetry_interval_seconds)  # （执行具体处理逻辑）
        if args.telemetry_output  # （判断条件并选择执行分支）
        else None  # （执行具体处理逻辑）
    )  # （结束多行结构）

    backend = make_backend(args)  # （创建 X-Plane 通信后端）
    try:  # （开始异常捕获代码块）
        if args.watch_runway_distance is not None:  # （判断条件并选择执行分支）
            if args.runway_heading_deg is None:  # （判断条件并选择执行分支）
                raise SystemExit("--watch-runway-distance requires --runway-heading-deg")  # （抛出异常提示错误）
            local_pair_ok = args.threshold_local_x is not None and args.threshold_local_z is not None  # （计算并保存中间变量）
            geo_pair_ok = args.threshold_lat is not None and args.threshold_lon is not None  # （计算并保存中间变量）
            if not local_pair_ok and not geo_pair_ok:  # （判断条件并选择执行分支）
                raise SystemExit(  # （抛出异常提示错误）
                    "--watch-runway-distance requires either "  # （执行具体处理逻辑）
                    "(--threshold-local-x and --threshold-local-z) or "  # （执行具体处理逻辑）
                    "(--threshold-lat and --threshold-lon)."  # （执行具体处理逻辑）
                )  # （结束多行结构）
            watch_runway_distance(  # （执行具体处理逻辑）
                backend,  # （多行结构中的一项）
                args.watch_runway_distance,  # （多行结构中的一项）
                args.distance_poll_hz,  # （多行结构中的一项）
                args.runway_heading_deg,  # （多行结构中的一项）
                args.threshold_local_x,  # （多行结构中的一项）
                args.threshold_local_z,  # （多行结构中的一项）
                args.threshold_lat,  # （多行结构中的一项）
                args.threshold_lon,  # （多行结构中的一项）
                args.dme_lat,  # （多行结构中的一项）
                args.dme_lon,  # （多行结构中的一项）
            )  # （结束多行结构）
            return  # （返回计算结果）

        if args.test_dataref:  # （判断条件并选择执行分支）
            if args.test_value is None:  # （判断条件并选择执行分支）
                raise SystemExit("--test-dataref requires --test-value")  # （抛出异常提示错误）
            run_single_dataref_test(  # （执行具体处理逻辑）
                backend,  # （多行结构中的一项）
                args.test_dataref,  # （多行结构中的一项）
                args.test_value,  # （多行结构中的一项）
                args.watch_dataref,  # （多行结构中的一项）
                args.watch_seconds,  # （多行结构中的一项）
            )  # （结束多行结构）
            return  # （返回计算结果）

        if phase_scenario_path is not None:  # （判断条件并选择执行分支）
            if not phase_scenario_path.exists():  # （判断条件并选择执行分支）
                raise SystemExit(f"Phase scenario file not found: {phase_scenario_path}")  # （抛出异常提示错误）
            if args.distance_trigger and args.dme_trigger:  # （判断条件并选择执行分支）
                raise SystemExit("Choose either --distance-trigger or --dme-trigger, not both.")  # （抛出异常提示错误）
            if args.dme_trigger:  # （判断条件并选择执行分支）
                if args.dme_lat is None or args.dme_lon is None:  # （判断条件并选择执行分支）
                    raise SystemExit("DME-trigger mode requires --dme-lat and --dme-lon")  # （抛出异常提示错误）
                results = run_dme_phase_scenario(  # （计算并保存中间变量）
                    backend,  # （多行结构中的一项）
                    phase_scenario_path,  # （多行结构中的一项）
                    args.dme_lat,  # （多行结构中的一项）
                    args.dme_lon,  # （多行结构中的一项）
                    args.phase_transition_distance_m,  # （多行结构中的一项）
                    args.distance_poll_hz,  # （多行结构中的一项）
                    args.status_interval_seconds,  # （多行结构中的一项）
                    args.runway_heading_deg,  # （多行结构中的一项）
                    args.threshold_local_x,  # （多行结构中的一项）
                    args.threshold_local_z,  # （多行结构中的一项）
                    args.threshold_lat,  # （多行结构中的一项）
                    args.threshold_lon,  # （多行结构中的一项）
                    telemetry_recorder,  # （多行结构中的一项）
                )  # （结束多行结构）
            elif args.distance_trigger:  # （继续判断其他条件）
                if args.runway_heading_deg is None:  # （判断条件并选择执行分支）
                    raise SystemExit("Distance-trigger mode requires --runway-heading-deg")  # （抛出异常提示错误）
                local_pair_ok = args.threshold_local_x is not None and args.threshold_local_z is not None  # （计算并保存中间变量）
                geo_pair_ok = args.threshold_lat is not None and args.threshold_lon is not None  # （计算并保存中间变量）
                if not local_pair_ok and not geo_pair_ok:  # （判断条件并选择执行分支）
                    raise SystemExit(  # （抛出异常提示错误）
                        "Distance-trigger mode requires either "  # （执行具体处理逻辑）
                        "(--threshold-local-x and --threshold-local-z) or "  # （执行具体处理逻辑）
                        "(--threshold-lat and --threshold-lon)."  # （执行具体处理逻辑）
                    )  # （结束多行结构）
                results = run_distance_phase_scenario(  # （计算并保存中间变量）
                    backend,  # （多行结构中的一项）
                    phase_scenario_path,  # （多行结构中的一项）
                    args.phase_transition_distance_m,  # （多行结构中的一项）
                    args.runway_heading_deg,  # （多行结构中的一项）
                    args.distance_poll_hz,  # （多行结构中的一项）
                    args.status_interval_seconds,  # （多行结构中的一项）
                    args.threshold_local_x,  # （多行结构中的一项）
                    args.threshold_local_z,  # （多行结构中的一项）
                    args.threshold_lat,  # （多行结构中的一项）
                    args.threshold_lon,  # （多行结构中的一项）
                    telemetry_recorder,  # （多行结构中的一项）
                )  # （结束多行结构）
            else:  # （处理默认分支）
                results = run_phase_scenario(backend, phase_scenario_path, args.phase_transition_seconds)  # （计算并保存中间变量）
            write_results(output_path, results)  # （执行具体处理逻辑）
            print(f"Saved results to {output_path.resolve()}")  # （输出运行状态或结果）
            return  # （返回计算结果）

        if not cases_path.exists():  # （判断条件并选择执行分支）
            raise SystemExit(f"Case file not found: {cases_path}")  # （抛出异常提示错误）

        results = []  # （计算并保存中间变量）
        for case in load_cases(cases_path):  # （遍历数据并循环处理）
            print(f"Running {case.case_id} ...")  # （输出运行状态或结果）
            apply_case(backend, case)  # （执行具体处理逻辑）
            time.sleep(case.settle_seconds)  # （暂停等待采样或状态稳定）
            observed_samples = sample_observed_datarefs(  # （计算并保存中间变量）
                backend, case.sample_seconds, case.sample_hz, OBSERVED_DATAREFS  # （执行具体处理逻辑）
            )  # （结束多行结构）
            vertical_wind_samples = observed_samples["wind_now_y_msc"]  # （计算并保存中间变量）
            summary = summarize(case, vertical_wind_samples)  # （保存结果汇总数据）
            summary.update(summarize_observed(observed_samples))  # （执行具体处理逻辑）
            impact_score = compute_impact_score(summary)  # （计算并保存中间变量）
            summary["impact_score"] = impact_score  # （保存结果汇总数据）
            summary["response_classification"] = classify_aircraft_response(impact_score)  # （保存结果汇总数据）
            results.append(summary)  # （执行具体处理逻辑）
            print(summary)  # （输出运行状态或结果）
        write_results(output_path, results)  # （执行具体处理逻辑）
        print(f"Saved results to {output_path.resolve()}")  # （输出运行状态或结果）
    finally:  # （执行最终清理逻辑）
        if telemetry_recorder is not None:  # （判断条件并选择执行分支）
            telemetry_recorder.close()  # （执行具体处理逻辑）
        backend.close()  # （执行具体处理逻辑）


if __name__ == "__main__":  # （脚本直接运行时进入主程序）
    main()  # （执行具体处理逻辑）
