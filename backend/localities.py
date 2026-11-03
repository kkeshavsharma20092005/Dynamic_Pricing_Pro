"""
Neighbourhoods of Jammu and Srinagar, so riders can name the area they actually live in.

Coordinates come from OpenStreetMap (ODbL) and mark the area roughly, not a house. OSM has
gaps in these cities, so this list answers first, and it also carries Hindi and Urdu names
that a Latin-script map search would miss. "Bharat Nagar" is not on OSM, so it is pinned at
Talab Tillo, the area a local rider placed it in.
"""
import chatbot
from chatbot import normalise

LOCALITIES = [
    # name, city, lat, lon, aliases
    ("Bharat Nagar, Talab Tillo", "Jammu", 32.7380, 74.8298, ["bharat nagar talab tillo", "bharat nagar", "भारत नगर तालाब तिल्लो", "भारत नगर", "بھارت نگر تالاب تلو", "بھارت نگر"]),
    ("Talab Tillo", "Jammu", 32.7380, 74.8298, ["talab tillo", "talab tilo", "तालाब तिल्लो", "तालाब तिलो", "تالاب تلو"]),
    ("Roop Nagar", "Jammu", 32.7603, 74.8242, ["roop nagar", "rup nagar", "रूप नगर", "روپ نگر"]),
    ("Trikuta Nagar", "Jammu", 32.6912, 74.8771, ["trikuta nagar", "त्रिकुटा नगर", "تریکوٹا نگر"]),
    ("Janipur", "Jammu", 32.7575, 74.8520, ["janipur", "जानीपुर", "جانی پور"]),
    ("Channi Himmat", "Jammu", 32.6865, 74.8864, ["channi himmat", "चन्नी हिम्मत", "چنی ہمت"]),
    ("Sainik Colony", "Jammu", 32.6788, 74.9033, ["sainik colony", "सैनिक कॉलोनी", "سینک کالونی"]),
    ("Shastri Nagar", "Jammu", 32.6907, 74.8524, ["shastri nagar", "शास्त्री नगर", "شاستری نگر"]),
    ("Bakshi Nagar", "Jammu", 32.7365, 74.8584, ["bakshi nagar", "बख्शी नगर", "بخشی نگر"]),
    ("Rehari", "Jammu", 32.7460, 74.8476, ["rehari", "रेहाड़ी", "ریہاڑی"]),
    ("Residency Road", "Jammu", 32.7294, 74.8708, ["residency road", "रेजीडेंसी रोड", "ریزیڈنسی روڈ"]),
    ("Nanak Nagar", "Jammu", 32.6979, 74.8661, ["nanak nagar", "नानक नगर", "نانک نگر"]),
    ("Sanjay Nagar", "Jammu", 32.6849, 74.8541, ["sanjay nagar", "संजय नगर", "سنجے نگر"]),
    ("Greater Kailash", "Jammu", 32.6742, 74.8903, ["greater kailash", "ग्रेटर कैलाश", "گریٹر کیلاش"]),
    ("Paloura", "Jammu", 32.7635, 74.8371, ["paloura", "पलौड़ा", "پلوڑہ"]),
    ("Muthi", "Jammu", 32.7521, 74.8154, ["muthi", "मुट्ठी", "مٹھی"]),
    ("Satwari", "Jammu", 32.6923, 74.8486, ["satwari", "सतवारी", "ستواری"]),
    ("Digiana", "Jammu", 32.6863, 74.8565, ["digiana", "दिगियाना", "دگیانہ"]),
    ("Narwal", "Jammu", 32.6766, 74.8844, ["narwal", "नरवाल", "نروال"]),
    ("Kunjwani", "Jammu", 32.6673, 74.8752, ["kunjwani", "कुंजवानी", "کنجوانی"]),
    ("Bari Brahmana", "Jammu", 32.6383, 74.9152, ["bari brahmana", "बड़ी ब्राह्मणा", "باڑی برہمنا"]),
    ("Prem Nagar", "Jammu", 32.7271, 74.8655, ["prem nagar", "प्रेम नगर", "پریم نگر"]),
    ("Ambphalla", "Jammu", 32.7447, 74.8647, ["ambphalla", "अंबफला", "امبھ پھلہ"]),
    ("Pacca Danga", "Jammu", 32.7405, 74.8688, ["pacca danga", "पक्का डंगा", "پکا ڈنگہ"]),
    ("Canal Road", "Jammu", 32.7273, 74.8523, ["canal road", "कैनाल रोड", "کینال روڈ"]),
    ("General Bus Stand", "Jammu", 32.7296, 74.8594, ["bus stand", "general bus stand", "jammu bus stand", "बस स्टैंड", "بس اسٹینڈ"]),
    ("GMC Jammu", "Jammu", 32.7359, 74.8538, ["gmc", "gmc jammu", "medical college", "जीएमसी", "میڈیکل کالج"]),
    ("University of Jammu", "Jammu", 32.7183, 74.8694, ["university", "jammu university", "university of jammu", "जम्मू यूनिवर्सिटी", "جموں یونیورسٹی"]),
    ("Dogra Hall", "Jammu", 32.7376, 74.8632, ["dogra hall", "डोगरा हॉल", "ڈوگرہ ہال"]),
    ("Jewel Chowk", "Jammu", 32.7276, 74.8506, ["jewel chowk", "ज्वेल चौक", "جیول چوک"]),
    ("Parade Ground", "Jammu", 32.7363, 74.8653, ["parade ground", "parade", "परेड ग्राउंड", "پریڈ گراؤنڈ"]),
    ("Sidhra", "Jammu", 32.7606, 74.8991, ["sidhra", "सिद्रा", "سدھرا"]),
    ("Rajbagh", "Srinagar", 34.0660, 74.8279, ["rajbagh", "राजबाग", "راج باغ"]),
    ("Jawahar Nagar", "Srinagar", 34.0607, 74.8117, ["jawahar nagar", "जवाहर नगर", "جواہر نگر"]),
    ("Karan Nagar", "Srinagar", 34.0840, 74.7968, ["karan nagar", "करण नगर", "کرن نگر"]),
    ("Nowhatta", "Srinagar", 34.0983, 74.8122, ["nowhatta", "नौहट्टा", "نوہٹہ"]),
    ("Bemina", "Srinagar", 34.0764, 74.7682, ["bemina", "बेमिना", "بیمنہ"]),
    ("Hyderpora", "Srinagar", 34.0396, 74.7934, ["hyderpora", "हैदरपोरा", "حیدرپورہ"]),
    ("Soura", "Srinagar", 34.1378, 74.8021, ["soura", "सौरा", "صورہ"]),
    ("Batamaloo", "Srinagar", 34.0692, 74.7917, ["batamaloo", "बटमालू", "بٹہ مالو"]),
    ("Lal Bazar", "Srinagar", 34.1270, 74.8188, ["lal bazar", "लाल बाज़ार", "لال بازار"]),
    ("Rawalpora", "Srinagar", 34.0196, 74.7994, ["rawalpora", "रावलपोरा", "راولپورہ"]),
    ("Sanat Nagar", "Srinagar", 34.0343, 74.8004, ["sanat nagar", "सनत नगर", "صنعت نگر"]),
    ("Nishat", "Srinagar", 34.1286, 74.8801, ["nishat", "निशात", "نشاط"]),
    ("Khanyar", "Srinagar", 34.0933, 74.8145, ["khanyar", "खानयार", "خانیار"]),
    ("Habba Kadal", "Srinagar", 34.0821, 74.8079, ["habba kadal", "हब्बा कदल", "حبہ کدل"]),
    ("Natipora", "Srinagar", 34.0453, 74.8164, ["natipora", "नाटीपोरा", "ناتی پورہ"]),
]

# So replies can name these areas in the rider's own script.
for _name, _city, _, _, _aliases in LOCALITIES:
    chatbot.ALIASES[f"{_name}, {_city}"] = _aliases

CITY_WORDS = {t for word in ("jammu", "srinagar", "जम्मू", "श्रीनगर", "جموں", "سرینگر") for t in normalise(word)}
_INDEX = sorted(
    ((tuple(normalise(alias)), entry) for entry in LOCALITIES for alias in entry[4]),
    key=lambda item: -len(item[0]))


def _contains(tokens: list, sequence: tuple) -> bool:
    size = len(sequence)
    return any(tuple(tokens[i:i + size]) == sequence for i in range(len(tokens) - size + 1))


def lookup(text: str) -> dict | None:
    """
    The neighbourhood named in this text. When the rider said more than the area, such as
    a lane or house, their own words stay as the label, so the driver sees the full address.
    """
    tokens = normalise(text)
    meaningful = [t for t in tokens if t not in CITY_WORDS]
    for sequence, (name, city, lat, lon, _) in _INDEX:
        if _contains(tokens, sequence):
            exact = len(meaningful) == len(sequence)
            return {"lat": lat, "lon": lon, "name": f"{name}, {city}" if exact else text.strip().title(),
                    "approx": not exact, "area": name}
    return None
