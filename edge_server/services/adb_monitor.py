"""
ADB Connection Monitor
======================
Monitors ADB connection status and handles reconnection logic.
"""

import asyncio
import logging
import subprocess
import time
from typing import Dict, Set, Optional

from config import settings
from services.action_executor import ActionExecutor

logger = logging.getLogger(__name__)


class AdbConnectionMonitor:
    """Monitors ADB connection status and handles automatic reconnection."""

    def __init__(self, action_executor: ActionExecutor):
        self.action_executor = action_executor
        self.connected_devices: Set[str] = set()
        self.last_check_time: float = 0
        self.check_interval: int = 30  # Check every 30 seconds
        self.monitoring: bool = False

    async def start_monitoring(self) -> None:
        """Start monitoring ADB connections."""
        self.monitoring = True
        logger.info("ADB connection monitor started")
        
        while self.monitoring:
            try:
                await self._check_connections()
                await asyncio.sleep(self.check_interval)
            except Exception as e:
                logger.error("Error in ADB connection monitoring: %s", e)
                await asyncio.sleep(self.check_interval)

    def stop_monitoring(self) -> None:
        """Stop monitoring ADB connections."""
        self.monitoring = False
        logger.info("ADB connection monitor stopped")

    async def _check_connections(self) -> None:
        """Check current ADB connection status."""
        try:
            current_devices = await self._list_connected_devices()
            
            # Check for new connections
            new_devices = current_devices - self.connected_devices
            if new_devices:
                for device in new_devices:
                    logger.info("ADB device connected: %s", device)
                    
            # Check for disconnections
            disconnected_devices = self.connected_devices - current_devices
            if disconnected_devices:
                for device in disconnected_devices:
                    logger.warning("ADB device disconnected: %s", device)
                    await self._handle_disconnection(device)
            
            # Update connected devices set
            self.connected_devices = current_devices
            self.last_check_time = time.time()
            
        except Exception as e:
            logger.error("Failed to check ADB connections: %s", e)

    async def _list_connected_devices(self) -> Set[str]:
        """Get list of currently connected ADB devices."""
        try:
            # Run adb devices command
            cmd = [self.action_executor.adb, "devices"]
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode != 0:
                logger.warning("ADB command failed: %s", stderr.decode().strip())
                return set()
            
            # Parse device list
            devices = set()
            lines = stdout.decode().strip().split('\n')
            
            # Skip first line ("List of devices attached")
            for line in lines[1:]:
                if line.strip() and '\t' in line:
                    serial, status = line.split('\t')
                    if status.strip() == 'device':
                        devices.add(serial.strip())
            
            return devices
            
        except Exception as e:
            logger.error("Failed to list ADB devices: %s", e)
            return set()

    async def _handle_disconnection(self, device_serial: str) -> None:
        """Handle ADB device disconnection."""
        logger.warning("Handling disconnection for device: %s", device_serial)
        
        # Log the disconnection event
        try:
            # This would typically be logged to the database
            logger.info("ADB disconnection event recorded for device: %s", device_serial)
        except Exception as e:
            logger.error("Failed to log disconnection event: %s", e)
        
        # Attempt to reconnect if we have the device IP
        await self._attempt_reconnection(device_serial)

    async def _attempt_reconnection(self, device_serial: str) -> None:
        """Attempt to reconnect to a disconnected device."""
        logger.info("Attempting to reconnect to device: %s", device_serial)
        
        try:
            # Try to get device IP if it was previously connected via network
            # This is a simplified approach - in practice, you might store this information
            device_ip = await self._get_device_ip(device_serial)
            
            if device_ip:
                # Try to connect via TCP/IP
                connect_cmd = [self.action_executor.adb, "connect", device_ip]
                process = await asyncio.create_subprocess_exec(
                    *connect_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                
                stdout, stderr = await process.communicate()
                
                if process.returncode == 0:
                    logger.info("Successfully reconnected to device %s at %s", device_serial, device_ip)
                else:
                    logger.warning("Failed to reconnect to device %s: %s", device_serial, stderr.decode().strip())
            else:
                logger.info("No IP address available for device %s, cannot attempt reconnection", device_serial)
                
        except Exception as e:
            logger.error("Error during reconnection attempt for device %s: %s", device_serial, e)

    async def _get_device_ip(self, device_serial: str) -> Optional[str]:
        """Get device IP address if connected via network."""
        try:
            # Try to get device IP from ADB properties
            cmd = [self.action_executor.adb, "-s", device_serial, "shell", "ip", "route"]
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                output = stdout.decode().strip()
                # Look for default route which typically contains the device IP
                import re
                match = re.search(r'default via [\d.]+ dev wlan\d+ src ([\d.]+)', output)
                if match:
                    return match.group(1)
            
            return None
            
        except Exception as e:
            logger.debug("Could not get IP for device %s: %s", device_serial, e)
            return None


# Global instance
adb_monitor: Optional[AdbConnectionMonitor] = None
