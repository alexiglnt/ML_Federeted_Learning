"""Fill an empty database with a usable starting point.

Run by the entrypoint when MLFL_SEED_ON_START=1, and safe to run again: it
checks for existing content and does nothing rather than duplicating. Somebody
restarting this project cold should get a site with a populated registry and a
real example project, not an empty shell that looks broken.

    python -m api.seed
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.db import SessionLocal
from api.models import (
    AccessRole,
    Engine,
    Project,
    ProjectAccess,
    ProjectInput,
    ProjectStatus,
    ProjectTarget,
    ProjectVisibility,
    User,
    UserRole,
    Variable,
    VariableAlias,
    VariableStatus,
)
from api.security import hash_password
from api.services.naming import normalise

# --------------------------------------------------------------------------- #
# The registry
# --------------------------------------------------------------------------- #
# Aliases are seeded from the original site's column-matching hints, which were
# built against real files from real labs. "γ (°)" and "rβ (µm)" are the actual
# column headings of the study this platform grew out of — without these, those
# columns are unrecognisable.
#
# `penalised_sign` here is only a suggestion offered when a project adds the
# variable; the authoritative value lives on project_inputs. See
# ARCHITECTURE.md §3.
SEED_VARIABLES: list[dict] = [
    {
        "key": "rake_angle",
        "display_name": "Rake angle",
        "symbol": "γ",
        "unit": "deg",
        "dimension": "angle",
        "penalised_sign": -1.0,
        "description": "Tool rake angle. Negative rake is common in hard machining.",
        "aliases": ["gamma", "rake", "rake angle", "angle de coupe", "cutting angle"],
    },
    {
        "key": "edge_radius",
        "display_name": "Cutting edge radius",
        "symbol": "rβ",
        "unit": "um",
        "dimension": "length",
        "penalised_sign": -1.0,
        "description": "Radius of the cutting edge, sometimes called edge sharpness.",
        "aliases": ["r beta", "rbeta", "edge radius", "rayon arete", "acuite", "arete"],
    },
    {
        "key": "cutting_speed",
        "display_name": "Cutting speed",
        "symbol": "Vc",
        "unit": "m/min",
        "dimension": "speed",
        "penalised_sign": 1.0,
        "description": "Surface speed at the cutting edge.",
        "aliases": ["vc", "cutting speed", "vitesse de coupe", "speed", "surface speed"],
    },
    {
        "key": "uncut_chip_thickness",
        "display_name": "Uncut chip thickness",
        "symbol": "h",
        "unit": "mm",
        "dimension": "length",
        "penalised_sign": 1.0,
        "description": "Undeformed chip thickness. In orthogonal turning this is the feed.",
        "aliases": ["h", "chip thickness", "uncut chip thickness", "epaisseur", "thickness"],
    },
    {
        "key": "feed",
        "display_name": "Feed per revolution",
        "symbol": "f",
        "unit": "mm/rev",
        "dimension": "length",
        "description": "Feed rate per revolution.",
        "aliases": ["feed", "feed rate", "avance", "f"],
    },
    {
        "key": "depth_of_cut",
        "display_name": "Depth of cut",
        "symbol": "ap",
        "unit": "mm",
        "dimension": "length",
        "description": "Radial or axial engagement of the tool.",
        "aliases": ["ap", "depth of cut", "doc", "profondeur de passe"],
    },
    {
        "key": "nose_radius",
        "display_name": "Tool nose radius",
        "symbol": "rε",
        "unit": "mm",
        "dimension": "length",
        "aliases": ["nose radius", "r epsilon", "repsilon", "rayon de bec"],
    },
    {
        "key": "clearance_angle",
        "display_name": "Clearance angle",
        "symbol": "α",
        "unit": "deg",
        "dimension": "angle",
        "aliases": ["alpha", "clearance angle", "angle de depouille", "relief angle"],
    },
    {
        "key": "residual_stress_axial",
        "display_name": "Residual stress, axial",
        "symbol": "σ_L",
        "unit": "MPa",
        "dimension": "stress",
        "description": "Surface residual stress along the cutting direction. "
        "Compressive stress is negative.",
        "aliases": ["srs l", "srsl", "residual stress axial", "rs axial", "sigma l"],
    },
    {
        "key": "residual_stress_circumferential",
        "display_name": "Residual stress, circumferential",
        "symbol": "σ_T",
        "unit": "MPa",
        "dimension": "stress",
        "description": "Surface residual stress transverse to the cutting direction.",
        "aliases": [
            "srs t", "srst", "residual stress circumferential", "rs circumferential",
            "sigma t",
        ],
    },
    {
        "key": "surface_roughness_ra",
        "display_name": "Surface roughness Ra",
        "symbol": "Ra",
        "unit": "um",
        "dimension": "length",
        "description": "Arithmetic mean roughness of the machined surface.",
        "aliases": ["ra", "roughness", "surface roughness", "rugosite"],
    },
    {
        "key": "cutting_temperature",
        "display_name": "Cutting temperature",
        "symbol": "T",
        "unit": "degC",
        "dimension": "temperature",
        "aliases": ["temperature", "cutting temperature", "t"],
    },
    {
        "key": "cutting_force",
        "display_name": "Cutting force",
        "symbol": "Fc",
        "unit": "N",
        "dimension": "force",
        "aliases": ["fc", "cutting force", "effort de coupe", "force"],
    },
    {
        "key": "tool_wear_vb",
        "display_name": "Flank wear VB",
        "symbol": "VB",
        "unit": "mm",
        "dimension": "length",
        "aliases": ["vb", "flank wear", "tool wear", "usure"],
    },
]


def seed_variables(db: Session) -> dict[str, Variable]:
    by_key: dict[str, Variable] = {}
    for spec in SEED_VARIABLES:
        aliases = spec.pop("aliases", [])
        variable = db.scalar(select(Variable).where(Variable.key == spec["key"]))
        if variable is None:
            variable = Variable(**spec, status=VariableStatus.APPROVED)
            db.add(variable)
            db.flush()
            seen: set[str] = set()
            for raw in [spec["display_name"], *aliases]:
                alias = normalise(raw)
                if alias and alias not in seen:
                    seen.add(alias)
                    db.add(VariableAlias(variable_id=variable.id, alias=alias))
        by_key[variable.key] = variable
    return by_key


# --------------------------------------------------------------------------- #
# A demo project, from the study this platform started from
# --------------------------------------------------------------------------- #
# example.com, not a .invalid or .test domain: those are rejected by
# email-validator as special-use, so an account created with one here could
# never sign in through the API — the seed would produce a demo account that
# does not work.
DEMO_EMAIL = "demo@example.com"
# A weak, published password. This account exists only so that a fresh install
# is explorable; it must not be created on a public deployment, which is why
# seeding is behind MLFL_SEED_ON_START — see ROADMAP.md.
DEMO_PASSWORD = "demo-account-not-for-production"


def seed_demo_project(db: Session, variables: dict[str, Variable]) -> None:
    if db.scalar(select(Project).where(Project.slug == "ti-6al-4v-residual-stress")):
        return

    owner = db.scalar(select(User).where(User.email == DEMO_EMAIL))
    if owner is None:
        owner = User(
            email=DEMO_EMAIL,
            password_hash=hash_password(DEMO_PASSWORD),
            full_name="Demo Owner",
            institution="Example Lab",
            role=UserRole.USER,
        )
        db.add(owner)
        db.flush()

    project = Project(
        slug="ti-6al-4v-residual-stress",
        owner_id=owner.id,
        title="Residual stress in orthogonal turning of Ti-6Al-4V",
        description=(
            "Surface residual stress after orthogonal turning of Ti-6Al-4V, as a "
            "function of the four cutting parameters. Seeded from the seven "
            "conditions of the Outeiro 2022 study — which is exactly the problem "
            "this platform exists for: seven points is not enough to fit anything "
            "that generalises, and every lab in this field is in the same position."
        ),
        material="Ti-6Al-4V",
        process="orthogonal turning",
        visibility=ProjectVisibility.PUBLIC,
        status=ProjectStatus.DRAFT,
        main_engine=Engine.PIML,
        accepts_federated=True,
        licence="CC-BY-4.0",
    )
    db.add(project)
    db.flush()

    # Order matters and is stored: a contribution whose columns are permuted
    # produces silently wrong coefficients.
    inputs = [
        ("rake_angle", -1.0, -6.0, 10.0),
        ("edge_radius", -1.0, 16.0, 30.0),
        ("cutting_speed", 1.0, 20.0, 60.0),
        ("uncut_chip_thickness", 1.0, 0.15, 0.20),
    ]
    for position, (key, sign, low, high) in enumerate(inputs):
        db.add(
            ProjectInput(
                project_id=project.id,
                variable_id=variables[key].id,
                position=position,
                required=True,
                unit=variables[key].unit,
                penalised_sign=sign,
                expected_min=low,
                expected_max=high,
            )
        )

    for position, key in enumerate(
        ["residual_stress_axial", "residual_stress_circumferential"]
    ):
        db.add(
            ProjectTarget(
                project_id=project.id,
                variable_id=variables[key].id,
                position=position,
                unit=variables[key].unit,
            )
        )

    db.add(
        ProjectAccess(
            project_id=project.id, user_id=owner.id, role=AccessRole.OWNER
        )
    )


def main() -> None:
    db = SessionLocal()
    try:
        # Idempotence is the whole point: the entrypoint runs this on every
        # start, and a populated database must come out untouched.
        already = db.scalar(select(Variable.id).limit(1))
        variables = seed_variables(db)
        seed_demo_project(db, variables)
        db.commit()
        print(
            "[seed] registry ready"
            + ("" if already else f", demo account {DEMO_EMAIL}")
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
