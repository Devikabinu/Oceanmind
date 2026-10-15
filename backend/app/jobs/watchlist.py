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
