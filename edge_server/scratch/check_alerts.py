import asyncio
from models.database import async_session
from sqlalchemy import select
import sys
import os

# Add current directory to path
sys.path.append(os.getcwd())

async def check():
    try:
        from models.alert import Alert
        async with async_session() as db:
            res = await db.execute(select(Alert).order_by(Alert.created_at.desc()).limit(10))
            alerts = list(res.scalars())
            if not alerts:
                print("No alerts found in database.")
            for a in alerts:
                print(f"Alert: {a.threat_type} | Severity: {a.severity} | Device: {a.device_id} | Time: {a.created_at}")
                print(f"  Message: {a.message}")
                print("-" * 20)
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(check())
