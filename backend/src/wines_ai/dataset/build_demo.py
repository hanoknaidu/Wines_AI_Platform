"""Build the demo artifact: the seed, plus illustrative producer names.

    python -m wines_ai.dataset.build_demo

Why this is a script and not a hand-written JSON file: it reads `wines.seed.json` and
changes exactly three things per row - `example_producers`, `review_status` and
`dataset_version`. Every other field is copied through byte-identically, so the demo
can never drift from the seed on a taste axis, a description or a region, and re-running
it after a seed change is free. The delta is auditable by reading PRODUCERS below.

**What these names are, and are not.** They are well-documented producers associated
with each variety and the regions already on the row. They were written from model
knowledge and have NOT been checked by a person against a label, an importer or a
registry. That is the whole reason the rows ship as `review_status: "fixture"` rather
than `"reviewed"`: section 9 of the backend plan calls producer names the weakest point
in the system and the one field a model confabulates, and `schema.py` refuses to let a
fixture row carry a `reviewed_by` signature. A fixture row is unverified by definition.

To promote a row to `reviewed`, a person checks the names, then stamps `review_status`
and `reviewed_by` - which is the review pipeline, not this script's job.
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SEED = HERE / "seed" / "wines.seed.json"
OUT = HERE / "seed" / "wines.demo.json"

DEMO_VERSION = "demo-0.1"

NOTES = (
    "Demo artifact. Identical to wines.seed.json on every taste axis, description and "
    "region - the only differences are example_producers, review_status and "
    "dataset_version. review_status is 'fixture' on every row: the producer names are "
    "illustrative and have NOT been verified by a person, and schema.py forbids a "
    "fixture row from carrying a reviewed_by signature. Use this to demo a full card; "
    "do not treat the producer names as checked facts. Load with "
    "WA_DATASET_PATH=.../wines.demo.json."
)

# row_id -> producers, chosen to sit inside the regions already on that row.
PRODUCERS: dict[str, list[str]] = {
    # --- red ---------------------------------------------------------------
    "w-0001": ["Château Léoville-Barton", "Stag's Leap Wine Cellars", "Wynns Coonawarra Estate"],
    "w-0002": ["Château La Conseillante", "Leonetti Cellar", "Ornellaia"],
    "w-0003": ["Domaine Dujac", "Domaine Drouhin Oregon", "Felton Road"],
    "w-0004": ["Château Rayas", "Clos Mogador", "Yalumba"],
    "w-0005": ["Catena Zapata", "Achaval-Ferrer", "Château du Cèdre"],
    "w-0006": ["Domaine Jean-Louis Chave", "Penfolds", "Craggy Range"],
    "w-0007": ["Giacomo Conterno", "Bruno Giacosa", "Produttori del Barbaresco"],
    "w-0008": ["Fontodi", "Isole e Olena", "Castello di Monsanto"],
    "w-0009": ["Marcel Lapierre", "Jean Foillard", "Château Thivin"],
    "w-0010": ["La Rioja Alta", "R. López de Heredia", "Vega Sicilia"],
    "w-0011": ["Concha y Toro", "Viña Errázuriz", "Santa Rita"],
    "w-0012": ["Ridge Vineyards", "Turley Wine Cellars", "Klinker Brick"],
    "w-0013": ["Giuseppe Quintarelli", "Dal Forno Romano", "Masi"],
    # --- white -------------------------------------------------------------
    "w-0014": ["Domaine Leflaive", "Kistler Vineyards", "Leeuwin Estate"],
    "w-0015": ["Domaine William Fèvre", "Domaine Raveneau", "Jean-Marc Brocard"],
    "w-0016": ["Cloudy Bay", "Greywacke", "Didier Dagueneau"],
    "w-0017": ["Alois Lageder", "Elena Walch", "Santa Margherita"],
    "w-0018": ["Trimbach", "Domaine Weinbach", "Grosset"],
    "w-0019": ["Dr. Loosen", "Joh. Jos. Prüm", "Hermann J. Wiemer"],
    "w-0020": ["Joh. Jos. Prüm", "Egon Müller", "Robert Weil"],
    "w-0021": ["Domaine Huet", "François Chidaine", "Sadie Family Wines"],
    "w-0022": ["Domaine Zind-Humbrecht", "Trimbach", "Cantina Tramin"],
    "w-0023": ["Pazo de Señoráns", "Do Ferreiro", "Zárate"],
    "w-0024": ["E. Guigal", "Georges Vernay", "André Perret"],
    "w-0025": ["Weingut Hirtzberger", "F.X. Pichler", "Schloss Gobelsburg"],
    "w-0026": ["Tyrrell's Wines", "Mount Pleasant", "Château Smith Haut Lafitte"],
    # --- rose --------------------------------------------------------------
    "w-0027": ["Domaine Tempier", "Château d'Esclans", "Domaines Ott"],
    "w-0028": ["Domaine Vacheron", "Lucien Crochet", "Soter Vineyards"],
    "w-0029": ["Fattoria Le Pupille", "Castello di Ama", "Antinori"],
    "w-0030": ["Sutter Home", "Beringer", "Barefoot"],
    "w-0031": ["Domaine des Baumard", "Château de Fesles", "Domaine Ogereau"],
    "w-0032": ["Franz Haas", "Cantina Tramin", "Castel Sallegg"],
    # --- sparkling ---------------------------------------------------------
    "w-0033": ["Bollinger", "Pol Roger", "Louis Roederer"],
    "w-0034": ["Langlois-Château", "Bouvet-Ladubay", "Domaine des Baumard"],
    "w-0035": ["Recaredo", "Gramona", "Codorníu"],
    "w-0036": ["Nino Franco", "Bisol", "Adami"],
    "w-0037": ["Cleto Chiarli", "Medici Ermete", "Cavicchioli"],
    "w-0038": ["Fontanafredda", "Martini & Rossi", "Cinzano"],
    # --- dessert -----------------------------------------------------------
    "w-0039": ["Château d'Yquem", "Château Climens", "Château Coutet"],
    "w-0040": ["Taylor's", "Graham's", "Niepoort"],
    "w-0041": ["Vietti", "Paolo Saracco", "La Spinetta"],
    "w-0042": ["Royal Tokaji", "Disznókő", "Oremus"],
    "w-0043": ["Dr. Loosen", "Inniskillin", "Pillitteri Estates"],
    "w-0044": ["González Byass", "Emilio Lustau", "Osborne"],
    "w-0045": ["Avignonesi", "Isole e Olena", "Fèlsina"],
}


def build() -> dict:
    artifact = json.loads(SEED.read_text(encoding="utf-8"))

    seed_ids = {row["row_id"] for row in artifact["rows"]}
    missing = seed_ids - PRODUCERS.keys()
    extra = PRODUCERS.keys() - seed_ids
    # A seed row with no entry would ship an empty producer list under a fixture status,
    # which reads as "we checked and there are none" - the one claim this must not make.
    if missing:
        raise SystemExit(f"no producers for rows: {sorted(missing)}")
    if extra:
        raise SystemExit(f"producers for rows not in the seed: {sorted(extra)}")

    for row in artifact["rows"]:
        row["example_producers"] = list(PRODUCERS[row["row_id"]])
        row["review_status"] = "fixture"
        row["reviewed_by"] = None
        row["reviewed_at"] = None
        row["dataset_version"] = DEMO_VERSION

    artifact["dataset_version"] = DEMO_VERSION
    artifact["notes"] = NOTES
    return artifact


def main() -> None:
    artifact = build()

    # Validate before writing, with the same model the loader uses at startup: a demo
    # artifact that fails readyz is worse than no demo artifact.
    from .schema import DatasetArtifact

    DatasetArtifact.model_validate(artifact)

    OUT.write_text(json.dumps(artifact, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    rows = artifact["rows"]
    print(f"wrote {OUT}")
    print(f"  dataset_version: {artifact['dataset_version']}")
    print(f"  rows:            {len(rows)}")
    print(f"  producers:       {sum(len(r['example_producers']) for r in rows)} names")
    fixtures = sum(1 for r in rows if r["review_status"] == "fixture")
    print(f"  review_status:   fixture on {fixtures}")


if __name__ == "__main__":
    main()
