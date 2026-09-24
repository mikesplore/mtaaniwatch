"""Idempotently load clearly labeled Mombasa demo records."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Area, Crew, Report, Task, TaskStatus, TaskStatusHistory


AREAS = [    
    # --- Mainland North (Changamwe/Jomvu) ---
    ("Mbaraki", "Major industrial hub with residential estates."),
    ("Miritini", "Residential area along the Mombasa-Nairobi highway."),
    ("Bamburi", "Residential area near the Moi International Sports Complex."),
    ("Changamwe", "High-density residential area, home to Changamwe Hospital."),
    ("Mjamboni", "Residential area near Jomvu Industrial Area."),
    ("Magogoni", "Residential area near Changamwe."),
    ("Mshomoroni", "Residential area in the northern mainland."),
    ("Mkondoni", "Residential area near Bamburi."),
    ("Mwaro", "Residential area near Mtopanga."),
    ("Mtepeni", "Residential area near Jomvu."),
    ("Mchongoano", "Informal settlement area near Mtopanga."),
    ("Mwembe Tayari", "Residential area known for its local market."),
    ("Makadara", "High-density residential area."),

    # --- Mainland South (Likoni/Nyali Bridge approach) ---
    ("Likoni", "Gateway to the South Coast, busy ferry terminal area."),
    ("Mtongwe", "Residential area near the Likoni Ferry."),
    ("Bofu", "Industrial and residential area near the port."),
    ("Port Reitz", "Area surrounding the Port Reitz Creek and airport."),
    ("Kipevu", "Industrial area near the oil terminals and airport."),

    # --- Island North (Nyali/Mkomani) ---
    ("Kongowea", "Dense residential and market area; resident-reported landmarks should be confirmed."),
    ("Nyali", "Upscale residential and commercial area."),
    ("Mkomani", "Dense residential area near Nyali Bridge."),
    ("Frere Town", "Historic residential area near the coast."),
    ("Kizingo", "Mixed residential and commercial area."),
    ("Tudor", "Residential area near the Tudor Creek bridge."),
    ("Shanzu", "Coastal residential area with hotels and homes."),
    ("Bamburi Beach", "Coastal strip near Bamburi."),

    # --- Island Central (CBD/Old Town) ---
    ("Mji wa Kale", "Old Town, historic buildings and narrow alleys."),
    ("Mnazi", "Residential area near the CBD."),
    ("Pangani", "Residential area near the CBD."),
    ("Tononoka", "Busy transport and commercial hub."),
    ("Majengo", "High-density residential area near the CBD."),
    ("Landhies", "Commercial and residential area near the port."),

    # --- Island South (South Coast) ---
    ("Shimoni", "Coastal area further south, known for marine parks."),
    ("Vikwatani", "Residential area on the South Coast."),
    ("Mtambwe", "Coastal residential area."),
    ("Diwani", "Residential area on the South Coast."),
    ("Ukunda", "Growing residential area on the South Coast."),
    ("Tiwi", "Coastal area near Diani, further south."),
]

CREWS = [
    ("Mombasa County Drainage Team A", None),
    ("Changamwe Community Volunteers", "Changamwe"),
    ("Jomvu Rapid Response Unit", "Mjamboni"),
    ("Nyali Clean-Up Crew", "Nyali"),
    ("Coast Cleaners Collective", None),
    ("Likoni Ferry Wardens", "Likoni"),
]

REPORTS = [
    {
        "reference": "MW-2026-001", "category": "blocked_drain", "area": "Changamwe",
        "landmark": "Near Changamwe Hospital main gate",
        "impact": "Water pooling on the road, blocking ambulance access.",
        "summary": "Drain has been blocked by plastic waste for two days. Rain is expected tonight.",
        "language": "sw", "source": "sms", "verified": False,
        "created": "2026-09-24 08:30:00", "status": "reported", "crew": None, "history": [],
    },
    {
        "reference": "MW-2026-002", "category": "garbage_collection", "area": "Makadara",
        "landmark": "Opposite Makadara Market entrance",
        "impact": "Bad smell and stray animals scattering waste.",
        "summary": "Heap of garbage not collected for a week. Blocking the sidewalk.",
        "language": "en", "source": "voice_call", "verified": True,
        "created": "2026-09-23 14:15:00", "status": "in_progress", "crew": "Changamwe Community Volunteers",
        "history": [("reported", "Report verified by coordinator.", "2026-09-23 14:20:00"),
                    ("in_progress", "Crew dispatched.", "2026-09-23 16:00:00")],
    },
    {
        "reference": "MW-2026-003", "category": "flooding", "area": "Mjamboni",
        "landmark": "Mjamboni Stage near the petrol station",
        "impact": "Pedestrians cannot cross; matatus detouring.",
        "summary": "Heavy rain caused drain overflow. Water is knee-deep.",
        "language": "sw", "source": "whatsapp", "verified": True,
        "created": "2026-09-22 07:00:00", "status": "resolved", "crew": "Jomvu Rapid Response Unit",
        "history": [("reported", "High priority due to location.", "2026-09-22 07:10:00"),
                    ("in_progress", "Crew clearing debris.", "2026-09-22 09:30:00"),
                    ("resolved", "Drain cleared, water receding.", "2026-09-22 13:45:00")],
    },
    {
        "reference": "MW-2026-004", "category": "infrastructure", "area": "Mji wa Kale",
        "landmark": "Corner of Biashara Street and Nkrumah Street",
        "impact": "Security risk at night.", "summary": "Streetlight has been off for three days.",
        "language": "en", "source": "web_form", "verified": False,
        "created": "2026-09-21 19:00:00", "status": "cancelled", "crew": None,
        "history": [("reported", "Pending verification.", "2026-09-21 19:05:00"),
                    ("cancelled", "Duplicate report already being handled by another utility.", "2026-09-22 10:00:00")],
    },
    {
        "reference": "MW-2026-005", "category": "blocked_drain", "area": "Kipevu",
        "landmark": "Near Kipevu Oil Terminal entrance", "impact": "Foul smell entering nearby houses.",
        "summary": "Drain covered by industrial sludge and leaves.", "language": "sw", "source": "sms",
        "verified": False, "created": "2026-09-24 09:15:00", "status": "reported", "crew": None, "history": [],
    },
    {
        "reference": "MW-2026-006", "category": "garbage_collection", "area": "Miritini",
        "landmark": "Behind Miritini Estate Block C", "impact": "Fire hazard due to dry waste.",
        "summary": "Large pile of cardboard and plastics accumulating.", "language": "en", "source": "voice_call",
        "verified": True, "created": "2026-09-23 11:00:00", "status": "in_progress", "crew": "Coast Cleaners Collective",
        "history": [("reported", "Verified via photo.", "2026-09-23 11:10:00"),
                    ("in_progress", "Truck en route.", "2026-09-23 14:00:00")],
    },
    {
        "reference": "MW-2026-007", "category": "flooding", "area": "Changamwe",
        "landmark": "Changamwe Market main entrance", "impact": "Vendors unable to set up stalls.",
        "summary": "Rainwater from the hill has flooded the market path.", "language": "sw", "source": "whatsapp",
        "verified": True, "created": "2026-09-20 06:30:00", "status": "resolved", "crew": "Changamwe Community Volunteers",
        "history": [("reported", "Urgent.", "2026-09-20 06:45:00"),
                    ("in_progress", "Digging temporary channel.", "2026-09-20 08:00:00"),
                    ("resolved", "Water diverted.", "2026-09-20 12:00:00")],
    },
    {
        "reference": "MW-2026-008", "category": "infrastructure", "area": "Mjamboni",
        "landmark": "Mjamboni Health Centre perimeter wall",
        "impact": "Wall collapsing onto the footpath.", "summary": "Section of the wall is cracked and leaning.",
        "language": "en", "source": "web_form", "verified": False,
        "created": "2026-09-24 10:00:00", "status": "reported", "crew": None, "history": [],
    },
    {
        "reference": "MW-2026-009", "category": "garbage_collection", "area": "Nyali",
        "landmark": "Near Nyali Shopping Centre back entrance",
        "impact": "Unsightly waste affecting tourist area aesthetics.",
        "summary": "Several bags of waste left outside the compound wall.",
        "language": "en", "source": "web_form", "verified": True,
        "created": "2026-09-24 11:30:00", "status": "in_progress", "crew": "Nyali Clean-Up Crew",
        "history": [("reported", "Verified by coordinator.", "2026-09-24 11:45:00"),
                    ("in_progress", "Clean-up crew assigned.", "2026-09-24 12:00:00")],
    },
    {
        "reference": "MW-2026-010", "category": "blocked_drain", "area": "Likoni",
        "landmark": "Near Likoni Ferry terminal queue area",
        "impact": "Foul smell and potential health hazard for commuters.",
        "summary": "Drain blocked by sand and waste near the ferry approach.",
        "language": "sw", "source": "sms", "verified": False,
        "created": "2026-09-24 13:00:00", "status": "reported", "crew": None, "history": [],
    }
]


def dt(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=ZoneInfo("Africa/Nairobi")).astimezone(timezone.utc)


def seed() -> None:
    with SessionLocal.begin() as db:
        areas: dict[str, Area] = {}
        for name, description in AREAS:
            area = db.scalar(select(Area).where(Area.name == name))
            if area is None:
                area = Area(name=name, description=description, is_demo=True)
                db.add(area)
            areas[name] = area
        db.flush()

        crews: dict[str, Crew] = {}
        for name, area_name in CREWS:
            crew = db.scalar(select(Crew).where(Crew.name == name))
            if crew is None:
                crew = Crew(name=name, home_area=areas.get(area_name), is_demo=True)
                db.add(crew)
            crews[name] = crew
        db.flush()

        for item in REPORTS:
            if db.scalar(select(Report).where(Report.reference == item["reference"])):
                continue
            report = Report(
                reference=item["reference"], category=item["category"], area=item["area"],
                area_ref=areas[item["area"]], landmark=item["landmark"],
                impact_reported=[item["impact"]], summary=item["summary"], language=item["language"],
                source=item["source"], is_demo=True, verified=item["verified"], created_at=dt(item["created"]),
            )
            task_status = TaskStatus(item["status"])
            task = Task(report=report, crew_ref=crews.get(item["crew"]), crew_name=item["crew"],
                        status=task_status, created_at=dt(item["created"]))
            events = item["history"] or [("reported", "Report received.", item["created"])]
            for status, note, created_at in events:
                task.history.append(TaskStatusHistory(status=TaskStatus(status), note=note, created_at=dt(created_at)))
            db.add(report)
            db.add(task)


if __name__ == "__main__":
    seed()
    print("Demo areas, crews, and reports are seeded.")
