"""
The J&K calendar, shared by the data generator and the live ride app so both describe
a given date identically. Dates are 2024 day-of-year values and are approximate: the
yatras move each year, and these are demand signals, not an official schedule.
"""
import numpy as np

FESTIVALS = {
    1:   "New Year's Day",
    26:  "Republic Day",
    70:  "Maha Shivaratri",
    102: "Eid-ul-Fitr",
    108: "Ram Navami",
    169: "Eid-ul-Adha",
    228: "Independence Day",
    286: "Dussehra",
    306: "Diwali",
    360: "Christmas",
}

# region -> [(first day, last day, intensity, name)]
PILGRIMAGES = {
    "JMU": [(100, 108, 1.0, "Navratri at Vaishno Devi"), (277, 285, 1.0, "Navratri at Vaishno Devi")],
    "KSH": [(181, 232, 1.0, "Amarnath Yatra")],
    "HIL": [(207, 249, 0.6, "Machail Mata Yatra")],
}

# region -> index by month (January first)
TOURISM = {
    "JMU": [.2, .2, .2, .3, .3, .3, .2, .2, .2, .3, .2, .2],
    "KSH": [.6, .6, .3, 1., 1., 1., .6, .6, .4, .3, .2, .6],
    "HIL": [.2, .2, .2, .3, .7, .7, .4, .3, .3, .3, .2, .2],
}


# Live pricing can only trust holidays on fixed dates. FESTIVALS above are 2024's dates for the
# training data, and most of them move each year.
FIXED_HOLIDAYS = {(1, 1), (1, 26), (8, 15), (12, 25)}


def is_holiday(day_of_year) -> np.ndarray:
    return np.isin(day_of_year, list(FESTIVALS)).astype(int)


def pilgrim_index(region: str, day_of_year) -> np.ndarray:
    doy = np.asarray(day_of_year)
    index = np.zeros(doy.shape)
    for first, last, intensity, _ in PILGRIMAGES[region]:
        index = np.where((doy >= first) & (doy <= last), intensity, index)
    return index


def tourist_index(region: str, month) -> np.ndarray:
    return np.asarray(TOURISM[region])[np.asarray(month) - 1]


def active_pilgrimage(region: str, day_of_year: int):
    for first, last, _, name in PILGRIMAGES[region]:
        if first <= day_of_year <= last:
            return name
    return None
