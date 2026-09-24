"""Модели удалённых плат."""

from app.models.devices.device import Device
from app.models.devices.device_command import DeviceCommand
from app.models.devices.diagnostic import DeviceDiagnosticEvent, DeviceDiagnosticSample, DeviceInputTestLog

__all__ = ["Device", "DeviceCommand", "DeviceDiagnosticSample", "DeviceDiagnosticEvent", "DeviceInputTestLog"]
