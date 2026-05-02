"""
Database Cleanup Service
========================
Handles automated cleanup of old data to prevent database growth.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models.database import async_session

logger = logging.getLogger(__name__)


class DatabaseCleanupService:
    """Service for cleaning up old database records."""

    def __init__(self):
        self.running = False

    async def cleanup_old_data(self) -> None:
        """Clean up data older than the retention period."""
        try:
            async with async_session() as session:
                cutoff_date = datetime.utcnow() - timedelta(days=settings.data_retention_days)
                
                # Clean up old behavior events
                deleted_events = await self._delete_old_records(
                    session, "behavior_events", cutoff_date
                )
                
                # Clean up old alerts
                deleted_alerts = await self._delete_old_records(
                    session, "alerts", cutoff_date
                )
                
                # Clean up old device baselines (keep recent ones)
                deleted_baselines = await self._delete_old_records(
                    session, "device_baselines", cutoff_date
                )
                
                await session.commit()
                
                logger.info(
                    "Database cleanup completed: %d events, %d alerts, %d baselines deleted",
                    deleted_events,
                    deleted_alerts,
                    deleted_baselines
                )
                
        except Exception as e:
            logger.error("Database cleanup failed: %s", str(e))
            raise

    async def _delete_old_records(
        self, 
        session: AsyncSession, 
        table_name: str, 
        cutoff_date: datetime
    ) -> int:
        """Delete records older than cutoff date from specified table."""
        try:
            result = await session.execute(
                text(f"DELETE FROM {table_name} WHERE timestamp < :cutoff_date"),
                {"cutoff_date": cutoff_date}
            )
            return result.rowcount
        except Exception as e:
            logger.warning("Failed to clean up %s: %s", table_name, str(e))
            return 0

    async def start_cleanup_scheduler(self) -> None:
        """Start the scheduled cleanup job."""
        try:
            from apscheduler.schedulers.asyncio import AsyncIOScheduler
            from apscheduler.triggers.cron import CronTrigger
            
            scheduler = AsyncIOScheduler()
            
            # Run cleanup daily at 2 AM
            scheduler.add_job(
                self.cleanup_old_data,
                CronTrigger(hour=2, minute=0),
                id='database_cleanup',
                name='Database Cleanup Job',
                misfire_grace_time=3600  # 1 hour grace period
            )
            
            scheduler.start()
            self.running = True
            
            logger.info("Database cleanup scheduler started - will run daily at 2 AM")
            
        except ImportError:
            logger.warning("APScheduler not available - database cleanup will not run automatically")
        except Exception as e:
            logger.error("Failed to start cleanup scheduler: %s", str(e))


# Global instance
db_cleanup_service = DatabaseCleanupService()
