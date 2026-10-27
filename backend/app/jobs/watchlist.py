"""Species the platform syncs OBIS records for by default.

This is a curated LIST OF NAMES ONLY (a choice of what to monitor: charismatic / conservation-relevant marine taxa that
occur in or migrate through the NE Pacific study region and the wider ocean). Every fact about them (AphiaID, taxonomy,
common name, conservation category, observations) is fetched from OBIS / WoRMS at sync time. Edit freely; users can also
add any other OBIS species from the Species page.
"""

WATCHLIST = [
    # marine mammals
    "Megaptera novaeangliae", "Eschrichtius robustus", "Balaenoptera musculus", "Balaenoptera physalus",
    "Orcinus orca", "Zalophus californianus", "Mirounga angustirostris", "Enhydra lutris",
    # sea turtles
    "Chelonia mydas", "Dermochelys coriacea", "Caretta caretta", "Lepidochelys olivacea",
    # sharks and large fish
    "Carcharodon carcharias", "Prionace glauca", "Isurus oxyrinchus", "Thunnus orientalis", "Mola mola",
    "Sardinops sagax", "Engraulis mordax",
    # seabirds
    "Phoebastria nigripes", "Phoebastria immutabilis", "Uria aalge",
    # corals
    "Porites lobata", "Pocillopora meandrina",
    # other
    "Dosidicus gigas",
]


# Pacific-wide list (names only; status, taxonomy and records come from OBIS / WoRMS / GBIF-IUCN at sync time): taxa that occur in the tropical, western,
# central, southern and eastern Pacific and that carry IUCN assessments, so that threatened-species exposure can be assessed across the basin.
PACIFIC_WATCHLIST = WATCHLIST + [
    # marine mammals
    "Balaenoptera borealis", "Balaenoptera omurai", "Physeter macrocephalus", "Eubalaena japonica", "Dugong dugon", "Neophocaena phocaenoides",
    "Zalophus wollebaeki", "Arctocephalus galapagoensis", "Phocoenoides dalli", "Eumetopias jubatus", "Callorhinus ursinus",
    # sea turtles
    "Eretmochelys imbricata", "Natator depressus",
    # sharks, rays and large fish
    "Rhincodon typus", "Sphyrna lewini", "Carcharhinus longimanus", "Carcharhinus falciformis", "Manta birostris", "Mobula alfredi",
    "Thunnus obesus", "Thunnus albacares", "Thunnus alalunga", "Thunnus maccoyii", "Cheilinus undulatus", "Bolbometopon muricatum", "Makaira nigricans",
    "Istiompax indica", "Xiphias gladius",
    # seabirds
    "Phoebastria albatrus", "Spheniscus mendiculus", "Pterodroma phaeopygia", "Fregata minor",
    # reptiles
    "Amblyrhynchus cristatus", "Laticauda colubrina",
    # invertebrates
    "Tridacna gigas", "Tridacna derasa", "Nautilus pompilius",
    # reef corals
    "Acropora millepora", "Acropora hyacinthus", "Pocillopora damicornis", "Fungia fungites", "Galaxea fascicularis",
]
