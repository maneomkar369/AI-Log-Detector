import asyncio
from models.database import async_session
from sqlalchemy import select
import sys
import os

sys.path.append(os.getcwd())

async def check():
    try:
        from models.device import Device
        async with async_session() as db:
            res = await db.execute(select(Device))
            devices = list(res.scalars())
            if not devices:
                print("No devices found.")
            for d in devices:
                print(f"Device: {d.id}")
                print(f"  Samples: {d.baseline_sample_count}")
                print(f"  Distance Mean: {d.distance_mean:.2f}")
                print(f"  Distance Std: {d.distance_std:.2f}")
                print(f"  CUSUM Pos: {d.cusum_pos:.2f} | Neg: {d.cusum_neg:.2f}")
                print("-" * 20)
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(check())
