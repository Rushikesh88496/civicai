import asyncio

from sqlalchemy import text

from app.db.session import async_session_factory

CHECKS = [
    ("w1-kondhwakhurd", "WARD-1", 18.47187, 73.88863),
    ("w1-kondhwa", "WARD-1", 18.4634, 73.8912),
    ("w1-nibm", "WARD-1", 18.4598, 73.9065),
    ("w1-yewalewadi", "WARD-1", 18.4363, 73.8965),
    ("w1-kondhwabudruk", "WARD-1", 18.4535, 73.9115),
    ("w1-bibvewadi", "WARD-1", 18.4620, 73.8677),
    ("a1-kondhwa", "WARD-1", 18.477091, 73.890686),
    ("a1-yewalewadi", "WARD-1", 18.4275046, 73.891336),
    ("w2-kothrud", "WARD-2", 18.5106, 73.8076),
    ("w2-karvenagar", "WARD-2", 18.4867, 73.8050),
    ("w2-erandwane", "WARD-2", 18.5071, 73.8310),
    ("w2-paudroad", "WARD-2", 18.5083, 73.7960),
    ("w2-vanaz", "WARD-2", 18.5090, 73.8230),
    ("w2-dahanukar", "WARD-2", 18.5120, 73.8170),
    ("a2-kothrud", "WARD-2", 18.5106, 73.8076),
    ("a2-karvenagar", "WARD-2", 18.4867, 73.8050),
    ("a2-erandwane", "WARD-2", 18.5071, 73.8310),
    ("w3-magarpatta", "WARD-3", 18.5159, 73.9263),
    ("w3-mundhwa", "WARD-3", 18.5347, 73.9355),
    ("w3-hadapsar", "WARD-3", 18.4995, 73.9256),
    ("w3-nhadapsar", "WARD-3", 18.5270, 73.9300),
    ("w3-magarpattas", "WARD-3", 18.5050, 73.9330),
    ("w3-hadapsargaon", "WARD-3", 18.5080, 73.9180),
    ("a3-hadapsar", "WARD-3", 18.499535, 73.925591),
    ("w4-vimannagar", "WARD-4", 18.5605, 73.9117),
    ("w4-yerwada", "WARD-4", 18.5584, 73.8821),
    ("w4-lohegaon", "WARD-4", 18.5787, 73.9137),
    ("w4-kharadi", "WARD-4", 18.5510, 73.9380),
    ("w4-vishrantwadi", "WARD-4", 18.5724, 73.8796),
    ("w4-dighi", "WARD-4", 18.5843, 73.8750),
    ("w4-dhanori", "WARD-4", 18.5765, 73.8960),
    ("a4-vimannagar", "WARD-4", 18.566526, 73.912239),
    ("a4-kalyani", "WARD-4", 18.5481, 73.9033),
    ("a4-kharadi", "WARD-4", 18.55222, 73.94361),
    ("x-shivajinagar", None, 18.5307, 73.8439),
    ("x-hyderabad", None, 17.4327, 78.3885),
    ("x-mumbai", None, 19.0760, 72.8777),
    ("x-peth", None, 18.5168, 73.8525),
    ("x-pimpri", None, 18.6175, 73.7995),
]

POINT = "ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)"


async def main():
    async with async_session_factory() as db:
        print("== wards ==")
        rows = (
            await db.execute(
                text(
                    "SELECT code, name, city, state, country, is_active "
                    "FROM wards WHERE code LIKE 'WARD-%' ORDER BY code"
                )
            )
        ).fetchall()
        for r in rows:
            print(r)

        print("\n== boundaries ==")
        rows = (
            await db.execute(
                text(
                    "SELECT w.code, b.is_demo, ST_IsValid(b.geom) AS valid, "
                    "round(ST_X(ST_Centroid(b.geom))::numeric,4) AS cx, "
                    "round(ST_Y(ST_Centroid(b.geom))::numeric,4) AS cy, "
                    "ST_Contains(b.geom, b.centroid) AS centroid_inside, "
                    "round((ST_Area(b.geom::geography)/1e6)::numeric,2) AS km2 "
                    "FROM ward_boundaries b JOIN wards w ON w.id=b.ward_id "
                    "WHERE w.code LIKE 'WARD-%' ORDER BY w.code"
                )
            )
        ).fetchall()
        for r in rows:
            print(r)

        print("\n== demo critical locations (expect 0) ==")
        n = (
            await db.execute(text("SELECT count(*) FROM critical_locations WHERE is_demo = true"))
        ).scalar_one()
        print("demo critical_locations:", n)
        total = (await db.execute(text("SELECT count(*) FROM critical_locations"))).scalar_one()
        print("total critical_locations:", total)

        print("\n== overlaps between reference ward polygons ==")
        overlaps = (
            await db.execute(
                text(
                    "SELECT wa.code AS w1, wb.code AS w2, "
                    "round((ST_Area(ST_Intersection(a.geom,b.geom))/2)::numeric,6) AS km2 "
                    "FROM ward_boundaries a CROSS JOIN ward_boundaries b "
                    "JOIN wards wa ON wa.id=a.ward_id JOIN wards wb ON wb.id=b.ward_id "
                    "WHERE wa.code LIKE 'WARD-%' AND wb.code LIKE 'WARD-%' "
                    "AND wa.code < wb.code AND ST_Intersects(a.geom, b.geom)"
                )
            )
        ).fetchall()
        print(overlaps if overlaps else "none")

        print("\n== point-in-polygon checks ==")
        fails = 0
        for label, expected, lat, lon in CHECKS:
            row = (
                await db.execute(
                    text(
                        f"SELECT w.code FROM ward_boundaries b JOIN wards w ON w.id=b.ward_id "
                        f"WHERE ST_Contains(b.geom, {POINT}) LIMIT 1"
                    ),
                    {"lon": lon, "lat": lat},
                )
            ).first()
            got = row[0] if row else None
            status = "OK " if got == expected else "FAIL"
            if got != expected:
                fails += 1
            print(f"{status} {label}: expected={expected} got={got}")
        print(f"\npoint-in-polygon failures: {fails}")

        print("\n== field workers: count by ward + home-base containment ==")
        fw_fails = 0
        fw_rows = (
            await db.execute(
                text(
                    "SELECT fw.home_latitude, fw.home_longitude, w.code "
                    "FROM field_workers fw JOIN users u ON u.id = fw.user_id "
                    "JOIN wards w ON w.id = u.ward_id "
                    "WHERE w.code LIKE 'WARD-%' ORDER BY u.email"
                )
            )
        ).fetchall()
        counts: dict[str, int] = {}
        for lat, lon, code in fw_rows:
            counts[code] = counts.get(code, 0) + 1
            row = (
                await db.execute(
                    text(
                        f"SELECT w.code FROM ward_boundaries b JOIN wards w ON w.id=b.ward_id "
                        f"WHERE ST_Contains(b.geom, {POINT}) LIMIT 1"
                    ),
                    {"lon": lon, "lat": lat},
                )
            ).first()
            in_ward = row[0] if row else None
            if in_ward != code:
                fw_fails += 1
                print(f"FAIL worker {lat},{lon} registered {code} but sits in {in_ward}")
        print("counts by ward:", counts, "| expected WARD-1=6 WARD-2=6 WARD-3=6 WARD-4=7")
        print(f"worker-home containment failures: {fw_fails}")


asyncio.run(main())
