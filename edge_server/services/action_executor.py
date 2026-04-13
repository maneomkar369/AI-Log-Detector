"""
Action Executor
================
Executes threat neutralization actions on target Android devices
via ADB commands. All actions are audit-logged.
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional

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
            "target": target_package or str(target_uid),
            "timestamp": datetime.utcnow().isoformat(),
            "success": False,
            "output": "",
        }

        try:
            if action == "kill_process" and target_package:
                cmd = f"{self.adb} -s {device_id} shell am force-stop {target_package}"
                result["output"] = await self._run(cmd)
                result["success"] = True

            elif action == "block_network" and target_uid:
                cmd = (
                    f"{self.adb} -s {device_id} shell "
                    f"iptables -A OUTPUT -m owner --uid-owner {target_uid} -j DROP"
                )
                result["output"] = await self._run(cmd)
                result["success"] = True

            elif action == "quarantine_app" and target_package:
                cmd = (
                    f"{self.adb} -s {device_id} shell "
                    f"pm disable-user --user 0 {target_package}"
                )
                result["output"] = await self._run(cmd)
                result["success"] = True

            elif action == "lock_device":
                cmd = f"{self.adb} -s {device_id} shell input keyevent 26"
                result["output"] = await self._run(cmd)
                result["success"] = True

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
            "ACTION %s | device=%s target=%s success=%s",
            action, device_id, result["target"], result["success"],
        )
        return result

    async def execute_all_actions(
        self,
        actions: list,
        device_id: str,
        target_package: Optional[str] = None,
        target_uid: Optional[int] = None,
    ) -> list:
        """Execute multiple actions sequentially with audit trail."""
        results = []
        for action in actions:
            if action == "notify":
                continue  # Notifications handled separately
            r = await self.execute_action(
                action, device_id, target_package, target_uid
            )
            results.append(r)
        return results

    @staticmethod
    async def _run(cmd: str) -> str:
        """Run a shell command asynchronously."""
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        output = stdout.decode().strip()
        if stderr:
            output += f" [stderr: {stderr.decode().strip()}]"
        return output
