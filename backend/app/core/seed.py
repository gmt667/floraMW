"""Database seed module for FloraMW Phase 1.

All data is transcribed verbatim from lib/models.dart and lib/locale_data.dart.
No botanical descriptions, section keys or source URLs are invented here.
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.district import District
from app.models.plant import Plant, PlantSection, PlantSource

# ---------------------------------------------------------------------------
# Districts — from lib/locale_data.dart const districtsByRegion
# ---------------------------------------------------------------------------
DISTRICTS_BY_REGION = {
    "Northern": [
        "Chitipa",
        "Karonga",
        "Likoma",
        "Mzimba",
        "Nkhata Bay",
        "Rumphi",
    ],
    "Central": [
        "Dedza",
        "Dowa",
        "Kasungu",
        "Lilongwe",
        "Mchinji",
        "Nkhotakota",
        "Ntcheu",
        "Ntchisi",
        "Salima",
    ],
    "Southern": [
        "Balaka",
        "Blantyre",
        "Chikwawa",
        "Chiradzulu",
        "Machinga",
        "Mangochi",
        "Mulanje",
        "Mwanza",
        "Neno",
        "Nsanje",
        "Phalombe",
        "Thyolo",
        "Zomba",
    ],
}

# ---------------------------------------------------------------------------
# Shared pending section prose — from lib/models.dart const pending
# ---------------------------------------------------------------------------
_PENDING = {
    "Local names & knowledge": (
        "Malawian names and reported uses are awaiting community verification. "
        "Records should include language, district, plant part, attribution and "
        "permission. A traditional belief does not establish that a plant cures disease."
    ),
    "Medicinal research": (
        "No therapeutic claim has been reviewed in this demonstration. A verified "
        "record will distinguish isolated compounds, laboratory studies, clinical "
        "evidence and approved medicines. Do not infer that a flower itself can "
        "safely replace a manufactured drug."
    ),
    "Malawi distribution": (
        "District occurrence, native or introduced status, habitat and altitude have "
        "not been verified. This sample catalogue does not establish that this species "
        "occurs in Malawi."
    ),
    "Growing conditions": (
        "Species-specific sunlight, temperature, soil, rainfall and drainage "
        "information is pending horticultural review."
    ),
    "Plant care & treatment": (
        "Watering, propagation, pruning, flowering season and pest management are "
        "pending review. Confirm the plant identity before applying a treatment."
    ),
    "Effects & precautions": (
        "Do not eat or prepare medicine from an unidentified plant. Photo "
        "identification can be wrong. Toxicity, drug interactions, allergies and "
        "risks for children, pregnancy and breastfeeding require qualified review."
    ),
    "Legal & conservation": (
        "No legal status has been assessed. Protected status, collection and "
        "harvesting permits, trade restrictions and medicine manufacturing rules need "
        "current Malawi authority references. This app does not grant permission to "
        "harvest or sell plants."
    ),
    "Sources & review": (
        "Public botanical sources checked on 8 November 2026. This is an educational "
        "summary, not an independent botanical or clinical review. Malawi district "
        "occurrence and local traditional uses remain unverified. Open the source "
        "links below for context."
    ),
}

# Reusable legal summary (from lib/models.dart const legalSummary)
_LEGAL_SUMMARY = (
    "Malawi\u2019s Pharmacy and Medicines Regulatory Authority regulates medicines and "
    "traditional medicinal products. Consult PMRA before manufacturing or marketing a "
    "medicine. Species-specific harvesting permissions and protected status are not "
    "assessed here. A plant profile is not a permit."
)

# Reusable PMRA source (from lib/models.dart const pmraSource)
_PMRA_SOURCE = {
    "title": "PMRA \u00b7 mandate and regulated products",
    "url": "https://www.pmra.mw/who-we-are/",
    "is_pmra_reference": True,
}

# ---------------------------------------------------------------------------
# Plant catalogue — transcribed from lib/models.dart final plants = <Plant>[...]
# ---------------------------------------------------------------------------
PLANTS_DATA = [
    {
        "id": "hibiscus",
        "name": "Chinese hibiscus",
        "scientific": "Hibiscus rosa-sinensis",
        "family": "Malvaceae",
        "category": "Garden flowers",
        "symbol": "\U0001f33a",
        "description": (
            "A tropical evergreen shrub in the mallow family, known for large "
            "flowers with a prominent central floral tube."
        ),
        "sections": {
            **_PENDING,
            "Identifying features": (
                "Large funnel-shaped flowers; a conspicuous central floral tube; "
                "glossy leaves with toothed edges. Cultivars vary. These features "
                "alone do not confirm an identification."
            ),
            "Growing conditions": (
                "NC State Extension describes sun to partial shade and fertile, moist "
                "soil that drains well. Protect from frost and strong wind. This "
                "general care guidance is not a Malawi district suitability assessment."
            ),
            "Plant care & treatment": (
                "Keep the root zone moist without waterlogging. Stem cuttings are "
                "used for propagation. Watch for scale insects. Obtain local "
                "horticultural advice before using pesticides."
            ),
            "Medicinal research": (
                "No approved medicinal use is asserted for this species in FloraMW. "
                "Do not confuse it with other Hibiscus species or transfer claims "
                "about a different species to this flower."
            ),
            "Legal & conservation": _LEGAL_SUMMARY,
        },
        "sources": [
            {
                "title": "NC State Extension \u00b7 Chinese hibiscus",
                "url": "https://plants.ces.ncsu.edu/plants/hibiscus-rosa-sinensis/",
                "is_pmra_reference": False,
            },
            _PMRA_SOURCE,
        ],
    },
    {
        "id": "periwinkle",
        "name": "Madagascar periwinkle",
        "scientific": "Catharanthus roseus",
        "family": "Apocynaceae",
        "category": "Research interest",
        "symbol": "\U0001f338",
        "description": (
            "A flowering plant with glossy opposite leaves and typically five "
            "spreading flower lobes. Its medicinal compounds do not make the whole "
            "plant safe to consume."
        ),
        "sections": {
            **_PENDING,
            "Identifying features": (
                "Opposite glossy leaves with a pale midrib and flowers with a narrow "
                "tube opening into five broad lobes. Pink and white forms occur. "
                "Compare multiple features and seek expert confirmation."
            ),
            "Growing conditions": (
                "NC State Extension describes sun to partial shade and freely draining "
                "soil. It tolerates heat and some dry conditions. Avoid persistently "
                "wet roots."
            ),
            "Plant care & treatment": (
                "Seed propagation is common. Some cultivars resist certain fungal "
                "problems; cultivar resistance does not mean immunity. Seek "
                "horticultural advice for rot or blight."
            ),
            "Medicinal research": (
                "The US National Cancer Institute identifies vinblastine as a "
                "plant-derived alkaloid from Catharanthus roseus. Vincristine is a "
                "related chemotherapy drug. These are manufactured medicines used "
                "under specialist care; consuming the plant is not a cancer treatment."
            ),
            "Effects & precautions": (
                "Queensland Poisons Information Centre describes all parts as toxic. "
                "Ingestion can cause illness. Do not make teas, extracts or home "
                "remedies from this plant. If exposure causes symptoms, seek medical "
                "attention."
            ),
            "Legal & conservation": _LEGAL_SUMMARY,
        },
        "sources": [
            {
                "title": "NC State Extension \u00b7 periwinkle care and features",
                "url": "https://plants.ces.ncsu.edu/plants/catharanthus-roseus/",
                "is_pmra_reference": False,
            },
            {
                "title": "National Cancer Institute \u00b7 vinblastine sulfate",
                "url": "https://www.cancer.gov/publications/dictionaries/cancer-drug/def/vinblastine-sulfate",
                "is_pmra_reference": False,
            },
            {
                "title": "National Cancer Institute \u00b7 vincristine sulfate",
                "url": "https://www.cancer.gov/about-cancer/treatment/drugs/vincristinesulfate",
                "is_pmra_reference": False,
            },
            {
                "title": "Queensland Health \u00b7 periwinkle toxicity",
                "url": "https://www.poisonsinfo.health.qld.gov.au/plants-and-mushrooms/periwinkle-catharanthus-roseus",
                "is_pmra_reference": False,
            },
            _PMRA_SOURCE,
        ],
    },
    {
        "id": "marigold",
        "name": "African marigold",
        "scientific": "Tagetes erecta",
        "family": "Asteraceae",
        "category": "Garden flowers",
        "symbol": "\U0001f33c",
        "description": (
            "An upright flowering annual with dense flower heads. Despite its common "
            "name, it originates from Mexico and Guatemala."
        ),
        "sections": {
            **_PENDING,
            "Identifying features": (
                "Dense yellow or orange flower heads and divided aromatic leaves are "
                "useful comparison features. Cultivars differ, and similar marigolds "
                "can be confused."
            ),
            "Growing conditions": (
                "NC State Extension recommends full sun and well-drained soil, with "
                "reasonably even moisture. Light afternoon shade can be tolerated."
            ),
            "Plant care & treatment": (
                "Remove spent flower heads. Taller plants may need support from "
                "strong wind. Young shoots can be pinched for bushier growth. Look "
                "out for leaf spots, mildew and rot; avoid diagnosing a disease from "
                "a single image."
            ),
            "Effects & precautions": (
                "Sap can cause skin irritation; some plant compounds can cause "
                "reactions in contact with sunlight. Avoid contact with eyes and do "
                "not assume ornamental plants are edible."
            ),
            "Legal & conservation": _LEGAL_SUMMARY,
        },
        "sources": [
            {
                "title": "NC State Extension \u00b7 African marigold",
                "url": "https://plants.ces.ncsu.edu/plants/tagetes-erecta/",
                "is_pmra_reference": False,
            },
            _PMRA_SOURCE,
        ],
    },
    {
        "id": "frangipani",
        "name": "Frangipani",
        "scientific": "Plumeria rubra",
        "family": "Apocynaceae",
        "category": "Flowering trees",
        "symbol": "\U0001f33f",
        "description": (
            "A tropical flowering tree native from Mexico to Venezuela, according to "
            "Kew. A reference photograph is not evidence of local occurrence."
        ),
        "sections": {
            **_PENDING,
            "Identifying features": (
                "A small tree with thick branches and clusters of flowers. Flower "
                "colour varies. Related Plumeria species can look similar, so check "
                "leaves and other features with a specialist."
            ),
            "Growing conditions": (
                "Singapore National Parks describes full sun, moderate watering and "
                "well-drained soil. This is general horticultural guidance, not a "
                "Malawi district planting guarantee."
            ),
            "Plant care & treatment": (
                "Poor drainage can encourage root rot. Scale insects and caterpillars "
                "are among reported pests. Prune for structure with appropriate "
                "protective equipment and local horticultural advice."
            ),
            "Effects & precautions": (
                "University of California guidance treats Plumeria plants as toxic "
                "and warns that sap can irritate skin. Wear gloves and protect eyes "
                "during pruning. Keep cut material away from children and pets."
            ),
            "Legal & conservation": _LEGAL_SUMMARY,
        },
        "sources": [
            {
                "title": "Kew \u00b7 Plumeria rubra taxonomy and native range",
                "url": "https://powo.science.kew.org/taxon/81275-1",
                "is_pmra_reference": False,
            },
            {
                "title": "Singapore National Parks \u00b7 frangipani care",
                "url": "https://www.nparks.gov.sg/florafaunaweb/flora/3/0/3074",
                "is_pmra_reference": False,
            },
            {
                "title": "University of California \u00b7 Plumeria safety",
                "url": "https://ucanr.edu/site/plant-safely-drought-tolerant-landscapes/plumeria-spp",
                "is_pmra_reference": False,
            },
            _PMRA_SOURCE,
        ],
    },
]

# Expected section keys for all plants (the 8 pending + "Identifying features")
# Note: not all plants have all 9 — marigold and hibiscus have 9; periwinkle/frangipani
# override some pending keys. The backend stores whatever each plant defines.
ALL_SECTION_KEYS = list(_PENDING.keys()) + ["Identifying features"]


# ---------------------------------------------------------------------------
# Seed functions
# ---------------------------------------------------------------------------


async def seed_districts(session: AsyncSession) -> int:
    """Seed all 28 Malawi districts. Idempotent — skips existing records."""
    count = 0
    for region, names in DISTRICTS_BY_REGION.items():
        for name in names:
            existing = await session.scalar(
                select(District).where(District.name == name)
            )
            if not existing:
                session.add(District(name=name, region=region))
                count += 1
    if count:
        await session.commit()
    return count


async def seed_plants(session: AsyncSession) -> int:
    """Seed the 4 reference plants with sections and sources. Idempotent."""
    count = 0
    for pdata in PLANTS_DATA:
        existing = await session.scalar(
            select(Plant).where(Plant.id == pdata["id"])
        )
        if not existing:
            plant = Plant(
                id=pdata["id"],
                common_name_en=pdata["name"],
                scientific_name=pdata["scientific"],
                family=pdata["family"],
                category=pdata["category"],
                symbol=pdata["symbol"],
                description=pdata["description"],
                is_published=True,
            )
            session.add(plant)
            await session.flush()

            for key, content in pdata["sections"].items():
                # Classify section metadata heuristically
                content_lower = content.lower()
                if "toxic" in content_lower or "irritat" in content_lower:
                    disclaimer = "toxicity_warning"
                else:
                    disclaimer = "educational_summary"

                pending_keys = set(_PENDING.keys())
                if key in pending_keys and (
                    "awaiting" in content_lower
                    or "pending" in content_lower
                    or "not been verified" in content_lower
                    or "not been assessed" in content_lower
                    or "no legal status" in content_lower
                ):
                    verification = "pending_review"
                else:
                    verification = "verified"

                session.add(
                    PlantSection(
                        plant_id=plant.id,
                        section_key=key,
                        content=content,
                        content_disclaimer_type=disclaimer,
                        verification_status=verification,
                    )
                )

            for sdata in pdata["sources"]:
                session.add(
                    PlantSource(
                        plant_id=plant.id,
                        title=sdata["title"],
                        url=sdata["url"],
                        is_pmra_reference=sdata["is_pmra_reference"],
                    )
                )

            count += 1

    if count:
        await session.commit()
    return count


async def seed_all(session: AsyncSession) -> dict:
    """Execute complete initial database seeding. Safe to call multiple times."""
    d_count = await seed_districts(session)
    p_count = await seed_plants(session)
    return {"districts_seeded": d_count, "plants_seeded": p_count}
