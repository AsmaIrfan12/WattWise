import sys
import os
import asyncio
from datetime import datetime, timedelta, date

sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'backend'))

async def main():
    try:
        from app.scheduler import aggregate_hourly, aggregate_daily
    except ImportError as e:
        print(f"Error importing aggregators: {e}")
        return

    days = 2
    now = datetime.utcnow()
    
    print(f"Triggering {days} days of hourly aggregations backward...")
    for h in range(days * 24, 0, -1):
        target = now - timedelta(hours=h)
        print(f"  Hour: {target.strftime('%Y-%m-%d %H:00')}...")
        await aggregate_hourly(target_time=target)
        
    print(f"Triggering {days} days of daily aggregations backward...")
    for d in range(days, -1, -1):
        target = (now - timedelta(days=d)).date()
        print(f"  Day: {target}...")
        await aggregate_daily(target_date=target)
        
    print("Done!")

if __name__ == '__main__':
    asyncio.run(main())
