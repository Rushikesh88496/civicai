"""Development seed script for CivicAgent — reference data only (Part 31).

The platform ships GENUINELY EMPTY: zero complaints, zero hotspots, zero
predictions, zero analytics. This script only seeds REFERENCE data:

- Roles: CITIZEN, OFFICER, WARD_REPRESENTATIVE, FIELD_WORKER, ADMIN, SUPER_ADMIN
- Departments for the worker/representative links
- DEMO-critical reference locations (illustrative facility placeholders, NOT
  operational incidents)
- The Citizen AI Assistant knowledge base
- A single bootstrap ``admin@example.com`` SUPER_ADMIN account (documented
  login for the super-admin panel)
- 25 development FIELD_WORKER accounts (ward distribution 6/6/6/7 across
  WARD-1 .. WARD-4) with realistic municipal jobs, skills and registered base
  locations across Pune, Maharashtra, India — created idempotently by email and
  re-pointed to their Pune base on re-runs
- 4 development WARD_REPRESENTATIVE accounts (one per ward) — created
  idempotently by email

The four reference wards (WARD 1 .. WARD 4) and their boundaries arrive via the
``31a2b3c4d5e6`` alembic migration — NOT from this script — so a fresh deploy
always has functional sign-up wards.

Usage (from backend/):
    .venv\\Scripts\\python seed.py              # seed reference data (idempotent)
    .venv\\Scripts\\python seed.py --reset       # wipe demo/operational data first

``--reset`` delegates to ``scripts.reset_dev_data``: it removes all demo users,
complaints, work orders, infra assets, ML rows and legacy demo wards (W-001..W-003),
keeping reference data + the bootstrap admin. NEVER run against production.
"""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy import func, select

from app.core.security import hash_password
from app.db.session import async_session_factory, engine
from app.models import (
    CriticalLocation,
    Department,
    FieldWorker,
    Role,
    User,
    UserProfile,
    Ward,
    WardRepresentative,
)
from app.models.enums import (
    CriticalLocationCategory,
    RepresentativeStatus,
    RoleName,
    WorkerStatus,
)

# The bootstrap super-admin shares the documented demo password. Used by the
# Super-Admin Panel login. Change it after first sign-in in a real deployment.
_DEMO_PASSWORD = "CivicAgent#2026"
_BOOTSTRAP_ADMIN_EMAIL = "admin@example.com"

# Shared dev password for all seeded field workers (documented, Part 33).
_WORKER_PASSWORD = "FieldWorker#2026"

# Shared dev password for seeded ward representatives.
_REP_PASSWORD = "1234#Rushi"

# 4 ward representatives — one per ward (WARD-1 .. WARD-4).
_WARD_REPRESENTATIVES: list[dict] = [
    {
        "name": "Kobu Jadav",
        "email": "kobu.jadav@example.com",
        "ward_code": "WARD-1",
        "title": "Ward 1 Representative",
    },
    {
        "name": "Dheeraj Borse",
        "email": "dheeraj.borse@example.com",
        "ward_code": "WARD-2",
        "title": "Ward 2 Representative",
    },
    {
        "name": "Rushikesh Tapsale",
        "email": "rushikesh.tapsale@example.com",
        "ward_code": "WARD-3",
        "title": "Ward 3 Representative",
    },
    {
        "name": "Rajveer Rajput",
        "email": "rajveer.rajput@example.com",
        "ward_code": "WARD-4",
        "title": "Ward 4 Representative",
    },
]

_ROLES: list[tuple[RoleName, str]] = [
    (RoleName.CITIZEN, "Citizen who submits and tracks complaints."),
    (RoleName.OFFICER, "Municipal officer who reviews complaints and approves work."),
    (RoleName.WARD_REPRESENTATIVE, "Elected/assigned representative for a ward."),
    (RoleName.FIELD_WORKER, "Field worker who executes assigned work orders."),
    (RoleName.ADMIN, "System administrator with full management rights."),
    (RoleName.SUPER_ADMIN, "Super administrator with panel management rights."),
]

# (name, category, lat, lon, address) — illustrative REFERENCE facility
# placeholders around Hyderabad, India. They are DATAPOINTS on the civic map,
# NOT operational incidents; ``is_demo=True`` keeps them clearly labelled.
_DEMO_CRITICAL_LOCATIONS: list[tuple[str, CriticalLocationCategory, float, float, str | None]] = [
    ("City Central Hospital", CriticalLocationCategory.HOSPITAL, 17.4350, 78.3890, "Riverside"),
    ("Riverside Primary School", CriticalLocationCategory.SCHOOL, 17.4310, 78.3870, "Riverside"),
    ("Market Street Bus Stop", CriticalLocationCategory.BUS_STOP, 17.4330, 78.3895, "Market"),
    (
        "Old Town Police Station",
        CriticalLocationCategory.POLICE_STATION,
        17.4210,
        78.4250,
        "Old Town",
    ),
    ("Downtown Fire Station", CriticalLocationCategory.FIRE_STATION, 17.4600, 78.4200, "Downtown"),
    ("Riverfront Road", CriticalLocationCategory.ROAD, 17.4327, 78.3885, "Near riverfront"),
    ("Central Bus Terminal", CriticalLocationCategory.TRANSPORT, 17.4400, 78.4350, "Downtown"),
]

_DEPARTMENTS = [
    ("Public Works", "PW", "Roads, water, and public infrastructure."),
    ("Sanitation", "SN", "Waste collection and street cleaning."),
    ("Parks & Recreation", "PR", "Public parks and green spaces."),
]

# 25 development field workers — 6 in WARD-1, 6 in WARD-2, 6 in WARD-3,
# 7 in WARD-4. Each row is deterministic: job (specialty), department, ward,
# real municipal base location in Pune, Maharashtra (India), skill tags and
# equipment. Ward membership is the account's registered ward (User.ward_id,
# via the reference ward codes); home coords are the worker's REGISTERED BASE —
# real distinct localities spread in four geographic quadrants of Pune so each
# ward's team is distributed across the city, never a single centre point and
# never a random/duplicated coordinate:
#   WARD-1 (south-west) lat 18.42-18.55 lon 73.72-73.86
#   WARD-2 (south-east) lat 18.42-18.55 lon 73.86-73.97
#   WARD-3 (north-west) lat 18.55-18.66 lon 73.72-73.86
#   WARD-4 (north-east) lat 18.55-18.66 lon 73.86-73.97
# All points lie within the Pune municipal area (18.42-18.66 / 73.72-73.97) and
# are 25 distinct coordinates. ``base_location`` is the human-readable station
# label; it never represents the worker's live GPS position.
_FIELD_WORKERS: list[dict] = [
    # --- WARD-1 (Ward 1, 6 workers) ------------------------------------
    {
        "name": "Ramesh Yadav",
        "email": "worker.1@example.com",
        "ward_code": "WARD-1",
        "department_code": "PW",
        "specialty": "Road Maintenance",
        "lat": 18.5106,
        "lon": 73.8076,
        "base_location": "Kothrud, Pune, Maharashtra",
        "skill_tags": ["road-maintenance", "asphalt", "patching"],
        "equipment": ["road-roller", "compactor"],
    },
    {
        "name": "Suresh Patel",
        "email": "worker.2@example.com",
        "ward_code": "WARD-1",
        "department_code": "PW",
        "specialty": "Pothole Repair",
        "lat": 18.4755,
        "lon": 73.8310,
        "base_location": "Sinhagad Road, Pune, Maharashtra",
        "skill_tags": ["pothole-repair", "asphalt", "cold-mix"],
        "equipment": ["asphalt-paver", "compactor"],
    },
    {
        "name": "Mohammed Irfan",
        "email": "worker.3@example.com",
        "ward_code": "WARD-1",
        "department_code": "SN",
        "specialty": "Garbage Collection",
        "lat": 18.4796,
        "lon": 73.7968,
        "base_location": "Warje, Pune, Maharashtra",
        "skill_tags": ["garbage-collection", "collections"],
        "equipment": ["garbage-truck"],
    },
    {
        "name": "Lakshmi Narayanan",
        "email": "worker.4@example.com",
        "ward_code": "WARD-1",
        "department_code": "SN",
        "specialty": "Waste Management",
        "lat": 18.4541,
        "lon": 73.8610,
        "base_location": "Katraj, Pune, Maharashtra",
        "skill_tags": ["waste-management", "segregation", "landfill"],
        "equipment": ["compactor-truck"],
    },
    {
        "name": "Kiran Babu",
        "email": "worker.5@example.com",
        "ward_code": "WARD-1",
        "department_code": "PW",
        "specialty": "Streetlight Repair",
        "lat": 18.5075,
        "lon": 73.8493,
        "base_location": "Navi Peth, Pune, Maharashtra",
        "skill_tags": ["streetlight-repair", "electrical", "lamp"],
        "equipment": ["boom-truck", "voltage-tester"],
    },
    {
        "name": "Anil Kumar",
        "email": "worker.6@example.com",
        "ward_code": "WARD-1",
        "department_code": "PR",
        "specialty": "Public Infrastructure Maintenance",
        "lat": 18.4496,
        "lon": 73.8429,
        "base_location": "Ambegaon Khurd, Pune, Maharashtra",
        "skill_tags": ["civic-assets", "maintenance", "public-infrastructure"],
        "equipment": ["hand-tools", "app-phone"],
    },
    # --- WARD-2 (Ward 2, 6 workers) ------------------------------------
    {
        "name": "Venkata Rao",
        "email": "worker.7@example.com",
        "ward_code": "WARD-2",
        "department_code": "PW",
        "specialty": "Road Inspection",
        "lat": 18.5125,
        "lon": 73.8836,
        "base_location": "Camp, Pune, Maharashtra",
        "skill_tags": ["road-inspection", "pavement-assessment"],
        "equipment": ["distance-measuring-wheel"],
    },
    {
        "name": "Santosh Reddy",
        "email": "worker.8@example.com",
        "ward_code": "WARD-2",
        "department_code": "PW",
        "specialty": "Water Pipeline Repair",
        "lat": 18.4634,
        "lon": 73.8912,
        "base_location": "Kondhwa, Pune, Maharashtra",
        "skill_tags": ["water-line-repair", "pipeline", "valve"],
        "equipment": ["excavator", "pipe-cutter"],
    },
    {
        "name": "Pooja Sharma",
        "email": "worker.9@example.com",
        "ward_code": "WARD-2",
        "department_code": "SN",
        "specialty": "Street Cleaning",
        "lat": 18.5362,
        "lon": 73.8940,
        "base_location": "Koregaon Park, Pune, Maharashtra",
        "skill_tags": ["street-cleaning", "sweeping"],
        "equipment": ["street-sweeper-vehicle"],
    },
    {
        "name": "Deepak Mishra",
        "email": "worker.10@example.com",
        "ward_code": "WARD-2",
        "department_code": "SN",
        "specialty": "Sewer Maintenance",
        "lat": 18.5089,
        "lon": 73.9259,
        "base_location": "Hadapsar, Pune, Maharashtra",
        "skill_tags": ["sewer-maintenance", "manhole", "jetting-rig"],
        "equipment": ["jetting-rig", "manhole-lift"],
    },
    {
        "name": "Rajesh Verma",
        "email": "worker.11@example.com",
        "ward_code": "WARD-2",
        "department_code": "PW",
        "specialty": "Electrical Maintenance",
        "lat": 18.5330,
        "lon": 73.9050,
        "base_location": "Ghorpadi, Pune, Maharashtra",
        "skill_tags": ["electrical-maintenance", "feeder", "panel"],
        "equipment": ["voltage-tester", "insulated-gloves"],
    },
    {
        "name": "Sunil Das",
        "email": "worker.12@example.com",
        "ward_code": "WARD-2",
        "department_code": "PW",
        "specialty": "Footpath Repair",
        "lat": 18.4620,
        "lon": 73.8677,
        "base_location": "Bibvewadi, Pune, Maharashtra",
        "skill_tags": ["footpath-repair", "paving", "paver-block"],
        "equipment": ["paver-block-setter"],
    },
    # --- WARD-3 (Ward 3, 6 workers) ------------------------------------
    {
        "name": "Manoj Gupta",
        "email": "worker.13@example.com",
        "ward_code": "WARD-3",
        "department_code": "PW",
        "specialty": "Road Maintenance",
        "lat": 18.5608,
        "lon": 73.7988,
        "base_location": "Aundh, Pune, Maharashtra",
        "skill_tags": ["road-maintenance", "asphalt", "patching"],
        "equipment": ["road-roller", "compactor"],
    },
    {
        "name": "Arjun Singh",
        "email": "worker.14@example.com",
        "ward_code": "WARD-3",
        "department_code": "PW",
        "specialty": "Water Leakage Repair",
        "lat": 18.5596,
        "lon": 73.7865,
        "base_location": "Baner, Pune, Maharashtra",
        "skill_tags": ["water-leak-repair", "pipeline", "shutoff-valve"],
        "equipment": ["pipe-clamp", "excavator"],
    },
    {
        "name": "Naveen Kumar",
        "email": "worker.15@example.com",
        "ward_code": "WARD-3",
        "department_code": "SN",
        "specialty": "Drain Cleaning",
        "lat": 18.5854,
        "lon": 73.7724,
        "base_location": "Wakad, Pune, Maharashtra",
        "skill_tags": ["drain-cleaning", "drainage-jetting"],
        "equipment": ["jetting-rig"],
    },
    {
        "name": "Ravi Teja",
        "email": "worker.16@example.com",
        "ward_code": "WARD-3",
        "department_code": "SN",
        "specialty": "Garbage Collection",
        "lat": 18.5913,
        "lon": 73.7389,
        "base_location": "Hinjewadi, Pune, Maharashtra",
        "skill_tags": ["garbage-collection", "collections"],
        "equipment": ["garbage-truck"],
    },
    {
        "name": "Prakash Rao",
        "email": "worker.17@example.com",
        "ward_code": "WARD-3",
        "department_code": "PW",
        "specialty": "Pothole Repair",
        "lat": 18.6298,
        "lon": 73.8147,
        "base_location": "Pimpri, Pune, Maharashtra",
        "skill_tags": ["pothole-repair", "asphalt", "cold-mix"],
        "equipment": ["asphalt-paver", "compactor"],
    },
    {
        "name": "Harish Naik",
        "email": "worker.18@example.com",
        "ward_code": "WARD-3",
        "department_code": "PR",
        "specialty": "Public Infrastructure Maintenance",
        "lat": 18.6278,
        "lon": 73.8100,
        "base_location": "Chinchwad, Pune, Maharashtra",
        "skill_tags": ["civic-assets", "maintenance", "public-infrastructure"],
        "equipment": ["hand-tools", "app-phone"],
    },
    # --- WARD-4 (Ward 4, 7 workers) ------------------------------------
    {
        "name": "Gopal Krishna",
        "email": "worker.19@example.com",
        "ward_code": "WARD-4",
        "department_code": "PW",
        "specialty": "Road Inspection",
        "lat": 18.5605,
        "lon": 73.9117,
        "base_location": "Viman Nagar, Pune, Maharashtra",
        "skill_tags": ["road-inspection", "pavement-assessment"],
        "equipment": ["distance-measuring-wheel"],
    },
    {
        "name": "Abdul Rahman",
        "email": "worker.20@example.com",
        "ward_code": "WARD-4",
        "department_code": "SN",
        "specialty": "Waste Management",
        "lat": 18.5584,
        "lon": 73.8821,
        "base_location": "Yerwada, Pune, Maharashtra",
        "skill_tags": ["waste-management", "segregation", "landfill"],
        "equipment": ["compactor-truck"],
    },
    {
        "name": "Sita Devi",
        "email": "worker.21@example.com",
        "ward_code": "WARD-4",
        "department_code": "SN",
        "specialty": "Street Cleaning",
        "lat": 18.5787,
        "lon": 73.9137,
        "base_location": "Lohegaon, Pune, Maharashtra",
        "skill_tags": ["street-cleaning", "sweeping"],
        "equipment": ["street-sweeper-vehicle"],
    },
    {
        "name": "Vijay Kumar",
        "email": "worker.22@example.com",
        "ward_code": "WARD-4",
        "department_code": "PW",
        "specialty": "Water Pipeline Repair",
        "lat": 18.5510,
        "lon": 73.9380,
        "base_location": "Kharadi, Pune, Maharashtra",
        "skill_tags": ["water-line-repair", "pipeline", "valve"],
        "equipment": ["excavator", "pipe-cutter"],
    },
    {
        "name": "Mahesh Chandra",
        "email": "worker.23@example.com",
        "ward_code": "WARD-4",
        "department_code": "PW",
        "specialty": "Electrical Maintenance",
        "lat": 18.5724,
        "lon": 73.8796,
        "base_location": "Vishrantwadi, Pune, Maharashtra",
        "skill_tags": ["electrical-maintenance", "feeder", "panel"],
        "equipment": ["voltage-tester", "insulated-gloves"],
    },
    {
        "name": "Bhaskar Reddy",
        "email": "worker.24@example.com",
        "ward_code": "WARD-4",
        "department_code": "SN",
        "specialty": "Sewer Maintenance",
        "lat": 18.5843,
        "lon": 73.8750,
        "base_location": "Dighi, Pune, Maharashtra",
        "skill_tags": ["sewer-maintenance", "manhole", "jetting-rig"],
        "equipment": ["jetting-rig", "manhole-lift"],
    },
    {
        "name": "Krishna Mohan",
        "email": "worker.25@example.com",
        "ward_code": "WARD-4",
        "department_code": "PW",
        "specialty": "Streetlight Repair",
        "lat": 18.5765,
        "lon": 73.8960,
        "base_location": "Dhanori, Pune, Maharashtra",
        "skill_tags": ["streetlight-repair", "electrical", "lamp"],
        "equipment": ["boom-truck", "voltage-tester"],
    },
]


async def _seed_roles(db) -> dict[RoleName, Role]:
    roles: dict[RoleName, Role] = {}
    for name, desc in _ROLES:
        role = await db.scalar(select(Role).where(Role.name == name.value))
        if role is None:
            role = Role(name=name.value, description=desc)
            db.add(role)
            await db.flush()
            print(f"[seed] created role {name.value}")
        roles[name] = role
    return roles


async def _seed_departments(db) -> dict[str, Department]:
    departments: dict[str, Department] = {}
    for name, code, desc in _DEPARTMENTS:
        dept = await db.scalar(select(Department).where(Department.code == code))
        if dept is None:
            dept = Department(name=name, code=code, description=desc)
            db.add(dept)
            await db.flush()
            print(f"[seed] created department {code}")
        departments[code] = dept
    return departments


async def _seed_critical_locations(db) -> None:
    """Seed the DEMO reference critical locations (idempotent, Part 10).

    These are illustrative facility placeholders (``is_demo=True``), never
    operational incidents — the UI labels them clearly as demo data.
    """
    for name, category, lat, lon, address in _DEMO_CRITICAL_LOCATIONS:
        existing = await db.scalar(
            select(CriticalLocation).where(
                CriticalLocation.name == name, CriticalLocation.category == category
            )
        )
        if existing is not None:
            continue
        db.add(
            CriticalLocation(
                name=name,
                category=category,
                latitude=lat,
                longitude=lon,
                address=address,
                is_demo=True,
                geom=func.ST_SetSRID(func.ST_MakePoint(lon, lat), 4326),
            )
        )
        print(f"[seed] created demo critical location: {name}")
    await db.flush()


async def _seed_bootstrap_admin(db) -> None:
    """Create the single bootstrap SUPER_ADMIN (idempotent)."""
    existing = await db.scalar(select(User).where(User.email == _BOOTSTRAP_ADMIN_EMAIL))
    if existing is not None:
        print(f"[seed] bootstrap admin already exists: {_BOOTSTRAP_ADMIN_EMAIL}")
        return
    role = await db.scalar(select(Role).where(Role.name == RoleName.SUPER_ADMIN.value))
    if role is None:
        raise RuntimeError("SUPER_ADMIN role missing — run roles seeding first.")
    user = User(
        email=_BOOTSTRAP_ADMIN_EMAIL,
        password_hash=hash_password(_DEMO_PASSWORD),
        full_name="System Administrator",
        role_id=role.id,
        ward_id=None,
        is_active=True,
        is_email_verified=True,
    )
    db.add(user)
    await db.flush()
    db.add(UserProfile(user_id=user.id))
    await db.flush()
    print(f"[seed] created bootstrap super-admin: {_BOOTSTRAP_ADMIN_EMAIL}")


async def _seed_field_workers(
    db, wards_by_code: dict[str, Ward], departments_by_code: dict[str, Department]
) -> None:
    """Create the 25 development field workers (idempotent, keyed by email).

    Mirrors the admin-service convention: a FIELD_WORKER user with a
    ``UserProfile`` and a linked ``FieldWorker`` profile. All workers are ACTIVE
    with zero workload — no complaints or work orders are created by the seed,
    so the platform still starts operationally empty. Each worker is registered
    at a distinct real base location in Pune (Maharashtra); re-running the seed
    re-points an already-seeded worker to that Pune base without touching the
    account password.
    """
    fw_role = await db.scalar(select(Role).where(Role.name == RoleName.FIELD_WORKER.value))
    if fw_role is None:
        raise RuntimeError("FIELD_WORKER role missing — run roles seeding first.")

    created = 0
    updated = 0
    for spec in _FIELD_WORKERS:
        ward = wards_by_code[spec["ward_code"]]
        dept = departments_by_code[spec["department_code"]]
        existing = await db.scalar(select(User).where(User.email == spec["email"]))
        if existing is not None:
            # Idempotent CONVERGENCE: an existing dev worker is re-pointed to its
            # registered Pune base + ward without touching the account password
            # or any operational data (complaints/work orders are never created).
            worker = await db.scalar(
                select(FieldWorker).where(FieldWorker.user_id == existing.id)
            )
            if worker is None:
                db.add(
                    FieldWorker(
                        user_id=existing.id,
                        department_id=dept.id,
                        specialty=spec["specialty"],
                        status=WorkerStatus.ACTIVE,
                        skill_tags=spec["skill_tags"],
                        equipment=spec["equipment"],
                        home_latitude=spec["lat"],
                        home_longitude=spec["lon"],
                        base_location=spec["base_location"],
                        max_active_orders=3,
                    )
                )
                await db.flush()
                created += 1
            else:
                existing.ward_id = ward.id
                worker.department_id = dept.id
                worker.specialty = spec["specialty"]
                worker.status = WorkerStatus.ACTIVE
                worker.skill_tags = spec["skill_tags"]
                worker.equipment = spec["equipment"]
                worker.home_latitude = spec["lat"]
                worker.home_longitude = spec["lon"]
                worker.base_location = spec["base_location"]
                updated += 1
            continue
        user = User(
            email=spec["email"],
            password_hash=hash_password(_WORKER_PASSWORD),
            full_name=spec["name"],
            role_id=fw_role.id,
            ward_id=ward.id,
            is_active=True,
            is_email_verified=True,
        )
        db.add(user)
        await db.flush()
        db.add(UserProfile(user_id=user.id))
        db.add(
            FieldWorker(
                user_id=user.id,
                department_id=dept.id,
                specialty=spec["specialty"],
                status=WorkerStatus.ACTIVE,
                skill_tags=spec["skill_tags"],
                equipment=spec["equipment"],
                home_latitude=spec["lat"],
                home_longitude=spec["lon"],
                base_location=spec["base_location"],
                max_active_orders=3,
            )
        )
        await db.flush()
        created += 1
        print(
            f"[seed] created field worker: {spec['email']} "
            f"({spec['name']}, {ward.code}, {dept.code}, {spec['specialty']})"
        )
    if created:
        print(f"[seed] field workers created: {created}")
    if updated:
        print(f"[seed] field workers re-pointed to registered Pune base: {updated}")
    if created == 0 and updated == 0:
        print("[seed] field workers already present — nothing to do")


async def _seed_ward_representatives(
    db, wards_by_code: dict[str, Ward]
) -> None:
    """Create the 4 ward representatives (idempotent, keyed by email).

    Each rep is assigned to exactly one ward and given the WARD_REPRESENTATIVE
    role.  No complaints, work orders or other operational data are created.
    """
    rep_role = await db.scalar(
        select(Role).where(Role.name == RoleName.WARD_REPRESENTATIVE.value)
    )
    if rep_role is None:
        raise RuntimeError("WARD_REPRESENTATIVE role missing — run roles seeding first.")

    created = 0
    for spec in _WARD_REPRESENTATIVES:
        if await db.scalar(
            select(User).where(User.email == spec["email"])
        ) is not None:
            continue
        ward = wards_by_code[spec["ward_code"]]
        user = User(
            email=spec["email"],
            password_hash=hash_password(_REP_PASSWORD),
            full_name=spec["name"],
            role_id=rep_role.id,
            ward_id=ward.id,
            is_active=True,
            is_email_verified=True,
        )
        db.add(user)
        await db.flush()
        db.add(UserProfile(user_id=user.id))
        db.add(
            WardRepresentative(
                user_id=user.id,
                ward_id=ward.id,
                title=spec["title"],
                status=RepresentativeStatus.ACTIVE,
            )
        )
        await db.flush()
        created += 1
        print(
            f"[seed] created ward representative: {spec['email']} "
            f"({spec['name']}, {ward.code})"
        )
    if created:
        print(f"[seed] ward representatives created: {created}")
    else:
        print("[seed] ward representatives already present — nothing to do")


async def _seed_assistant_knowledge(db) -> int:
    """Seed the Citizen AI Assistant knowledge base (idempotent, Part 25)."""
    from app.rag.knowledge_base import ensure_knowledge_base

    ensured = await ensure_knowledge_base(db)
    print(f"[seed] assistant knowledge base ready ({ensured} documents)")
    return ensured


async def _requires(args) -> bool:
    return "--reset" in args


async def main() -> None:
    async with async_session_factory() as db:
        if await _requires(sys.argv[1:]):
            from scripts.reset_dev_data import reset_dev_data_all

            print("[seed] --reset requested: wiping demo/operational data first...")
            total_ops, deleted_users, deleted_wards = await reset_dev_data_all(db)
            print(
                f"[seed] reset removed {total_ops} operational rows, "
                f"{deleted_users} users, {deleted_wards} non-reference wards."
            )

        await _seed_roles(db)
        await _seed_departments(db)
        await _seed_critical_locations(db)
        await _seed_bootstrap_admin(db)
        await _seed_assistant_knowledge(db)

        # Reference wards are installed by the migration; verify + summarise.
        ref_wards = (await db.scalars(select(Ward).order_by(Ward.code))).all()
        if ref_wards:
            print(
                "[seed] reference wards: "
                + ", ".join(f"{w.code} ({w.name})" for w in ref_wards)
            )
            await _seed_field_workers(
                db,
                wards_by_code={w.code: w for w in ref_wards},
                departments_by_code={
                    d.code: d for d in (await db.scalars(select(Department))).all()
                },
            )
            await _seed_ward_representatives(
                db,
                wards_by_code={w.code: w for w in ref_wards},
            )
        else:
            print("[seed] WARNING: no wards found — run `alembic upgrade head` first.")

        await db.commit()
    await engine.dispose()
    print(
        "\n[seed] done. Reference-data baseline is ready.\n"
        f"Bootstrap SUPER_ADMIN login: {_BOOTSTRAP_ADMIN_EMAIL}\n"
        f"Password (shared demo password): {_DEMO_PASSWORD}\n"
        f"25 dev FIELD_WORKER logins worker.1@example.com...worker.25@example.com\n"
        f"Field-worker password: {_WORKER_PASSWORD}\n"
        f"4 WARD_REPRESENTATIVE logins: kobu.dheeraj/rushikesh/rajveer@example.com\n"
        f"Ward-rep password: {_REP_PASSWORD}\n"
        "No demo complaints/hotspots/predictions exist — the platform starts empty."
    )


if __name__ == "__main__":
    asyncio.run(main())
