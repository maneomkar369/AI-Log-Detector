"""
Action Executor
================
Executes threat neutralization actions on target Android devices
via ADB commands. All actions are audit-logged.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)


class ActionExecutor:
    """
    Executes approved threat neutralization actions.

    Supported actions:
    - kill_process   → adb shell am force-stop <package>
    - block_network  → adb shell iptables -A OUTPUT -m owner --uid-owner <uid> -j DROP
    - quarantine_app → adb shell pm disable-user <package>
    - lock_device    → adb shell input keyevent 26 (power button)
    """

    def __init__(self, adb_path: str = "adb"):
        self.adb = adb_path
        self.audit_log: list = []

    async def execute_action(
        self,
        action: str,
        device_id: str,
        target_package: Optional[str] = None,
        target_uid: Optional[int] = None,
        resolved_device_id: Optional[str] = None,
    ) -> dict:
        """
        Execute a single neutralization action.

        Parameters
        ----------
        action : str
            One of: kill_process, block_network, quarantine_app, lock_device
        device_id : str
            ADB device serial or identifier.
        target_package : str, optional
            Target app package name.
        target_uid : int, optional
            Target app UID (for iptables).

        Returns
        -------
        dict
            {success: bool, action: str, output: str, timestamp: str}
        """
        result = {
            "action": action,
            "device_id": device_id,
            "target": target_package or (str(target_uid) if target_uid is not None else None),
            "timestamp": datetime.utcnow().isoformat(),
            "success": False,
            "output": "",
        }

        try:
            effective_device_id = resolved_device_id or device_id
            if action != "notify" and resolved_device_id is None:
                effective_device_id = await self._resolve_device_id(device_id)

            if effective_device_id != device_id:
                result["resolved_device_id"] = effective_device_id

            if action == "kill_process" and target_package:
                cmd = f"{self.adb} -s {effective_device_id} shell am force-stop {target_package}"
                result["success"], result["output"] = await self._run(cmd)

            elif action == "block_network" and target_uid is not None:
                cmd = (
                    f"{self.adb} -s {effective_device_id} shell "
                    f"iptables -A OUTPUT -m owner --uid-owner {target_uid} -j DROP"
                )
                result["success"], result["output"] = await self._run(cmd)

            elif action == "quarantine_app" and target_package:
                cmd = (
                    f"{self.adb} -s {effective_device_id} shell "
                    f"pm disable-user --user 0 {target_package}"
                )
                result["success"], result["output"] = await self._run(cmd)

            elif action == "lock_device":
                cmd = f"{self.adb} -s {effective_device_id} shell input keyevent 26"
                result["success"], result["output"] = await self._run(cmd)

            elif action == "notify":
                # Notification-only action, no ADB command needed
                result["output"] = "Notification sent via WebSocket"
                result["success"] = True

            else:
                result["output"] = f"Unknown or incomplete action: {action}"

        except Exception as e:
            result["output"] = f"Error: {str(e)}"
            logger.error(
                "Action execution failed: %s on %s — %s",
                action, device_id, e,
            )

        # Audit log
        self.audit_log.append(result)
        logger.info(
            "ACTION %s | device=%s resolved=%s target=%s success=%s",
            action,
            device_id,
            result.get("resolved_device_id", device_id),
            result["target"],
            result["success"],
        )
        return result

    async def _resolve_device_id(self, requested_device_id: str) -> str:
        """
        Resolve the target device for ADB commands.

        Alerts are keyed by app-level Android IDs, which may differ from ADB serials.
        If the requested ID is not in `adb devices` and exactly one device is attached,
        fallback to that sole attached serial.
        """
        devices = await self._list_adb_devices()
        if not devices:
            return requested_device_id

        if requested_device_id in devices:
            return requested_device_id

        matched_by_android_id = await self._find_serial_by_android_id(
            requested_device_id,
            devices,
        )
        if matched_by_android_id:
            logger.info(
                "Resolved Android ID %s to adb serial %s",
                requested_device_id,
                matched_by_android_id,
            )
            return matched_by_android_id

        serial_map = await self._build_serial_map(devices)
        unique_hardware_ids = {value for value in serial_map.values() if value}
        if len(devices) > 1 and len(unique_hardware_ids) == 1:
            preferred = self._prefer_wireless_serial(devices)
            logger.warning(
                "Requested device id %s not found; multiple serials map to same physical device, using %s",
                requested_device_id,
                preferred,
            )
            return preferred

        if len(devices) == 1:
            fallback = devices[0]
            logger.warning(
                "Requested device id %s not found in adb list; using fallback serial %s",
                requested_device_id,
                fallback,
            )
            return fallback

        logger.warning(
            "Requested device id %s not found and multiple adb devices are connected: %s",
            requested_device_id,
            ",".join(devices),
        )
        return requested_device_id

    async def _find_serial_by_android_id(self, requested_device_id: str, devices: list[str]) -> Optional[str]:
        """Attempt to map app Android ID to one connected adb serial."""
        normalized_requested = requested_device_id.strip().lower()
        if not normalized_requested:
            return None

        matches: list[str] = []
        for serial in devices:
            android_id = await self._read_android_id(serial)
            if android_id and android_id.lower() == normalized_requested:
                matches.append(serial)

        if not matches:
            return None

        return self._prefer_wireless_serial(matches)

    async def _build_serial_map(self, devices: list[str]) -> dict[str, Optional[str]]:
        """Map adb serial to stable hardware serial (ro.serialno)."""
        mapping: dict[str, Optional[str]] = {}
        for serial in devices:
            mapping[serial] = await self._read_hardware_serial(serial)
        return mapping

    async def _read_android_id(self, serial: str) -> Optional[str]:
        output = await self._run_quick_command(
            f"{self.adb} -s {serial} shell settings get secure android_id",
            timeout_seconds=3.0,
        )
        if not output:
            return None

        value = output.strip().splitlines()[0].strip()
        if not value or value.lower() == "null":
            return None
        return value

    async def _read_hardware_serial(self, serial: str) -> Optional[str]:
        output = await self._run_quick_command(
            f"{self.adb} -s {serial} shell getprop ro.serialno",
            timeout_seconds=3.0,
        )
        if not output:
            return None

        value = output.strip().splitlines()[0].strip()
        if not value or value.lower() in {"unknown", "null"}:
            return None
        return value

    @staticmethod
    def _prefer_wireless_serial(devices: list[str]) -> str:
        """Prefer tcpip serials (`ip:port`) when available."""
        for serial in devices:
            if ":" in serial:
                return serial
        return devices[0]

    async def _run_quick_command(self, cmd: str, timeout_seconds: float) -> Optional[str]:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            logger.warning("Timed out running command: %s", cmd)
            return None

        if proc.returncode != 0:
            err = stderr.decode().strip()
            logger.debug("Command failed (%s): %s", proc.returncode, err)
            return None

        return stdout.decode()

    async def _list_adb_devices(self) -> list[str]:
        """Return connected ADB serials in `device` state."""
        proc = await asyncio.create_subprocess_shell(
            f"{self.adb} devices",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            logger.warning("Failed to list adb devices: %s", stderr.decode().strip())
            return []

        devices: list[str] = []
        for line in stdout.decode().splitlines():
            line = line.strip()
            if not line or line.startswith("List of devices attached"):
                continue
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "device":
                devices.append(parts[0])
        return devices

    async def execute_all_actions(
        self,
        actions: list,
        device_id: str,
        target_package: Optional[str] = None,
        target_uid: Optional[int] = None,
    ) -> list:
        """Execute multiple actions sequentially with audit trail."""
        results = []
        resolved_device_id = await self._resolve_device_id(device_id)
        for action in actions:
            action_name, action_target_package, action_target_uid = self._parse_action(action)
            resolved_package = action_target_package or target_package
            resolved_uid = action_target_uid if action_target_uid is not None else target_uid

            if not action_name:
                continue

            if action_name == "notify":
                continue  # Notifications handled separately

            r = await self.execute_action(
                action_name,
                device_id,
                resolved_package,
                resolved_uid,
                resolved_device_id=resolved_device_id,
            )
            results.append(r)
        return results

    @staticmethod
    def _parse_action(action: Any) -> tuple[str, Optional[str], Optional[int]]:
        """Parse action payloads from legacy strings or object-based plans."""
        if isinstance(action, str):
            return action.strip(), None, None

        if isinstance(action, dict):
            name = str(action.get("name", action.get("action", ""))).strip()

            target_package_raw = action.get("targetPackage", action.get("target_package"))
            target_package = (
                str(target_package_raw).strip()
                if target_package_raw is not None and str(target_package_raw).strip()
                else None
            )

            target_uid_raw = action.get("targetUid", action.get("target_uid"))
            try:
                target_uid = int(target_uid_raw) if target_uid_raw is not None else None
            except (TypeError, ValueError):
                target_uid = None

            return name, target_package, target_uid

        return "", None, None

    @staticmethod
    async def _run(cmd: str) -> tuple[bool, str]:
        """Run a shell command asynchronously and report success by return code."""
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        output = stdout.decode().strip()
        if stderr:
            output += f" [stderr: {stderr.decode().strip()}]"

        if proc.returncode != 0:
            if not output:
                output = f"Command failed with exit code {proc.returncode}"
            return False, output

        return True, (output or "Command executed successfully")
