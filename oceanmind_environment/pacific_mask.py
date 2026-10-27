"""A simple, configurable Pacific ocean mask for the temporary provider.

There is no land/sea dataset installed in this project, so land is described by coarse hand-drawn polygons (lon east 0..360, lat) that are good to roughly
one degree: continents and the larger islands. Islands smaller than about one degree are intentionally omitted (they are sub-grid at the default
resolution). Waters that are not Pacific (Indian Ocean west/south of Indonesia and Australia) are removed with exclusion boxes. The Americas polygon is
the whole landmass east of the Pacific coast out to the domain's eastern edge, so the Caribbean, Gulf of Mexico and Atlantic cells inside the domain are
masked as well.

This is a development stand-in, not a geographic database. A real provider supplies its own mask.
"""
from __future__ import annotations

import numpy as np
import shapely
from shapely.geometry import Polygon, box

# --- land (lon east 0..360, lat) -----------------------------------------------------------------------------------------------
_EURASIA = [  # east/south-east Asia mainland, Korea, Kamchatka, Malay peninsula; western edge at lon 100 (domain edge)
    (100, 66.5), (190, 66.5), (188, 65.2), (180, 64.6), (178, 62), (171, 60.2), (164, 59.6), (163, 56), (160.5, 53), (156.7, 51),
    (156, 53.5), (156.5, 58), (160, 61), (154, 59.8), (143.5, 59.4), (138, 55), (141.3, 52.4), (140.5, 48), (135.5, 43.3), (132, 43),
    (130.7, 42.3), (129.2, 40.7), (128.5, 38.5), (129.5, 36), (129.4, 35.2), (127.5, 34.5), (126.3, 34.6), (126.5, 36.6), (126.7, 37.8),
    (125, 39.2), (124, 39.9), (121.5, 40.8), (119.5, 39.2), (118, 38.8), (119, 37.2), (122.5, 37.4), (120.8, 36.2), (119.2, 35),
    (121, 32), (122, 30.7), (121.5, 28), (119.6, 25.5), (117.5, 23.5), (114.5, 22.2), (111, 21.4), (110.3, 20.4), (109.8, 21.5),
    (108, 21.6), (106.7, 19.8), (108.2, 16), (109.3, 12.5), (108.5, 11), (106.7, 10.2), (105.2, 8.7), (104.7, 10.2), (103.5, 10.5),
    (102.5, 11.9), (101, 12.6), (100, 13.2),
]
_MALAY = [(100, 9), (100.5, 6.8), (102, 6), (103.5, 4.4), (104.2, 2.4), (104.3, 1.3), (103.4, 1.3), (102, 2.2), (100.8, 4), (100, 5.8)]
_AMERICAS = [  # everything east of the Pacific coast, to the domain's eastern edge (lon 290 = 70W)
    (192, 66.5), (193, 65.8), (196, 64.7), (199.5, 63.2), (198, 60.5), (201, 58.8), (196, 56.2), (201.5, 55.2), (205, 57), (207.5, 59),
    (212, 60), (218, 59.7), (222, 57.8), (226, 56.3), (228.5, 53.8), (231.4, 52), (233.2, 49.4), (235.3, 48.3), (235.9, 45.8), (235.5, 42.5),
    (235.6, 40.4), (237.3, 38), (238.7, 36.8), (239.5, 34.5), (241, 34), (242.9, 32.5), (245.2, 31.8),
    # Gulf of California east shore and the Mexican/Central American Pacific coast
    (246.2, 31), (248.3, 29.4), (249.3, 27.3), (251.2, 25.4), (253, 24), (254.6, 22.5), (254.8, 20.5), (256, 19), (258, 17.8), (261, 16.7),
    (264, 15.7), (266, 16.2), (268, 14.6), (270, 13.6), (272, 13.2), (274, 11.5), (275.6, 9.8), (277, 8.4), (279.6, 7.4), (280.2, 8.5),
    (279.7, 9), (281.5, 8.2), (282.5, 7), (282.8, 5.5), (283, 4), (283.7, 2.2), (282.4, 1.2), (280.6, 0.4), (279.1, -1.2), (279.8, -2.4),
    (278.2, -3), (278.8, -4.6), (280.3, -5.8), (281, -7.5), (282.2, -9.8), (283.4, -12), (284.5, -14.2), (286.2, -15.8), (288, -17.2),
    (289.4, -18.4), (289.8, -20), (289.6, -24), (289.3, -30), (288.4, -33), (287.9, -37), (286.5, -40), (286, -43), (285.2, -47), (284.7, -52),
    (285.5, -54), (288, -55.5), (290, -56), (290, 66.5),
]
_BAJA = [(242.9, 32.5), (244, 30), (245, 28), (247, 26.2), (249, 23.2), (250.2, 22.9), (250.8, 24.2), (249.5, 26.5), (247.5, 29), (245.5, 31.3)]
_JAPAN_HONSHU = [(130.9, 33.9), (132.1, 35.4), (136, 36.2), (137.3, 37.4), (139.6, 38.6), (140, 40.7), (141.6, 41.4), (142, 39.5), (141, 38), (140.9, 36),
                 (140, 35), (138.8, 34.6), (136.8, 34.3), (135.2, 33.5), (133.5, 33.3), (131.5, 33.2), (131.2, 31.4), (130.3, 31.2), (129.8, 32.8)]
_HOKKAIDO = [(140, 42), (140.4, 43.5), (141.5, 45.4), (145.6, 44.1), (143.4, 42.1), (141.5, 42.4)]
_SAKHALIN = [(142, 46), (142, 49), (142.4, 52.5), (143.3, 54), (143.3, 50), (143.5, 46.8)]
_TAIWAN = [(120.1, 23), (120.2, 24.8), (121.7, 25.2), (122, 24), (121.2, 22), (120.7, 21.9)]
_HAINAN = [(108.7, 19.3), (110.5, 20.1), (111, 19.6), (109.7, 18.2)]
_LUZON = [(120, 14), (119.8, 16.3), (120.4, 18.5), (122.3, 18.5), (122.4, 16.2), (121.7, 14.3), (124, 13), (123, 12.8), (121, 13.6)]
_VISAYAS = [(122, 10.2), (122.2, 12), (125, 12.4), (125.5, 10), (123.8, 9.4)]
_MINDANAO = [(122, 7), (122.3, 8.5), (125.6, 9.5), (126.6, 7.6), (126, 6), (124, 6.4)]
_PALAWAN = [(117.2, 8.5), (119.4, 11.4), (119.9, 11), (117.9, 8.2)]
_BORNEO = [(109, 1), (109.8, 2), (111.5, 1.7), (113, 3.2), (115, 5), (116.8, 7), (119.2, 5.2), (117.6, 3.5), (118, 1), (116.5, -1.5), (116, -3.8),
           (114.5, -3.6), (111, -3), (110, -2.8)]
_SULAWESI = [(119, -5.2), (118.9, -1.5), (120, 0.8), (125, 1.6), (125, 0.4), (122, 0.5), (121.3, -1.5), (123, -1), (123.3, -4), (121.5, -4.8), (120.4, -5.6)]
_SUMATRA_E = [(100, 3.5), (101, 2.8), (103, 1), (104.5, -1.3), (106, -3), (106, -5.9), (105, -5.8), (103, -4), (101, -2.5), (100, -0.7)]
_JAVA = [(105.2, -6.8), (106, -5.9), (108, -6.3), (111, -6.4), (114.5, -7.7), (114.4, -8.7), (111, -8.2), (108, -7.8), (106, -7.4)]
_LESSER_SUNDA = [(115, -8.1), (120, -8.2), (125, -8.2), (127, -8.5), (125, -10.2), (120, -9.3), (115, -9)]
_NEW_GUINEA = [(131, -0.8), (134, -0.7), (138, -1.6), (141, -2.6), (145, -4.5), (147.5, -6), (150, -10.5), (147, -10.2), (144, -7.8), (141, -9.1),
               (138.5, -8.3), (137, -5.7), (133, -4), (132, -2.5)]
_NEW_BRITAIN = [(148, -5.5), (152, -4.2), (152, -6), (150, -6.5)]
_AUSTRALIA = [(113.5, -22), (114, -26), (115, -34), (118, -35), (124, -33.8), (131, -31.5), (135, -34.5), (138, -35.2), (140, -38), (144, -38.5), (147, -39),
              (150, -37.3), (153, -31), (153.5, -25), (150, -22), (146, -19), (145.5, -15), (143.5, -11), (142, -11), (141.6, -14), (140, -17.5),
              (136.8, -15), (136.8, -12.2), (131, -11.3), (129.5, -14.5), (126, -14), (123, -17), (121.5, -19.5), (118, -20.5)]
_TASMANIA = [(144.7, -41), (148.3, -40.8), (148, -43), (146, -43.6)]
_NZ_NORTH = [(172.7, -34.4), (175.5, -37), (178.5, -37.7), (177, -39.5), (175.5, -41.5), (174.8, -41.2), (173.8, -39.2)]
_NZ_SOUTH = [(172.6, -40.6), (174, -41.7), (174, -43), (173, -43.5), (171.5, -44.5), (169, -46.6), (166.5, -46), (168, -44), (171, -42), (172.2, -40.7)]

LAND_POLYGONS: dict[str, list[tuple[float, float]]] = {
    "eurasia_east": _EURASIA, "malay_peninsula": _MALAY, "americas": _AMERICAS, "baja_california": _BAJA, "honshu_kyushu": _JAPAN_HONSHU,
    "hokkaido": _HOKKAIDO, "sakhalin": _SAKHALIN, "taiwan": _TAIWAN, "hainan": _HAINAN, "luzon": _LUZON, "visayas": _VISAYAS, "mindanao": _MINDANAO,
    "palawan": _PALAWAN, "borneo": _BORNEO, "sulawesi": _SULAWESI, "sumatra_east": _SUMATRA_E, "java": _JAVA, "lesser_sunda": _LESSER_SUNDA,
    "new_guinea": _NEW_GUINEA, "new_britain": _NEW_BRITAIN, "australia": _AUSTRALIA, "tasmania": _TASMANIA, "new_zealand_north": _NZ_NORTH,
    "new_zealand_south": _NZ_SOUTH,
}

# (lon_min, lat_min, lon_max, lat_max): ocean that is not Pacific and must not receive Pacific SST
NON_PACIFIC_BOXES: dict[str, tuple[float, float, float, float]] = {
    "indian_ocean_south_of_australia": (100, -60, 146.5, -39),
    "indian_ocean_west_of_australia": (100, -39, 114.5, -8),
    "great_australian_bight": (114.5, -39, 146.5, -31),
    "north_west_shelf_and_timor_sea": (100, -22.5, 131, -8),
    "strait_of_malacca": (100, 0.5, 101.8, 8),
}


def land_geometries():
    return {name: Polygon(pts) for name, pts in LAND_POLYGONS.items()}


def build_ocean_mask(lat: np.ndarray, lon: np.ndarray, source: str = "builtin_polygons") -> np.ndarray:
    """Boolean (H, W) array, True where the cell centre is Pacific ocean. lon is east longitude 0..360 (continuous across the antimeridian)."""
    if source != "builtin_polygons":
        raise ValueError(f"unknown mask source {source!r}; only 'builtin_polygons' is implemented for the temporary provider")
    LON, LAT = np.meshgrid(np.asarray(lon, dtype="float64"), np.asarray(lat, dtype="float64"))
    ocean = np.ones(LAT.shape, dtype=bool)
    for poly in land_geometries().values():
        ocean &= ~shapely.contains_xy(poly, LON, LAT)
    for (x0, y0, x1, y1) in NON_PACIFIC_BOXES.values():
        ocean &= ~shapely.intersects_xy(box(x0, y0, x1, y1), LON, LAT)  # inclusive: cell centres can sit exactly on a box edge
    return ocean
