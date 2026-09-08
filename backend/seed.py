"""Development seed script for CivicAgent.

Populates (demo/data-labelled):
- Roles: CITIZEN, OFFICER, WARD_REPRESENTATIVE, FIELD_WORKER, ADMIN
- One admin user, one officer, ward reps, field workers, and a set of citizen
- Wards and departments for the worker/representative links

Usage (from backend/):
    .venv\\Scripts\\python seed.py

Idempotent: existing records by natural keys are skipped. Never in production.
"""

from __future__ import annotations

import asyncio
from datetime import UTC

from sqlalchemy import func, select

from app.core.security import hash_password
from app.db.session import async_session_factory, engine
from app.models import (
    Complaint,
    ComplaintLocation,
    CriticalLocation,
    Department,
    FieldWorker,
    InfrastructureAsset,
    Role,
    User,
    UserProfile,
    Ward,
    WardBoundary,
    WardRepresentative,
)
from app.models.enums import (
    ComplaintCategory,
    ComplaintPriority,
    ComplaintStatus,
    CriticalLocationCategory,
    InfrastructureCategory,
    RepresentativeStatus,
    RoleName,
    WorkerStatus,
)

# All demo users below use this shared password and are clearly demo data.
_DEMO_PASSWORD = "CivicAgent#2026"

# Demo coordinates fall within Riverside ward (W-002) — Hyderabad, India.
_SEED_LAT = 17.4327
_SEED_LON = 78.3885

_ROLES: list[tuple[RoleName, str]] = [
    (RoleName.CITIZEN, "Citizen who submits and tracks complaints."),
    (RoleName.OFFICER, "Municipal officer who reviews complaints and approves work."),
    (RoleName.WARD_REPRESENTATIVE, "Elected/assigned representative for a ward."),
    (RoleName.FIELD_WORKER, "Field worker who executes assigned work orders."),
    (RoleName.ADMIN, "System administrator with full management rights."),
    (RoleName.SUPER_ADMIN, "Super administrator with panel management rights."),
]

_WARDS = [
    ("Downtown", "W-001", "Central business district ward."),
    ("Riverside", "W-002", "Residential ward along the river."),
    ("Old Town", "W-003", "Historic residential ward."),
]

# ===== Part 10 — DEMO spatial data ============================================
# These ward boundaries and critical locations are ILLUSTRATIVE placeholders, NOT
# authoritative municipal data. They are stored with ``is_demo=True`` so the UI
# surfaces the configured GIS_DEMO_LABEL ("DEMO DATA") and never presents them as
# authoritative. Rectangles around Hyderabad, India (see _SEED_LAT/_SEED_LON).
# WKT ring orientation is longitude, latitude; polygons must be closed.
_DEMO_WARD_BOUNDARIES: dict[str, str] = {
    # code -> EWKT polygon
    "W-001": "POLYGON((78.40 17.45,78.44 17.45,78.44 17.49,78.40 17.49,78.40 17.45))",
    "W-002": "POLYGON((78.36 17.41,78.40 17.41,78.40 17.45,78.36 17.45,78.36 17.41))",
    "W-003": "POLYGON((78.44 17.42,78.48 17.42,78.48 17.46,78.44 17.46,78.44 17.42))",
}

# (name, category, lat, lon, address)
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

# ===== Part 24 - DEMO infrastructure assets ================================
# Registered demo assets used by the predictive infrastructure maintenance
# pipeline. Ranges of install dates are picked so the age signal varies;
# all rows are clearly demo data. Row shape: (name, category, ward_code, lat,
# lon, address, installed_at year, condition_note).
_DemoAsset = tuple[
    str, InfrastructureCategory, str, float, float, str, int, str
]

_DEMO_INFRASTRUCTURE_ASSETS: list[_DemoAsset] = [
    (
        "Market Street Asphalt",
        InfrastructureCategory.ROAD,
        "W-001",
        17.4420,
        78.4200,
        "Market Street, Downtown",
        2005,
        "Some surface cracking near junctions.",
    ),
    (
        "Riverfront Road Segment",
        InfrastructureCategory.ROAD,
        "W-002",
        17.4327,
        78.3885,
        "Near riverfront, Riverside",
        1998,
        "Frequent asphalt patching in this stretch.",
    ),
    (
        "Riverside Crossing Bridge",
        InfrastructureCategory.BRIDGE,
        "W-002",
        17.4300,
        78.3860,
        "Riverside",
        1985,
        "Deck joints show wear.",
    ),
    (
        "Downtown Water Main - Phase 1",
        InfrastructureCategory.WATER_MAIN,
        "W-001",
        17.4380,
        78.4240,
        "Downtown trunk line",
        2001,
        "",
    ),
    (
        "Riverside Water Main - Phase 2",
        InfrastructureCategory.WATER_MAIN,
        "W-002",
        17.4270,
        78.3830,
        "Riverside trunk line",
        1992,
        "Older ductile-iron section.",
    ),
    (
        "Old Town Drainage Line",
        InfrastructureCategory.DRAINAGE,
        "W-003",
        17.4210,
        78.4250,
        "Old Town",
        1988,
        "Periodic blockages reported.",
    ),
    (
        "Riverside Sewer Collector",
        InfrastructureCategory.SEWER,
        "W-002",
        17.4290,
        78.3890,
        "Riverside",
        1995,
        "",
    ),
    (
        "Market Street Light Poles",
        InfrastructureCategory.STREET_LIGHTING,
        "W-001",
        17.4410,
        78.4180,
        "Market Street",
        2012,
        "Conduit age moderate.",
    ),
    (
        "Riverside Park Lighting",
        InfrastructureCategory.STREET_LIGHTING,
        "W-002",
        17.4335,
        78.3865,
        "Riverside Park",
        2019,
        "Relatively new.",
    ),
    (
        "Riverside Park",
        InfrastructureCategory.PARK,
        "W-002",
        17.4330,
        78.3870,
        "Riverside Park",
        1990,
        "Pathways and playground aging.",
    ),
    (
        "Old Town Civic Hall",
        InfrastructureCategory.PUBLIC_BUILDING,
        "W-003",
        17.4200,
        78.4260,
        "Old Town",
        1975,
        "Plumbing service age high.",
    ),
    (
        "Central Bus Terminal Building",
        InfrastructureCategory.PUBLIC_BUILDING,
        "W-001",
        17.4400,
        78.4350,
        "Downtown",
        2008,
        "",
    ),
]

_DEMO_USERS = [
    # admin@example.com is the SUPER_ADMIN operator for the Super-Admin Panel.
    ("admin@example.com", "Admin User", RoleName.SUPER_ADMIN, None, None, None, None),
    ("officer@example.com", "Officer User", RoleName.OFFICER, None, None, None, "W-001"),
    ("worker@example.com", "Field Worker", RoleName.FIELD_WORKER, "SN", "Sanitation", None, None),
    ("rep@example.com", "Ward Rep", RoleName.WARD_REPRESENTATIVE, None, None, "W-001", None),
    ("rep2@example.com", "Alia Khan", RoleName.WARD_REPRESENTATIVE, None, None, "W-002", None),
    ("citizen@example.com", "Aarav Patel", RoleName.CITIZEN, None, None, None, "W-002"),
    ("citizen2@example.com", "New Citizen", RoleName.CITIZEN, None, None, None, "W-003"),
]

# Seed complaints for the primary demo citizen (citizen@example.com) covering
# every category, priority, and status so the dashboard has realistic data.
# (category, title, description, location, priority, status, relative_days_ago)
_COMPLAINTS: list[tuple[str, str, str, str, ComplaintPriority, ComplaintStatus, int]] = [
    (
        "ROAD",
        "Pothole on Market Street",
        "Large pothole near the 5th Street junction causing damage to vehicles.",
        "Market Street, Downtown",
        ComplaintPriority.HIGH,
        ComplaintStatus.IN_PROGRESS,
        1,
    ),
    (
        "STREET_LIGHTING",
        "Street light not working",
        "The street light outside 42 Riverside Avenue has been out for a week.",
        "Riverside Avenue",
        ComplaintPriority.MEDIUM,
        ComplaintStatus.OPEN,
        2,
    ),
    (
        "SANITATION",
        "Overflowing garbage bins",
        "Public bins near the riverside park are overflowing and need collection.",
        "Riverside Park",
        ComplaintPriority.MEDIUM,
        ComplaintStatus.RESOLVED,
        3,
    ),
    (
        "WATER",
        "Low water pressure",
        "Low water pressure in the apartment block on the east side of Riverside.",
        "East Riverside Block",
        ComplaintPriority.HIGH,
        ComplaintStatus.ESCALATED,
        4,
    ),
    (
        "ELECTRICITY",
        "Frequent power cuts",
        "Sudden power cuts every evening in the residential lanes off Riverside Avenue.",
        "Old Mill Lanes",
        ComplaintPriority.CRITICAL,
        ComplaintStatus.IN_PROGRESS,
        5,
    ),
    (
        "PARKS",
        "Damaged children's swing",
        "The swing set at Riverside Park is damaged and unsafe for children.",
        "Riverside Park",
        ComplaintPriority.LOW,
        ComplaintStatus.RESOLVED,
        6,
    ),
    (
        "PUBLIC_SAFETY",
        "Pothole near school crossing",
        "Deep pothole right at the school crossing, dangerous for children.",
        "Near Riverside Primary School",
        ComplaintPriority.CRITICAL,
        ComplaintStatus.OPEN,
        7,
    ),
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


async def _seed_wards(db) -> dict[str, Ward]:
    wards: dict[str, Ward] = {}
    for name, code, desc in _WARDS:
        ward = await db.scalar(select(Ward).where(Ward.code == code))
        if ward is None:
            ward = Ward(name=name, code=code, description=desc)
            db.add(ward)
            await db.flush()
            print(f"[seed] created ward {code}")
        wards[code] = ward
    return wards


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


async def _seed_user(
    db,
    email: str,
    full_name: str,
    role: Role,
    worker_dept: str | None,
    worker_specialty: str | None,
    rep_ward: str | None,
    user_ward: str | None,
    departments: dict[str, Department],
    wards: dict[str, Ward],
) -> User | None:
    user = await db.scalar(select(User).where(User.email == email))
    if user is not None:
        print(f"[seed] skip existing user {email}")
        return None
    user = User(
        email=email,
        password_hash=hash_password(_DEMO_PASSWORD),
        full_name=full_name,
        role_id=role.id,
        ward_id=wards[user_ward].id if user_ward else None,
        is_active=True,
        is_email_verified=True,
    )
    db.add(user)
    await db.flush()
    db.add(UserProfile(user_id=user.id))
    await db.flush()

    if worker_dept and role.name == RoleName.FIELD_WORKER.value:
        dept = departments[worker_dept]
        db.add(
            FieldWorker(
                user_id=user.id,
                department_id=dept.id,
                specialty=worker_specialty,
                status=WorkerStatus.ACTIVE,
            )
        )
        print(f"[seed] created field worker {email}")
    elif rep_ward and role.name == RoleName.WARD_REPRESENTATIVE.value:
        ward = wards[rep_ward]
        # A representative's ward is their own ward (user.ward_id drives all
        # ward-scoped RBAC across the app, so both must agree).
        user.ward_id = ward.id
        db.add(
            WardRepresentative(
                user_id=user.id,
                ward_id=ward.id,
                title="Ward Representative",
                status=RepresentativeStatus.ACTIVE,
            )
        )
        print(f"[seed] created ward representative {email}")
    else:
        print(f"[seed] created user {email} (role {role.name})")
    await db.flush()
    return user


async def _seed_locations(db, citizen: User) -> None:
    """Backfill a PostGIS location for any of the citizen's complaints that lack one."""
    complaints = (
        (
            await db.execute(
                select(Complaint)
                .where(Complaint.user_id == citizen.id)
                .outerjoin(ComplaintLocation)
                .where(ComplaintLocation.id.is_(None))
            )
        )
        .scalars()
        .all()
    )
    for complaint in complaints:
        db.add(
            ComplaintLocation(
                complaint_id=complaint.id,
                latitude=_SEED_LAT,
                longitude=_SEED_LON,
                geom=func.ST_SetSRID(func.ST_MakePoint(_SEED_LON, _SEED_LAT), 4326),
                address=complaint.location,
                source="gps",
                geopoint_denied=False,
            )
        )
        print(f"[seed] backfilled location for: {complaint.title}")
    await db.flush()


async def _seed_boundaries_and_critical_locations(db, wards: dict[str, Ward]) -> None:
    """Seed DEMO ward boundaries + demo critical locations (Part 10).

    Idempotent per (ward_id / name + category). All rows are flagged ``is_demo``
    and are explicitly illustrative, never authoritative municipal data.
    """
    # Demo ward boundaries.
    for code, wkt in _DEMO_WARD_BOUNDARIES.items():
        ward = wards[code]
        existing = await db.scalar(select(WardBoundary).where(WardBoundary.ward_id == ward.id))
        if existing is not None:
            continue
        db.add(
            WardBoundary(
                ward_id=ward.id,
                name=f"{ward.name} boundary",
                is_demo=True,
                geom=func.ST_SetSRID(func.ST_GeomFromText(wkt, 4326), 4326),
            )
        )
        print(f"[seed] created demo boundary for {code}")

    # Demo critical locations.
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


async def _seed_complaints(
    db,
    citizen: User,
) -> None:
    """Create demo complaints for a citizen. Idempotent per (user_id, title).

    created_at is backdated (days ago, newest first) to give the dashboard a
    realistic spread.
    """
    from datetime import datetime, timedelta

    for category, title, description, location, priority, status, days_ago in _COMPLAINTS:
        existing = await db.scalar(
            select(Complaint).where(Complaint.user_id == citizen.id, Complaint.title == title)
        )
        if existing is not None:
            print(f"[seed] skip existing complaint: {title}")
            continue
        created = datetime.now(UTC) - timedelta(days=days_ago, hours=3)
        complaint = Complaint(
            user_id=citizen.id,
            ward_id=citizen.ward_id,
            category=ComplaintCategory(category),
            title=title,
            description=description,
            location=location,
            priority=priority,
            status=status,
            created_at=created,
            updated_at=created + timedelta(hours=1),
        )
        db.add(complaint)
        await db.flush()
        print(f"[seed] created complaint: {title}")
    await db.flush()


async def _seed_infrastructure(db, wards: dict[str, Ward]) -> None:
    """Seed DEMO infrastructure assets (Part 24). Idempotent per (name, category)."""
    from datetime import date

    for name, category, ward_code, lat, lon, address, year, note in _DEMO_INFRASTRUCTURE_ASSETS:
        existing = await db.scalar(
            select(InfrastructureAsset).where(
                InfrastructureAsset.name == name, InfrastructureAsset.category == category
            )
        )
        if existing is not None:
            print(f"[seed] skip existing infrastructure asset: {name}")
            continue
        db.add(
            InfrastructureAsset(
                name=name,
                category=category,
                ward_id=wards[ward_code].id,
                latitude=lat,
                longitude=lon,
                address=address,
                installed_at=date(year, 7, 1),
                condition_note=note or None,
                is_active=True,
            )
        )
        print(f"[seed] created demo infrastructure asset: {name}")
    await db.flush()


async def _seed_assistant_knowledge(db) -> int:
    """Seed the Citizen AI Assistant knowledge base (idempotent, Part 25)."""
    from app.rag.knowledge_base import ensure_knowledge_base

    ensured = await ensure_knowledge_base(db)
    print(f"[seed] assistant knowledge base ready ({ensured} documents)")
    return ensured


async def main() -> None:
    async with async_session_factory() as db:
        roles = await _seed_roles(db)
        wards = await _seed_wards(db)
        departments = await _seed_departments(db)
        await _seed_boundaries_and_critical_locations(db, wards)
        await _seed_infrastructure(db, wards)
        for (
            email,
            name,
            role_name,
            worker_dept,
            worker_specialty,
            rep_ward,
            user_ward,
        ) in _DEMO_USERS:
            await _seed_user(
                db,
                email,
                name,
                roles[role_name],
                worker_dept,
                worker_specialty,
                rep_ward,
                user_ward,
                departments,
                wards,
            )

        # Ensure the primary demo citizen has a ward and complaints even if the
        # user pre-dates the ward column (seed is idempotent per natural key).
        demo = await db.scalar(select(User).where(User.email == "citizen@example.com"))
        if demo is not None:
            if demo.ward_id is None:
                demo.ward_id = wards["W-002"].id
                print("[seed] linked citizen@example.com to ward W-002")
            await _seed_complaints(db, demo)
            await _seed_locations(db, demo)
        await _seed_assistant_knowledge(db)
        await db.commit()
    await engine.dispose()
    print("\n[seed] done. Demo password for all accounts:", _DEMO_PASSWORD)


if __name__ == "__main__":
    asyncio.run(main())
