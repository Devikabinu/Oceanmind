"""Rule-based grouping of OBIS/WoRMS taxonomy into the broad categories shown in the UI."""

GROUPS = [
    "Marine mammals",
    "Sea turtles",
    "Sharks & rays",
    "Fish",
    "Seabirds",
    "Corals",
    "Other marine organisms",
]


def classify_group(taxon: dict) -> str:
    cls = (taxon.get("class") or "").strip()
    order = (taxon.get("order") or "").strip()
    if cls == "Mammalia":
        return "Marine mammals"
    if order == "Testudines":  # OBIS leaves `class` empty for turtles (superclass Reptilia); the order is reliable
        return "Sea turtles"
    if cls == "Elasmobranchii":
        return "Sharks & rays"
    if cls in ("Teleostei", "Actinopteri", "Actinopterygii", "Holocephali", "Myxini", "Petromyzonti"):
        return "Fish"
    if cls == "Aves":
        return "Seabirds"
    if cls in ("Anthozoa", "Hexacorallia", "Octocorallia"):
        return "Corals"
    return "Other marine organisms"


# IUCN Red List categories (codes as reported by GBIF / OBIS). A category is only ever shown when a source reports it.
IUCN_LABELS = {
    "EX": "Extinct",
    "EW": "Extinct in the Wild",
    "CR": "Critically Endangered",
    "EN": "Endangered",
    "VU": "Vulnerable",
    "NT": "Near Threatened",
    "LC": "Least Concern",
    "DD": "Data Deficient",
    "NE": "Not Evaluated",
}
CONSERVATION_SENSITIVE = ("CR", "EN", "VU")  # "threatened" categories
