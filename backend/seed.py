"""Development seed script for CivicAgent — reference data only (Part 31).

The platform ships GENUINELY EMPTY: zero complaints, zero hotspots, zero
predictions, zero analytics. This script only seeds REFERENCE data:

- Roles: CITIZEN, OFFICER, WARD_REPRESENTATIVE, FIELD_WORKER, ADMIN, SUPER_ADMIN
- Departments for the worker/representative links
- The Citizen AI Assistant knowledge base
- A single bootstrap ``admin@example.com`` SUPER_ADMIN account (documented
  login for the super-admin panel)
- 25 development FIELD_WORKER accounts (ward distribution 6/6/6/7 across
  WARD-1..WARD-4 — Kondhwa, Kothrud, Hadapsar, Viman Nagar) with realistic
  municipal jobs, skills and registered base locations inside their ward's
  operational polygon in Pune, Maharashtra, India — created idempotently by
  email and re-pointed to their Pune base on re-runs
- 4 development WARD_REPRESENTATIVE accounts (one per ward) — created
  idempotently by email

The four reference wards (WARD 1..WARD 4) and their real Pune operational
boundaries arrive via the alembic migrations (``31a2b3c4d5e6`` +
``b6c7d8e9f0a1``) — NOT from this script — so a fresh deploy always has
functional sign-up wards. Nearby infrastructure is intentionally NEVER seeded:
the platform sources real facilities from OpenStreetMap (Overpass) at lookup
time, with an explicit "unavailable" fallback.

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

from sqlalchemy import select

from app.core.security import hash_password
from app.db.session import async_session_factory, engine
from app.models import (
    Department,
    FieldWorker,
    Role,
    User,
    UserProfile,
    Ward,
    WardRepresentative,
)
from app.models.enums import (
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

# Shared dev password for seeded municipal officers.
_OFFICER_PASSWORD = "Officer#2026"

# 2 municipal officers — the officer-portal users who review complaints,
# approve dispatch recommendations and verify resolution evidence. Officers are
# global staff (not ward-scoped), so no ward link is required for them.
_OFFICERS: list[dict] = [
    {"name": "Sneha Kulkarni", "email": "officer.1@example.com"},
    {"name": "Vikram Deshmukh", "email": "officer.2@example.com"},
]

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

# (name, code, description) — operational departments for worker/rep links.
_DEPARTMENTS = [
    ("Public Works", "PW", "Roads, water, and public infrastructure."),
    ("Sanitation", "SN", "Waste collection and street cleaning."),
    ("Parks & Recreation", "PR", "Public parks and green spaces."),
]

# 25 development field workers — 6 in WARD-1 (Kondhwa), 6 in WARD-2 (Kothrud),
# 6 in WARD-3 (Hadapsar), 7 in WARD-4 (Viman Nagar). Each row is deterministic:
# job (specialty), department, ward and a real municipal base location that lies
# INSIDE that ward's operational polygon (PostGIS ST_Contains verified by
# scripts/validate_pune_geo.py). Ward membership is the account's registered
# ward (User.ward_id, via the reference ward codes); home coords are the
# worker's REGISTERED BASE — distinct localities in each ward's geography, never
# a single centre point and never a random/duplicated coordinate.
_FIELD_WORKERS: list[dict] = [
    # --- WARD-1 (Ward 1 — Kondhwa, 6 workers) ---------------------------
    # Kondhwa Khurd, Kondhwa, NIBM, Yewalewadi, Kondhwa Budruk, Bibvewadi.
    {
        "name": "Ramesh Yadav",
        "email": "worker.1@example.com",
        "ward_code": "WARD-2",
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
        "lat": 18.4719,
        "lon": 73.8886,
        "base_location": "Kondhwa Khurd, Pune, Maharashtra",
        "skill_tags": ["pothole-repair", "asphalt", "cold-mix"],
        "equipment": ["asphalt-paver", "compactor"],
    },
    {
        "name": "Mohammed Irfan",
        "email": "worker.3@example.com",
        "ward_code": "WARD-2",
        "department_code": "SN",
        "specialty": "Garbage Collection",
        "lat": 18.4867,
        "lon": 73.8050,
        "base_location": "Karve Nagar, Pune, Maharashtra",
        "skill_tags": ["garbage-collection", "collections"],
        "equipment": ["garbage-truck"],
    },
    {
        "name": "Lakshmi Narayanan",
        "email": "worker.4@example.com",
        "ward_code": "WARD-1",
        "department_code": "SN",
        "specialty": "Waste Management",
        "lat": 18.4634,
        "lon": 73.8912,
        "base_location": "Kondhwa, Pune, Maharashtra",
        "skill_tags": ["waste-management", "segregation", "landfill"],
        "equipment": ["compactor-truck"],
    },
    {
        "name": "Kiran Babu",
        "email": "worker.5@example.com",
        "ward_code": "WARD-1",
        "department_code": "PW",
        "specialty": "Streetlight Repair",
        "lat": 18.4598,
        "lon": 73.9065,
        "base_location": "NIBM, Pune, Maharashtra",
        "skill_tags": ["streetlight-repair", "electrical", "lamp"],
        "equipment": ["boom-truck", "voltage-tester"],
    },
    {
        "name": "Anil Kumar",
        "email": "worker.6@example.com",
        "ward_code": "WARD-1",
        "department_code": "PR",
        "specialty": "Public Infrastructure Maintenance",
        "lat": 18.4363,
        "lon": 73.8965,
        "base_location": "Yewalewadi, Pune, Maharashtra",
        "skill_tags": ["civic-assets", "maintenance", "public-infrastructure"],
        "equipment": ["hand-tools", "app-phone"],
    },
    # --- WARD-2 (Ward 2 — Kothrud, 6 workers) ---------------------------
    # Kothrud, Karve Nagar, Erandwane, Paud Road, Vanaz, Dahanukar Colony.
    {
        "name": "Venkata Rao",
        "email": "worker.7@example.com",
        "ward_code": "WARD-2",
        "department_code": "PW",
        "specialty": "Road Inspection",
        "lat": 18.5071,
        "lon": 73.8310,
        "base_location": "Erandwane, Pune, Maharashtra",
        "skill_tags": ["road-inspection", "pavement-assessment"],
        "equipment": ["distance-measuring-wheel"],
    },
    {
        "name": "Santosh Reddy",
        "email": "worker.8@example.com",
        "ward_code": "WARD-2",
        "department_code": "PW",
        "specialty": "Water Pipeline Repair",
        "lat": 18.5083,
        "lon": 73.7960,
        "base_location": "Paud Road, Pune, Maharashtra",
        "skill_tags": ["water-line-repair", "pipeline", "valve"],
        "equipment": ["excavator", "pipe-cutter"],
    },
    {
        "name": "Pooja Sharma",
        "email": "worker.9@example.com",
        "ward_code": "WARD-2",
        "department_code": "SN",
        "specialty": "Street Cleaning",
        "lat": 18.5090,
        "lon": 73.8230,
        "base_location": "Vanaz, Pune, Maharashtra",
        "skill_tags": ["street-cleaning", "sweeping"],
        "equipment": ["street-sweeper-vehicle"],
    },
    {
        "name": "Deepak Mishra",
        "email": "worker.10@example.com",
        "ward_code": "WARD-2",
        "department_code": "SN",
        "specialty": "Sewer Maintenance",
        "lat": 18.5120,
        "lon": 73.8170,
        "base_location": "Dahanukar Colony, Pune, Maharashtra",
        "skill_tags": ["sewer-maintenance", "manhole", "jetting-rig"],
        "equipment": ["jetting-rig", "manhole-lift"],
    },
    {
        "name": "Rajesh Verma",
        "email": "worker.11@example.com",
        "ward_code": "WARD-1",
        "department_code": "PW",
        "specialty": "Electrical Maintenance",
        "lat": 18.4535,
        "lon": 73.9115,
        "base_location": "Kondhwa Budruk, Pune, Maharashtra",
        "skill_tags": ["electrical-maintenance", "feeder", "panel"],
        "equipment": ["voltage-tester", "insulated-gloves"],
    },
    {
        "name": "Sunil Das",
        "email": "worker.12@example.com",
        "ward_code": "WARD-1",
        "department_code": "PW",
        "specialty": "Footpath Repair",
        "lat": 18.4620,
        "lon": 73.8677,
        "base_location": "Bibvewadi, Pune, Maharashtra",
        "skill_tags": ["footpath-repair", "paving", "paver-block"],
        "equipment": ["paver-block-setter"],
    },
    # --- WARD-3 (Ward 3 — Hadapsar, 6 workers) --------------------------
    # Magarpatta City, Mundhwa, Hadapsar, North Hadapsar, Magarpatta South,
    # Hadapsar Gaon.
    {
        "name": "Manoj Gupta",
        "email": "worker.13@example.com",
        "ward_code": "WARD-3",
        "department_code": "PW",
        "specialty": "Road Maintenance",
        "lat": 18.5159,
        "lon": 73.9263,
        "base_location": "Magarpatta City, Pune, Maharashtra",
        "skill_tags": ["road-maintenance", "asphalt", "patching"],
        "equipment": ["road-roller", "compactor"],
    },
    {
        "name": "Arjun Singh",
        "email": "worker.14@example.com",
        "ward_code": "WARD-3",
        "department_code": "PW",
        "specialty": "Water Leakage Repair",
        "lat": 18.5347,
        "lon": 73.9355,
        "base_location": "Mundhwa, Pune, Maharashtra",
        "skill_tags": ["water-leak-repair", "pipeline", "shutoff-valve"],
        "equipment": ["pipe-clamp", "excavator"],
    },
    {
        "name": "Naveen Kumar",
        "email": "worker.15@example.com",
        "ward_code": "WARD-3",
        "department_code": "SN",
        "specialty": "Drain Cleaning",
        "lat": 18.4995,
        "lon": 73.9256,
        "base_location": "Hadapsar, Pune, Maharashtra",
        "skill_tags": ["drain-cleaning", "drainage-jetting"],
        "equipment": ["jetting-rig"],
    },
    {
        "name": "Ravi Teja",
        "email": "worker.16@example.com",
        "ward_code": "WARD-3",
        "department_code": "SN",
        "specialty": "Garbage Collection",
        "lat": 18.5270,
        "lon": 73.9300,
        "base_location": "North Hadapsar, Pune, Maharashtra",
        "skill_tags": ["garbage-collection", "collections"],
        "equipment": ["garbage-truck"],
    },
    {
        "name": "Prakash Rao",
        "email": "worker.17@example.com",
        "ward_code": "WARD-3",
        "department_code": "PW",
        "specialty": "Pothole Repair",
        "lat": 18.5050,
        "lon": 73.9330,
        "base_location": "Magarpatta South, Pune, Maharashtra",
        "skill_tags": ["pothole-repair", "asphalt", "cold-mix"],
        "equipment": ["asphalt-paver", "compactor"],
    },
    {
        "name": "Harish Naik",
        "email": "worker.18@example.com",
        "ward_code": "WARD-3",
        "department_code": "PR",
        "specialty": "Public Infrastructure Maintenance",
        "lat": 18.5080,
        "lon": 73.9180,
        "base_location": "Hadapsar Gaon, Pune, Maharashtra",
        "skill_tags": ["civic-assets", "maintenance", "public-infrastructure"],
        "equipment": ["hand-tools", "app-phone"],
    },
    # --- WARD-4 (Ward 4 — Viman Nagar, 7 workers) ------------------------
    # Viman Nagar, Yerwada, Lohegaon, Kharadi, Vishrantwadi, Dighi, Dhanori.
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
    at a distinct real base location inside its ward's operational polygon in
    Pune (Maharashtra); re-running the seed re-points an already-seeded worker
    to that Pune base without touching the account password.
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
            worker = await db.scalar(select(FieldWorker).where(FieldWorker.user_id == existing.id))
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


async def _seed_officers(db) -> None:
    """Create municipal OFFICER accounts (idempotent, keyed by email).

    Officers staff the officer portal: they review complaints, approve dispatch
    recommendations and verify resolution evidence. They are global staff (no
    ward link) — ward scoping only applies to WARD_REPRESENTATIVE users.
    """
    officer_role = await db.scalar(select(Role).where(Role.name == RoleName.OFFICER.value))
    if officer_role is None:
        raise RuntimeError("OFFICER role missing — run roles seeding first.")
    created = 0
    for spec in _OFFICERS:
        if await db.scalar(select(User).where(User.email == spec["email"])) is not None:
            continue
        user = User(
            email=spec["email"],
            password_hash=hash_password(_OFFICER_PASSWORD),
            full_name=spec["name"],
            role_id=officer_role.id,
            ward_id=None,
            is_active=True,
            is_email_verified=True,
        )
        db.add(user)
        await db.flush()
        db.add(UserProfile(user_id=user.id))
        await db.flush()
        created += 1
        print(f"[seed] created officer: {spec['email']} ({spec['name']})")
    if created:
        print(f"[seed] officers created: {created}")
    else:
        print("[seed] officers already present — nothing to do")


async def _seed_ward_representatives(db, wards_by_code: dict[str, Ward]) -> None:
    """Create the 4 ward representatives (idempotent, keyed by email).

    Each rep is assigned to exactly one ward and given the WARD_REPRESENTATIVE
    role.  No complaints, work orders or other operational data are created.
    """
    rep_role = await db.scalar(select(Role).where(Role.name == RoleName.WARD_REPRESENTATIVE.value))
    if rep_role is None:
        raise RuntimeError("WARD_REPRESENTATIVE role missing — run roles seeding first.")

    created = 0
    for spec in _WARD_REPRESENTATIVES:
        if await db.scalar(select(User).where(User.email == spec["email"])) is not None:
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
        print(f"[seed] created ward representative: {spec['email']} ({spec['name']}, {ward.code})")
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
        await _seed_bootstrap_admin(db)
        await _seed_assistant_knowledge(db)

        # Reference wards are installed by the migration; verify + summarise.
        ref_wards = (await db.scalars(select(Ward).order_by(Ward.code))).all()
        if ref_wards:
            print("[seed] reference wards: " + ", ".join(f"{w.code} ({w.name})" for w in ref_wards))
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
            await _seed_officers(db)
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
        f"2 OFFICER logins: officer.1@example.com, officer.2@example.com\n"
        f"Officer password: {_OFFICER_PASSWORD}\n"
        "No demo complaints/hotspots/predictions exist — the platform starts empty."
    )


if __name__ == "__main__":
    asyncio.run(main())
