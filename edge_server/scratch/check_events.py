import asyncio
from models.database import async_session
from sqlalchemy import select
import sys
import os

sys.path.append(os.getcwd())

async def check():
    try:
        from models.behavior_event import BehaviorEvent
        async with async_session() as db:
            res = await db.execute(select(BehaviorEvent).order_by(BehaviorEvent.received_at.desc()).limit(20))
            events = list(res.scalars())
            if not events:
                print("No events found.")
            for e in events:
                print(f"ID: {e.id} | Type: {e.event_type} | Pkg: {e.package_name} | Data Preview: {str(e.data)[:50]}")
                # Note: package_name is encrypted, but I enabled plaintext fallback
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(check())
