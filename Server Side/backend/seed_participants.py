import asyncio
import csv
import logging
import random
import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import engine, get_db, AsyncSessionLocal
from app.models import User, Home, Device
from app.routers.auth import _hash_password

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("db_seed")

APPLIANCE_KEYS = ["kettle", "microwave", "washing_machine", "dishwasher", "toaster", "airfryer"]

async def upsert_admin(session: AsyncSession):
    """Ensure the system admin account exists and matches .env credentials."""
    email = settings.ADMIN_EMAIL
    pwd = settings.ADMIN_PASSWORD
    
    if not email or not pwd:
        log.warning("ADMIN_EMAIL or ADMIN_PASSWORD not set in config — skipping admin upsert")
        return

    hashed = _hash_password(pwd)
    result = await session.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    
    if user:
        log.info(f"Updating existing Admin user: {email}")
        await session.execute(
            update(User)
            .where(User.id == user.id)
            .values(password_hash=hashed, is_admin=True)
        )
    else:
        log.info(f"Creating fresh Admin user: {email}")
        new_admin = User(
            name="Suhas Devmane",
            email=email,
            password_hash=hashed,
            is_admin=True,
            notifications_enabled=True
        )
        session.add(new_admin)
    
    await session.commit()

async def seed_db():
    log.info("Connecting to database and starting seed process...")
    async with AsyncSessionLocal() as session:
        # 0. Sync Admin
        await upsert_admin(session)

        # 1. Load CSV
        with open("participants.csv", "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        # Manually inject Asma Irfan as "row" dictionary
        asma_row = {
            "Name": "Asma Irfan",
            "Email": "IrfanA1@cardiff.ac.uk",
            "Password": "WattWise2024!",
            "Address": "Cardiff University, Abacws Building",
            "Location": "Cardiff",
            "Occupants": "1",
            "HomeType": "flat",
            "Devices": "4",
        }
        rows.append(asma_row)

        inserted_users = 0
        inserted_homes = 0
        inserted_devices = 0

        for row in rows:
            email = row["Email"].strip()
            pwd = row["Password"].strip()
            hashed_pwd = _hash_password(pwd)
            
            # check if exists
            result = await session.execute(select(User).where(User.email == email))
            existing_user = result.scalar_one_or_none()
            
            if existing_user:
                log.info(f"Syncing existing user credentials: {email}")
                await session.execute(
                    update(User)
                    .where(User.id == existing_user.id)
                    .values(password_hash=hashed_pwd)
                )
                user_id = existing_user.id
            else:
                log.info(f"Creating fresh user: {email}")
                user = User(
                    name=row["Name"].strip(),
                    email=email,
                    password_hash=hashed_pwd,
                    notifications_enabled=True,
                    is_admin=False
                )
                session.add(user)
                await session.flush()  # to get user.id
                user_id = user.id
                inserted_users += 1

            # 2. Ensure Home exists (get or create)
            home_result = await session.execute(select(Home).where(Home.user_id == user_id))
            home = home_result.scalar_one_or_none()
            
            if not home:
                home = Home(
                    user_id=user_id,
                    home_name=f"{row['Name'].split(' ')[0]}'s Home",
                    address=row.get("Address", "").strip(),
                    location_desc=row.get("Location", "").strip(),
                    num_occupants=int(row.get("Occupants", "1")),
                    home_type=row.get("HomeType", "other").strip()
                )
                session.add(home)
                await session.flush()
                inserted_homes += 1
            
            # 3. Handle Devices
            num_devices_to_add = 0
            try:
                num_devices_csv = int(row.get("Devices", "0"))
                num_devices_to_add = max(num_devices_csv, 3) # Force at least 3
            except ValueError:
                num_devices_to_add = 3

            # Check existing devices
            dev_result = await session.execute(select(Device).where(Device.home_id == home.id))
            existing_devs = dev_result.scalars().all()
            
            if len(existing_devs) < 3:
                # Add enough devices to reach at least 3
                num_to_add = max(3 - len(existing_devs), num_devices_to_add - len(existing_devs))
                existing_keys = {d.appliance_key for d in existing_devs}
                available_keys = [k for k in APPLIANCE_KEYS if k not in existing_keys]
                
                chosen_appliances = random.sample(available_keys, min(num_to_add, len(available_keys)))
                for ak in chosen_appliances:
                    dev = Device(
                        home_id=home.id,
                        name=ak.replace("_", " ").title(),
                        appliance_key=ak,
                        entity_id=f"sensor.{ak}_{uuid.uuid4().hex[:6]}",
                        device_type="appliance"
                    )
                    session.add(dev)
                    inserted_devices += 1

        await session.commit()
        log.info(f"✨ Seed & Sync Complete! Added {inserted_users} new users, synced passwords for all.")

    # Explicitly dispose the engine so aiomysql connection cleanup
    # happens before asyncio.run() closes the event loop (Python 3.12+).
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(seed_db())
