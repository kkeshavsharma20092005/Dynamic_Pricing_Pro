"""
Understands ride requests in English, Hindi, Urdu, Roman Hindi/Urdu and everyday Dogri
(मिगी जम्मू थमां कटरा जाना ऐ, migi ithun airport jana ae). Dogri is answered in Hindi, which
Dogri speakers read easily, because replies written in Dogri would need checking by native
speakers. It also answers questions about J&K's best-known places and today's weather
(see jkinfo.py).

This is rule-based on purpose: it needs no API key, costs nothing per message, sends
nothing to an outside service, and can be tested exactly. The price is that it understands
ride-booking language, not open conversation. Anything else gets a clear help message.
"""
import re
import unicodedata
from dataclasses import dataclass, field
from difflib import get_close_matches

from places import BY_NAME

TOKEN = re.compile(r"[a-z0-9ऀ-ॿ؀-ۿݐ-ݿ]+")
URDU_DIACRITICS = re.compile(r"[ً-ْٰ]")

# Canonical place -> what people call it. Latin spellings of the name itself are added below.
ALIASES = {
    "Jammu City": ["jammu", "jamu", "jammu city", "जम्मू", "جموں"],
    "Jammu Railway Station": ["jammu station", "jammu railway station", "railway station", "जम्मू स्टेशन", "जम्मू रेलवे स्टेशन", "جموں اسٹیشن"],
    "Jammu Airport": ["jammu airport", "जम्मू एयरपोर्ट", "जम्मू हवाई अड्डा", "جموں ایئرپورٹ"],
    "Raghunath Bazaar": ["raghunath bazar", "रघुनाथ बाज़ार", "رگھوناتھ بازار"],
    "Raghunath Temple": ["raghunath mandir", "raghunath temple", "रघुनाथ मंदिर", "رگھوناتھ مندر"],
    "Gandhi Nagar, Jammu": ["gandhi nagar", "gandhinagar", "गांधी नगर", "गांधीनगर", "गाँधी नगर", "گاندھی نگر"],
    "Katra": ["katra", "katara", "कटरा", "کٹرہ", "کٹڑا", "vaishno devi", "mata vaishno devi", "वैष्णो देवी", "माता वैष्णो देवी", "ویشنو دیوی"],
    "Bahu Fort": ["bahu fort", "bahu kila", "बाहु किला", "बाहु फोर्ट", "باہو قلعہ"],
    "Samba": ["samba", "सांबा", "سانبہ"], "Kathua": ["kathua", "कठुआ", "کٹھوعہ"],
    "Akhnoor": ["akhnoor", "अखनूर", "اکھنور"], "Udhampur": ["udhampur", "उधमपुर", "ادھم پور"],
    "Reasi": ["reasi", "रियासी", "ریاسی"],
    "Shiv Khori": ["shiv khori", "shivkhori", "शिव खोड़ी", "شیو کھوڑی"],
    "Baba Dhansar": ["baba dhansar", "dhansar", "बाबा धनसर", "بابا دھنسر"],
    "Krimchi Temples": ["krimchi", "krimchi temple", "क्रिमची", "کرمچی"],
    "Mansar Lake": ["mansar", "mansar lake", "मानसर", "مانسر"],
    "Rajouri": ["rajouri", "राजौरी", "راجوری"], "Poonch": ["poonch", "पुंछ", "پونچھ"],
    "Ramban": ["ramban", "रामबन", "رام بن"], "Banihal": ["banihal", "बनिहाल", "بانہال"],
    "Patnitop": ["patnitop", "पटनीटॉप", "پتنی ٹاپ"], "Doda": ["doda", "डोडा", "ڈوڈہ"],
    "Bhaderwah": ["bhaderwah", "bhadarwah", "भद्रवाह", "بھدرواہ"], "Kishtwar": ["kishtwar", "किश्तवाड़", "کشتواڑ"],
    "Srinagar, Lal Chowk": ["srinagar", "lal chowk", "श्रीनगर", "लाल चौक", "سرینگر", "لال چوک"],
    "Srinagar Airport": ["srinagar airport", "श्रीनगर एयरपोर्ट", "سرینگر ایئرپورٹ"],
    "Dal Gate": ["dal gate", "dal lake", "डल झील", "डल गेट", "ڈل جھیل", "ڈل گیٹ"],
    "Hazratbal": ["hazratbal", "हज़रतबल", "حضرت بل"], "Budgam": ["budgam", "बडगाम", "بڈگام"],
    "Ganderbal": ["ganderbal", "गांदरबल", "گاندربل"], "Sonamarg": ["sonamarg", "सोनमर्ग", "سونمرگ"],
    "Gulmarg": ["gulmarg", "गुलमर्ग", "گلمرگ"], "Baramulla": ["baramulla", "बारामूला", "بارہمولہ"],
    "Sopore": ["sopore", "सोपोर", "سوپور"], "Uri": ["uri", "उरी", "اوڑی"],
    "Bandipora": ["bandipora", "बांदीपोरा", "بانڈی پورہ"], "Kupwara": ["kupwara", "कुपवाड़ा", "کپواڑہ"],
    "Pulwama": ["pulwama", "पुलवामा", "پلوامہ"], "Awantipora": ["awantipora", "अवंतीपोरा", "اونتی پورہ"],
    "Shopian": ["shopian", "शोपियां", "شوپیاں"], "Kulgam": ["kulgam", "कुलगाम", "کولگام"],
    "Anantnag": ["anantnag", "अनंतनाग", "اننت ناگ"], "Pahalgam": ["pahalgam", "पहलगाम", "پہلگام"],
    "Betaab Valley": ["betaab valley", "betab valley", "बेताब घाटी", "بیتاب وادی"],
    "Nishat Bagh": ["nishat bagh", "nishat garden", "निशात बाग", "نشاط باغ"],
    "Qazigund": ["qazigund", "काजीगुंड", "قاضی گنڈ"],
}

VEHICLES = {
    "erickshaw": ["e rickshaw", "erickshaw", "ई रिक्शा", "ای رکشہ"],
    "bike": ["bike", "scooter", "motorcycle", "बाइक", "بائیک"],
    "auto": ["auto", "rickshaw", "ऑटो", "ऑटो रिक्शा", "रिक्शा", "آٹو", "رکشہ"],
    "shared": ["shared", "share", "sumo", "शेयर", "शेयर्ड", "सूमो", "شیئرڈ", "سومو"],
    "cab": ["cab", "taxi", "car", "gaadi", "gadi", "gaddi", "कैब", "टैक्सी", "कार", "गाड़ी", "गड्डी", "ٹیکسی", "کیب", "گاڑی"],
}
VEHICLE_NAMES = {
    "en": {"bike": "Bike", "erickshaw": "E-rickshaw", "auto": "Auto", "cab": "Cab", "shared": "Shared cab"},
    "hinglish": {"bike": "Bike", "erickshaw": "E-rickshaw", "auto": "Auto", "cab": "Cab", "shared": "Shared cab"},
    "hi": {"bike": "बाइक", "erickshaw": "ई-रिक्शा", "auto": "ऑटो", "cab": "कैब", "shared": "शेयर्ड कैब"},
    "ur": {"bike": "بائیک", "erickshaw": "ای رکشہ", "auto": "آٹو", "cab": "ٹیکسی", "shared": "شیئرڈ ٹیکسی"},
}

# "main bharat nagar mein hoon" names where the rider is, so "hoon" works like "se".
# Dogri says "X थमां" (thaman) for "from X".
FROM_AFTER = {"se", "sey", "से", "سے", "hoon", "hun", "hu", "हूं", "हूँ", "ہوں", "थमां", "थमा", "thaman", "thamaan", "thama"}
FROM_BEFORE = {"from", "pickup", "am", "पिकअप", "پک"}
TO_BEFORE = {"to", "till", "towards", "drop", "dropoff", "ड्रॉप", "ڈراپ"}
# "katra ke liye gaadi", "vaishno devi kaise jaun" name where the rider is going.
TO_AFTER = {"tak", "ko", "jana", "jaana", "chalo", "तक", "को", "जाना", "चलो", "تک", "کو", "جانا", "چلو",
            "jaun", "jau", "jaaun", "जाऊं", "जाऊँ", "liye", "लिए", "لیے", "pahunchna", "पहुंचना", "पहुँचना"}
DIRECTION_WORDS = FROM_AFTER | FROM_BEFORE | TO_BEFORE | TO_AFTER

CURRENT = "__current__"
HOME = "__home__"
HOME_WORDS = {"ghar", "ghr", "gher", "home", "घर", "گھر"}
POSSESSIVE = {"mera", "meri", "my", "apna", "मेरा", "मेरी", "अपना", "میرا", "میری", "اپنا"}

CONFIRM = {"yes", "yeah", "yep", "ok", "okay", "confirm", "book", "haan", "han", "ha", "ji", "theek", "thik",
           "हां", "हाँ", "जी", "ठीक", "ओके", "बुक", "ہاں", "جی", "ٹھیک", "بک", "اوکے"}
DENY = {"no", "nope", "nahi", "nhi", "nahin", "nei", "cancel", "radd", "stop",
        "नहीं", "नही", "नेईं", "नईं", "रद्द", "कैंसल", "نہیں", "کینسل", "منسوخ"}
CANCEL = {"cancel", "radd", "रद्द", "कैंसल", "کینسل", "منسوخ"}
CHEAPEST = {"optimal", "cheapest", "cheap", "best", "sasta", "sasti", "saste", "budget", "सस्ता", "सस्ती", "सबसे", "ऑप्टिमल", "سستا", "سستی", "بہترین", "sabse"}
STATUS = {"status", "where", "kahan", "kaha", "kha", "kahaan", "kidhar", "driver", "कहां", "कहाँ", "ड्राइवर", "کہاں", "ڈرائیور"}
TEMPLES = {"temple", "temples", "mandir", "mandirs", "shrine", "मंदिर", "मंदिरों", "مندر", "مندروں"}
MOSQUES = {"masjid", "mosque", "mosques", "masjiden", "मस्जिद", "مسجد", "مسجدیں"}
GURUDWARAS = {"gurudwara", "gurdwara", "gurudwaras", "gurudware", "गुरुद्वारा", "گردوارہ"}
# "paas ke mandir", "mandir near me"; Dogri says कोल / नेड़े.
NEAR = {"paas", "pass", "nazdeek", "najdeek", "nazdik", "najdik", "nearby", "near", "nearest", "kareeb", "karib",
        "kol", "nede", "पास", "नजदीक", "करीब", "कोल", "नेड़े", "नेडे", "قریب", "پاس", "نزدیک"}
CALL = {"call", "phone", "ring", "कॉल", "फोन", "फ़ोन", "کال", "فون"}
HISTORY = {"history", "trips", "past", "pichli", "purani", "पिछली", "इतिहास", "यात्राएं", "تاریخ", "سفروں", "پچھلی"}
GREET = {"hi", "hello", "hey", "namaste", "namaskar", "salam", "assalam", "नमस्ते", "नमस्कार", "سلام", "اسلام"}
# Questions about a place ("katra mein kya dekhna hai") or the weather, rather than a trip.
INFO = {"dekhna", "dekhne", "dekhu", "ghoomna", "ghoomne", "ghumne", "ghumna", "ghoom", "sightseeing", "visit",
        "famous", "mashhoor", "mashoor", "baare", "bare", "jankari", "jaankari", "about", "information", "info",
        "yatra", "darshan", "kab", "when", "attractions", "places",
        "देखना", "देखने", "घूमना", "घूमने", "जगहें", "प्रसिद्ध", "मशहूर", "बारे", "जानकारी", "यात्रा", "दर्शन", "कब",
        "दिक्खना", "दिक्खने", "dikkhna"}
WEATHER = {"mausam", "weather", "temperature", "barish", "baarish", "barf", "snow", "snowfall", "thand", "garmi",
           "मौसम", "बारिश", "बर्फ", "ठंड", "गर्मी", "तापमान", "موسم", "بارش", "برف"}
FARE_WORDS = {"kiraya", "fare", "price", "किराया", "کرایہ"}
ROMAN_HINDI = {"mujhe", "muje", "mereko", "jana", "jaana", "hai", "se", "tak", "chahiye", "kitna", "kahan", "kaha",
               "karo", "kardo", "kar", "nahi", "haan", "mera", "meri", "mein", "aur", "kya", "kaise", "bhai", "gaadi",
               "gadi", "namaste", "salam", "madad", "chalo", "lena", "sabse", "sasta", "sasti", "batao", "bataiye", "dikhao", "kiraya", "kitne",
               "kha", "kahaan", "kidhar", "ghar", "ghr", "yahan", "yaha", "hoon", "hun", "abhi", "kitni", "door", "dijiye",
               "jaun", "liye", "mausam", "dekhna", "ghoomne", "jagah", "yatra", "kab", "ke", "ki", "ka", "paas", "pass",
               # Roman Dogri
               "migi", "miki", "ae", "thaman", "thamaan", "ithun", "itthun", "ithon", "chahidi", "chahida", "gaddi", "kinna"}


FILLER_WORDS = """optimal cheapest cheap best sasta sasti saste sabse budget price fare kiraya batao bataiye bata tell show
    kitna kitne dikhao kaunsa konsa which what सस्ता सस्ती सबसे किराया बताओ बताइए कितना دکھاؤ سستا سستی بہترین کرایہ بتاؤ کتنا
    i im am a an the want need please book ride go going take me get pick up by via is are in at on
    can you my mine would like let lets now today it this that
    mujhe muje mujhko mereko main mai mein me mera meri mere apne apna apni hai hain ho tha chahiye karo kardo karna kar
    ke ka ki liye par pe wala wali aur bhai ji ek
    do de dijiye dijie dena dedo kijiye kijie plz abhi jaldi zara ab kaise kese how far door dur distance kitni
    मुझे मुझको मैं में मेरा मेरी मेरे अपने अपना है हैं हो चाहिए करो करना कर दो के का की लिए पर वाला और भाई एक बुक राइड
    दीजिए दीजिये कीजिए अभी जल्दी कैसे कितनी दूर दूरी मेरेको मुझको
    मिगी मिकी migi miki ऐ ae ए दा da दी di किन्ना kinna चाहिदी चाहिदा chahidi chahida
    مجھے میں میرا میری میرے اپنے اپنا ہے ہیں ہو چاہیے کرو کرنا کر دو کے کا کی لیے پر والا اور بھائی ایک بک سواری""".split()


def normalise(text: str) -> list:
    """Lower-case tokens, with spelling variants of the same letter made equal."""
    text = unicodedata.normalize("NFC", text.lower())
    text = URDU_DIACRITICS.sub("", text).replace("ي", "ی").replace("ك", "ک").replace("ۃ", "ہ")
    text = text.replace("़", "")                    # Hindi nukta: ज़ and ज are typed interchangeably
    text = unicodedata.normalize("NFC", text.replace("ड़", "ड").replace("ढ़", "ढ"))
    return TOKEN.findall(text)


def _sequence_index(table: dict) -> list:
    """[(tokens, value)], longest first, so 'jammu airport' beats 'jammu'."""
    entries = [(tuple(normalise(alias)), value) for value, aliases in table.items() for alias in aliases]
    return sorted(set(entries), key=lambda e: -len(e[0]))


def _with_official_names() -> dict:
    missing = set(BY_NAME) - set(ALIASES)
    if missing:
        raise ValueError(f"Places with no chatbot aliases: {sorted(missing)}")
    return {name: aliases + [name] for name, aliases in ALIASES.items()}


PLACE_INDEX = _sequence_index(_with_official_names())
_EXACT_PLACES = dict(PLACE_INDEX)
VEHICLE_INDEX = _sequence_index(VEHICLES)
FILLER = ({t for word in FILLER_WORDS for t in normalise(word)} | CONFIRM | DENY | STATUS | CALL | GREET
          | {t for sequence, _ in VEHICLE_INDEX for t in sequence})
CURRENT_PHRASES = sorted((tuple(normalise(p)) for p in (
    "my current location", "current location", "my location", "my place", "here", "right here",
    "meri current location", "meri location", "mera location", "yahan", "yaha", "yahin", "isi jagah",
    "मेरी करंट लोकेशन", "करंट लोकेशन", "मेरी लोकेशन", "मौजूदा लोकेशन", "मेरी जगह", "यहां", "यहाँ", "यहीं",
    "इत्थूं", "इत्थों", "इत्थे", "इत्थें", "ithun", "itthun", "ithon", "itthon", "ithe", "itthe",   # Dogri: (from) here
    "میری کرنٹ لوکیشن", "کرنٹ لوکیشن", "میری لوکیشن", "موجودہ مقام", "یہاں", "یہیں")), key=lambda p: -len(p))
LATIN_NAMES = {tokens[0]: value for tokens, value in PLACE_INDEX
               if len(tokens) == 1 and tokens[0].isascii() and len(tokens[0]) >= 5}


@dataclass
class Parsed:
    lang: str | None = None      # None: nothing here shows a language, such as "cab" or "ok"
    pickup: str | None = None
    dropoff: str | None = None
    place: str | None = None     # one place with no direction word
    vehicle: str | None = None
    confirm: bool = False
    deny: bool = False
    cancel: bool = False
    status: bool = False
    temples: bool = False
    greet: bool = False
    call: bool = False
    history: bool = False
    cheapest: bool = False
    nearby: str | None = None    # "temple", "mosque" or "gurudwara": places of worship near...
    near: str | None = None      # ...this place, or CURRENT for the rider's own location
    info: bool = False           # a question about a place, not a trip
    weather: bool = False
    about: str | None = None     # the known place an info or weather question names
    free: str | None = None      # words that could be an address, with no direction word
    save_home: str | None = None
    tokens: list = field(default_factory=list)

    @property
    def has_place(self) -> bool:
        return bool(self.pickup or self.dropoff or self.place or self.save_home)


def detect_language(tokens: list, text: str) -> str | None:
    if re.search(r"[ऀ-ॿ]", text):
        return "hi"
    if re.search(r"[؀-ۿݐ-ݿ]", text):
        return "ur"
    if ROMAN_HINDI & set(tokens):
        return "hinglish"
    # A bare "ok" or "cab" could be any language, so it keeps the current one.
    # Place names don't either, so tapping a temple card keeps a Hindi conversation in Hindi.
    neutral = CONFIRM | DENY | {"cab", "auto", "bike", "taxi", "shared", "car", "hi", "hello", "ok", "to"}
    neutral |= {t for sequence, _ in PLACE_INDEX for t in sequence}
    return "en" if set(tokens) - neutral else None


def _find(tokens: list, index: list) -> list:
    """Non-overlapping matches as (start, end, value), earliest in the sentence first."""
    used, found = set(), []
    for sequence, value in index:
        size = len(sequence)
        for start in range(len(tokens) - size + 1):
            span = range(start, start + size)
            if tuple(tokens[start:start + size]) == sequence and not used & set(span):
                used.update(span)
                found.append((start, start + size, value))
    return sorted(found)


def _fix_typos(tokens: list) -> list:
    """Correct near-miss Latin place names, such as 'srinagr'."""
    known = {t for sequence, _ in PLACE_INDEX + VEHICLE_INDEX for t in sequence}
    fixed = []
    for token in tokens:
        if token.isascii() and len(token) >= 5 and token not in known and token not in ROMAN_HINDI:
            match = get_close_matches(token, LATIN_NAMES, n=1, cutoff=0.82)
            fixed.append(match[0] if match else token)
        else:
            fixed.append(token)
    return fixed


def parse(text: str) -> Parsed:
    tokens = _fix_typos(normalise(text))
    p = Parsed(lang=detect_language(tokens, text), tokens=tokens)
    words = set(tokens)
    p.deny = bool(words & DENY)
    p.confirm = bool(words & CONFIRM) and not p.deny
    p.cancel = bool(words & CANCEL)
    p.status = bool(words & STATUS)
    p.greet = bool(words & GREET)
    p.cheapest = bool(words & {t for w in CHEAPEST for t in normalise(w)})
    p.call = bool(words & {t for w in CALL for t in normalise(w)})
    p.history = bool(words & {t for w in HISTORY for t in normalise(w)})

    vehicles = _find(tokens, VEHICLE_INDEX)
    if vehicles:
        p.vehicle = vehicles[0][2]

    # "Mujhe paas ke mandir dekhne hain, apni current location se": the nearest ones to the rider.
    matches = _find(tokens, PLACE_INDEX)
    faith = ("temple" if words & TEMPLES else "mosque" if words & MOSQUES
             else "gurudwara" if words & GURUDWARAS else None)
    here = CURRENT in _mark_special_places(tokens)
    if faith and (here or words & NEAR):
        towns = [name for _, _, name in matches if name != "Jammu City"]
        p.nearby, p.near = faith, (CURRENT if here or not towns else towns[0])
        return p

    # "Jammu's temples" asks about temples in general, not for a ride to Jammu city.
    if words & TEMPLES and all(name == "Jammu City" for _, _, name in matches) and not words & TO_AFTER:
        p.temples = True
        return p

    # "Katra mein kya dekhna hai", "Srinagar ka mausam": a question, unless it also asks for a trip.
    asks_trip = words & DIRECTION_WORDS or words & FARE_WORDS or p.vehicle
    if (words & INFO or words & WEATHER) and not asks_trip:
        p.weather = bool(words & WEATHER)
        p.info = not p.weather
        p.about = matches[0][2] if matches else None
        return p

    tokens = _mark_special_places(tokens)
    if _read_home_address(tokens, p):
        return p
    _read_trip(tokens, p)
    return p


def _mark_special_places(tokens: list) -> list:
    """Replace "my current location" and "home" with one token each."""
    marked, i = [], 0
    while i < len(tokens):
        for phrase in CURRENT_PHRASES:
            if tuple(tokens[i:i + len(phrase)]) == phrase:
                marked.append(CURRENT)
                i += len(phrase)
                break
        else:
            marked.append(HOME if tokens[i] in HOME_WORDS else tokens[i])
            i += 1
    return marked


def _read_home_address(tokens: list, p: Parsed) -> bool:
    """"mera ghar bharat nagar mein hai" saves an address; "ghar jana hai" is a trip."""
    if HOME not in tokens:
        return False
    at = tokens.index(HOME)
    rest = tokens[at + 1:]
    if at == 0 or tokens[at - 1] not in POSSESSIVE or set(rest) & DIRECTION_WORDS:
        return False
    address = _clean(rest)
    if not address:
        return False
    p.save_home = " ".join(address)
    return True


def _clean(tokens: list) -> list:
    """Drop filler from both ends and keep the address in the middle exactly as said."""
    tokens = list(tokens)
    while tokens and tokens[0] in FILLER:
        tokens.pop(0)
    while tokens and tokens[-1] in FILLER:
        tokens.pop()
    return tokens


def _name_of(tokens: list) -> str:
    """The known place these words are exactly, or the words themselves as an address."""
    if tokens in ([CURRENT], [HOME]):
        return tokens[0]
    return _EXACT_PLACES.get(tuple(tokens), " ".join(tokens))


def _read_trip(tokens: list, p: Parsed):
    """
    Walk the sentence, splitting on direction words, so any words can be an address:
    "bharat nagar talab tillo se roop nagar jana hai" gives both ends without knowing either.
    """
    pickup, dropoff, target, buffer = None, None, None, []

    def take():
        words = _clean(buffer)
        buffer.clear()
        return words

    for token in tokens:
        if token == CURRENT and not _clean(buffer):   # "yahan se ...", Dogri "इत्थूं ..." (from here)
            buffer.clear()
            pickup, target = [CURRENT], None
        elif token in FROM_AFTER:                     # "X se"
            pickup = take() or pickup
            target = None
        elif token in FROM_BEFORE:                    # "from X"
            words = take()
            if target == "dropoff" and words:
                dropoff = words
            target = "pickup"
        elif token in TO_BEFORE:                      # "X to", then Y
            words = take()
            if target == "pickup" and words:
                pickup = words
            elif words and not pickup:
                pickup = words
            target = "dropoff"
        elif token in TO_AFTER:                       # "X tak", "X jana"
            dropoff = take() or dropoff
            target = None
        else:
            buffer.append(token)

    words = take()
    if words:
        if target == "pickup":
            pickup = words
        elif target == "dropoff" or (pickup and not dropoff):
            dropoff = words
        else:
            found = _find(words, PLACE_INDEX)
            if len(found) == 2:                       # "jammu katra": sentence order
                pickup, dropoff = [found[0][2]], [found[1][2]]
                p.pickup, p.dropoff = found[0][2], found[1][2]
                return
            if tuple(words) in _EXACT_PLACES or words in ([CURRENT], [HOME]):
                p.place = _name_of(words)
            else:
                p.free = " ".join(words)

    if pickup:
        p.pickup = _name_of(pickup)
    if dropoff:
        p.dropoff = _name_of(dropoff)
    # Only pickup can be "here" in this app.
    if p.dropoff == CURRENT and not p.pickup:
        p.pickup, p.dropoff = CURRENT, None


# ------------------------------------------------------------------ replies
BRAND = "Raahi"
REPLIES = {
    "en": {
        "help": "I'm your local guide. Tell me where you want to go, like \"Jammu to Katra by cab\", or ask me about a place, like \"what to see in Katra\", or today's weather.",
        "greet": "Hello! I'm Raahi, your local guide. Where would you like to go?",
        "ask_pickup": "Going to {dropoff}. Where should I pick you up? Say your exact spot, like a lane or landmark, tap My current location, or pick it on the map.",
        "ask_dropoff": "Pickup from {pickup}. Where are you going?",
        "ask_vehicle": "{pickup} to {dropoff}, {km} km. Which one would you like?",
        "not_offered": "{vehicle} is not available for this trip. Please pick one of these.",
        "confirm": "{vehicle} from {pickup} to {dropoff}: ₹{fare} for {km} km. Shall I book it?",
        "rec_rival": "By estimate, {rival} may be cheaper (assumed rates, not a live price). Check its app first if you like.",
        "rec_us": "By estimate, this is below Rapido and Uber (assumed rates, not live prices).",
        "booked": "Booked! ₹{fare}, {pickup} to {dropoff}. I'm finding your driver now. Watch your ride on the main screen.",
        "hint_vehicle": "Pick one of the options below, or just say it.",
        "hint_confirm": "There are two options below: tap one, or say yes or no.",
        "go_there": "🚕 Go to {place}",
        "ask_spot": "Where in {place}? Pick a spot below, or tell me a landmark.",
        "whole_area": "Just {place}",
        "already_there": "You're already near {place}! Tell me if you want to go somewhere else.",
        "nearby_found": "These {kind} are closest to you: {places}. Tap one and I'll take you there.",
        "nearby_town": "These {kind} are close to {place}: {places}. Tap one and I'll take you there.",
        "nearby_none": "I couldn't find any {kind} within 15 km of you.",
        "no_note": "I don't have notes on {place} yet, but I can book you a ride there.",
        "dropped": "Okay, I've cleared that trip. Where would you like to go instead?",
        "confirm_cancel": "Cancel your ride from {pickup} to {dropoff}?",
        "cancelled": "Your ride is cancelled.",
        "cant_cancel": "This ride can't be cancelled now because the trip has started.",
        "kept": "Okay, your ride stays booked.",
        "temples": "Here are famous temples around Jammu. Tap one to go there.",
        "closed": "That road is closed right now, so I can't book this trip. {detail}",
        "outside": "That place is outside the area we serve in Jammu & Kashmir.",
        "too_close": "Pickup and drop-off are too close together. Please choose another place.",
        "failed": "I couldn't price that trip: {detail}",
        "searching": "I'm still looking for a driver for {dropoff}.",
        "accepted": "{driver} is on the way to {pickup}.",
        "arrived": "{driver} has reached {pickup}.",
        "in_progress": "You're on the trip to {dropoff}.",
        "no_ride": "You don't have an active ride right now. Where would you like to go?",
        "calling": "Calling {driver} now.",
        "call_simulated": "{driver} is a demo driver, so this call is only simulated.",
        "call_wait": "There's no driver to call yet. I'm still looking for one.",
        "no_history": "You haven't taken any trips yet.",
        "history": "Your last trips: {trips}.",
        "where_is": "{place} is near {town}. Shall we go there? Tell me where to pick you up.",
        "which_one": "I found a few places called that. Which one do you mean?",
        "best_value": "The cheapest here is {vehicle} at ₹{fare}, from {pickup} to {dropoff}, {km} km. Shall I book it?",
        "hello": "{greeting}, {name}! I'm Raahi, your local guide for Jammu & Kashmir. Where are we headed today? You can also ask me about any place or the weather.",
        "hello_again": "{greeting}, {name}! Good to see you again. {place} again, or somewhere new today?",
        "locating": "Sure, let me find where you are.",
        "located": "Found you near {pickup}.",
        "ask_where": "Tell me your area or a nearby landmark, or I can use your current location.",
        "not_found": "Sorry, I couldn't find \"{place}\". Could you give me a nearby landmark or the main area? You can also drop a pin on the map.",
        "approx": "I've placed the pin around {area}. If it's off, you can pick the exact spot on the map.",
        "pin_prompt": "Okay, tap the spot on the map.",
        "home_saved": "Got it, {name}. I've saved {place} as your home. Just say \"take me home\" any time.",
        "ask_home": "I don't know your home yet. Tell me like this: \"my home is in Bharat Nagar, Talab Tillo\".",
        "btn_here": "📍 My current location", "btn_map": "🗺️ Pick on map", "btn_home": "🏠 Home",
    },
    "hinglish": {
        "help": "Main aapka local guide hoon. Bataiye kahan jana hai, jaise \"Jammu se Katra cab\", ya kisi jagah ke baare mein puchiye, jaise \"Katra mein kya dekhna hai\", ya aaj ka mausam.",
        "greet": "Namaste ji! Main Raahi, aapka local guide. Kahan chalna hai?",
        "ask_pickup": "{dropoff} jana hai. Aapko kahan se pick karun? Apni exact jagah boliye, jaise gali ya landmark, ya Meri current location dabaiye, ya map par jagah chuniye.",
        "ask_dropoff": "{pickup} se pickup. Kahan jana hai?",
        "ask_vehicle": "{pickup} se {dropoff}, {km} km. Kaunsi gaadi chahiye?",
        "not_offered": "Is trip ke liye {vehicle} available nahi hai. Inme se chuniye.",
        "confirm": "{vehicle}, {pickup} se {dropoff}: {km} km ke ₹{fare}. Book kar dun?",
        "rec_rival": "Estimate ke hisaab se {rival} sasta ho sakta hai (maane hue rates, live price nahi). Chahein to pehle uska app dekh lijiye.",
        "rec_us": "Estimate ke hisaab se yeh Rapido aur Uber se sasta hai (maane hue rates, live price nahi).",
        "booked": "Book ho gaya! ₹{fare}, {pickup} se {dropoff}. Ab driver dhoondh raha hoon. Main screen par apni ride dekhiye.",
        "hint_vehicle": "Neeche diye options mein se ek chuniye, ya bol kar bataiye.",
        "hint_confirm": "Neeche aapke paas do option hain, unme se ek par tap kijiye, ya haan ya nahi bol dijiye.",
        "go_there": "🚕 {place} chalein",
        "ask_spot": "{place} mein kahan jana hai? Neeche se jagah chuniye, ya koi landmark bataiye.",
        "whole_area": "Bas {place}",
        "already_there": "Aap to pehle se {place} ke paas hain! Kahin aur jana ho to bataiye.",
        "nearby_found": "Aapke paas yeh {kind} hain: {places}. Jis par tap karenge, wahan le chalunga.",
        "nearby_town": "{place} ke paas yeh {kind} hain: {places}. Jis par tap karenge, wahan le chalunga.",
        "nearby_none": "Aapke 15 km ke andar koi {kind} nahi mila.",
        "no_note": "{place} ke baare mein abhi meri jaankari kam hai, lekin wahan ki ride book kar sakta hoon.",
        "dropped": "Theek hai, yeh trip hata diya. Ab kahan jana hai?",
        "confirm_cancel": "{pickup} se {dropoff} wali ride cancel kar dun?",
        "cancelled": "Aapki ride cancel ho gayi.",
        "cant_cancel": "Trip shuru ho chuka hai, isliye ab yeh ride cancel nahi ho sakti.",
        "kept": "Theek hai, aapki ride book hi rahegi.",
        "temples": "Yeh rahe Jammu ke mashhoor mandir. Jahan jana ho, us par tap kijiye.",
        "closed": "Yeh raasta abhi band hai, isliye yeh trip book nahi ho sakta. {detail}",
        "outside": "Yeh jagah Jammu-Kashmir ke hamare service area se bahar hai.",
        "too_close": "Pickup aur drop bahut paas hain. Koi aur jagah chuniye.",
        "failed": "Is trip ka fare nahi nikal paya: {detail}",
        "searching": "{dropoff} ke liye abhi driver dhoondh raha hoon.",
        "accepted": "{driver} {pickup} aa rahe hain.",
        "arrived": "{driver} {pickup} pahunch gaye hain.",
        "in_progress": "Aap {dropoff} ke raaste par hain.",
        "no_ride": "Abhi aapki koi ride chal nahi rahi. Kahan jana hai?",
        "calling": "{driver} ko call kar raha hoon.",
        "call_simulated": "{driver} demo driver hain, isliye yeh call sirf simulated hai.",
        "call_wait": "Abhi call karne ke liye driver nahi hai. Driver dhoondh raha hoon.",
        "no_history": "Aapne abhi tak koi trip nahi ki.",
        "history": "Aapki pichli trips: {trips}.",
        "where_is": "{place} {town} ke paas hai. Wahan chalein? Bataiye aapko kahan se pick karun.",
        "which_one": "Is naam ki kuch jagahen mili hain. Aap kaunsi keh rahe hain?",
        "best_value": "Sabse sasta {vehicle} hai, ₹{fare} mein, {pickup} se {dropoff}, {km} km. Book kar dun?",
        "hello": "{greeting} {name} ji! Main Raahi hoon, aapka Jammu-Kashmir ka local guide. Bataiye aaj kahan chalna hai? Kisi jagah ya mausam ke baare mein bhi puch sakte hain.",
        "hello_again": "{greeting} {name} ji! Phir se mil kar achha laga. Phir {place} chalein, ya aaj kahin aur?",
        "locating": "Ji zaroor, abhi dekhta hoon aap kahan hain.",
        "located": "Aap {pickup} ke paas hain.",
        "ask_where": "Apna area ya paas ka koi landmark bataiye, ya main aapki current location le sakta hoon.",
        "not_found": "Maaf kijiye, \"{place}\" nahi mila. Paas ka koi landmark ya main area bata dijiye, ya map par pin laga dijiye.",
        "approx": "Maine pin {area} ke aas-paas lagaya hai. Sahi na ho to map par exact jagah chun lijiye.",
        "pin_prompt": "Theek hai, map par us jagah tap kijiye.",
        "home_saved": "Theek hai {name} ji, {place} aapka ghar save kar liya. Ab bas boliye \"ghar chalo\".",
        "ask_home": "Aapka ghar abhi mujhe pata nahi. Aise bataiye: \"mera ghar Bharat Nagar, Talab Tillo mein hai\".",
        "btn_here": "📍 Meri current location", "btn_map": "🗺️ Map par chuniye", "btn_home": "🏠 Ghar",
    },
    "hi": {
        "help": "मैं आपका लोकल गाइड हूं। बताइए कहां जाना है, जैसे \"जम्मू से कटरा कैब\", या किसी जगह के बारे में पूछिए, जैसे \"कटरा में क्या देखना है\", या आज का मौसम।",
        "greet": "नमस्ते जी! मैं राही, आपका लोकल गाइड। कहां चलना है?",
        "ask_pickup": "{dropoff} जाना है। आपको कहां से लूं? अपनी सटीक जगह बोलिए, जैसे गली या लैंडमार्क, या मेरी मौजूदा लोकेशन दबाइए, या मैप पर जगह चुनिए।",
        "ask_dropoff": "{pickup} से पिकअप। कहां जाना है?",
        "ask_vehicle": "{pickup} से {dropoff}, {km} किमी। कौन सी गाड़ी चाहिए?",
        "not_offered": "इस यात्रा के लिए {vehicle} उपलब्ध नहीं है। इनमें से चुनिए।",
        "confirm": "{vehicle}, {pickup} से {dropoff}: {km} किमी के ₹{fare}। बुक कर दूं?",
        "rec_rival": "अनुमान के हिसाब से {rival} सस्ता हो सकता है (मानी गई दरें, लाइव किराया नहीं)। चाहें तो पहले उसका ऐप देख लीजिए।",
        "rec_us": "अनुमान के हिसाब से यह Rapido और Uber से सस्ता है (मानी गई दरें, लाइव किराया नहीं)।",
        "booked": "बुक हो गया! ₹{fare}, {pickup} से {dropoff}। अब ड्राइवर खोज रहा हूं। मुख्य स्क्रीन पर अपनी राइड देखिए।",
        "hint_vehicle": "नीचे दिए विकल्पों में से एक चुनिए, या बोलकर बताइए।",
        "hint_confirm": "नीचे आपके पास दो विकल्प हैं, उनमें से एक पर टैप कीजिए, या हां या नहीं बोल दीजिए।",
        "go_there": "🚕 {place} चलें",
        "ask_spot": "{place} में कहां जाना है? नीचे से जगह चुनिए, या कोई लैंडमार्क बताइए।",
        "whole_area": "बस {place}",
        "already_there": "आप तो पहले से {place} के पास हैं! कहीं और जाना हो तो बताइए।",
        "nearby_found": "आपके पास ये {kind} हैं: {places}। जिस पर टैप करेंगे, वहां ले चलूंगा।",
        "nearby_town": "{place} के पास ये {kind} हैं: {places}। जिस पर टैप करेंगे, वहां ले चलूंगा।",
        "nearby_none": "आपके 15 किमी के अंदर कोई {kind} नहीं मिला।",
        "no_note": "{place} के बारे में अभी मेरी जानकारी कम है, लेकिन वहां की राइड बुक कर सकता हूं।",
        "dropped": "ठीक है, यह यात्रा हटा दी। अब कहां जाना है?",
        "confirm_cancel": "{pickup} से {dropoff} वाली राइड रद्द कर दूं?",
        "cancelled": "आपकी राइड रद्द हो गई।",
        "cant_cancel": "यात्रा शुरू हो चुकी है, इसलिए अब यह राइड रद्द नहीं हो सकती।",
        "kept": "ठीक है, आपकी राइड बुक रहेगी।",
        "temples": "ये रहे जम्मू के प्रसिद्ध मंदिर। जहां जाना हो, उस पर टैप कीजिए।",
        "closed": "यह रास्ता अभी बंद है, इसलिए यह यात्रा बुक नहीं हो सकती। {detail}",
        "outside": "यह जगह जम्मू-कश्मीर के हमारे सेवा क्षेत्र से बाहर है।",
        "too_close": "पिकअप और ड्रॉप बहुत पास हैं। कोई और जगह चुनिए।",
        "failed": "इस यात्रा का किराया नहीं निकल पाया: {detail}",
        "searching": "{dropoff} के लिए अभी ड्राइवर खोज रहा हूं।",
        "accepted": "{driver} {pickup} आ रहे हैं।",
        "arrived": "{driver} {pickup} पहुंच गए हैं।",
        "in_progress": "आप {dropoff} के रास्ते पर हैं।",
        "no_ride": "अभी आपकी कोई राइड नहीं चल रही। कहां जाना है?",
        "calling": "{driver} को कॉल कर रहा हूं।",
        "call_simulated": "{driver} डेमो ड्राइवर हैं, इसलिए यह कॉल सिर्फ़ सिम्युलेटेड है।",
        "call_wait": "अभी कॉल करने के लिए ड्राइवर नहीं है। ड्राइवर खोज रहा हूं।",
        "no_history": "आपने अभी तक कोई यात्रा नहीं की।",
        "history": "आपकी पिछली यात्राएं: {trips}।",
        "where_is": "{place} {town} के पास है। वहां चलें? बताइए आपको कहां से लूं।",
        "which_one": "इस नाम की कुछ जगहें मिली हैं। आप कौन सी कह रहे हैं?",
        "best_value": "सबसे सस्ता {vehicle} है, ₹{fare} में, {pickup} से {dropoff}, {km} किमी। बुक कर दूं?",
        "hello": "{greeting} {name} जी! मैं राही हूं, आपका जम्मू-कश्मीर का लोकल गाइड। बताइए आज कहां चलना है? किसी जगह या मौसम के बारे में भी पूछ सकते हैं।",
        "hello_again": "{greeting} {name} जी! फिर से मिलकर अच्छा लगा। फिर {place} चलें, या आज कहीं और?",
        "locating": "जी ज़रूर, अभी देखता हूं आप कहां हैं।",
        "located": "आप {pickup} के पास हैं।",
        "ask_where": "अपना इलाका या पास का कोई लैंडमार्क बताइए, या मैं आपकी मौजूदा लोकेशन ले सकता हूं।",
        "not_found": "माफ़ कीजिए, \"{place}\" नहीं मिला। पास का कोई लैंडमार्क या मुख्य इलाका बता दीजिए, या मैप पर पिन लगा दीजिए।",
        "approx": "मैंने पिन {area} के आसपास लगाया है। सही न हो तो मैप पर सटीक जगह चुन लीजिए।",
        "pin_prompt": "ठीक है, मैप पर उस जगह टैप कीजिए।",
        "home_saved": "ठीक है {name} जी, {place} आपका घर सेव कर लिया। अब बस बोलिए \"घर चलो\"।",
        "ask_home": "आपका घर अभी मुझे पता नहीं। ऐसे बताइए: \"मेरा घर भारत नगर, तालाब तिल्लो में है\"।",
        "btn_here": "📍 मेरी मौजूदा लोकेशन", "btn_map": "🗺️ मैप पर चुनें", "btn_home": "🏠 घर",
    },
    "ur": {
        "help": "بتائیے کہاں جانا ہے، جیسے \"جموں سے کٹرہ ٹیکسی\"۔ میں جموں کے مندر بھی دکھا سکتا ہوں اور بتا سکتا ہوں کہ آپ کی سواری کہاں ہے۔",
        "greet": "السلام علیکم! آپ کو کہاں جانا ہے؟",
        "ask_pickup": "{dropoff} جانا ہے۔ آپ کو کہاں سے لوں؟ اپنی صحیح جگہ بتائیے، جیسے گلی یا نشان، یا میری موجودہ لوکیشن دبائیے، یا نقشے پر جگہ چنیے۔",
        "ask_dropoff": "{pickup} سے پک اپ۔ کہاں جانا ہے؟",
        "ask_vehicle": "{pickup} سے {dropoff}، {km} کلومیٹر۔ کون سی گاڑی چاہیے؟",
        "not_offered": "اس سفر کے لیے {vehicle} دستیاب نہیں۔ ان میں سے چنیے۔",
        "confirm": "{vehicle}، {pickup} سے {dropoff}: {km} کلومیٹر کے ₹{fare}۔ بک کر دوں؟",
        "rec_rival": "اندازے کے مطابق {rival} سستا ہو سکتا ہے (فرض کردہ نرخ، لائیو کرایہ نہیں)۔ چاہیں تو پہلے اس کی ایپ دیکھ لیجیے۔",
        "rec_us": "اندازے کے مطابق یہ Rapido اور Uber سے سستا ہے (فرض کردہ نرخ، لائیو کرایہ نہیں)۔",
        "booked": "بک ہو گیا! ₹{fare}، {pickup} سے {dropoff}۔ اب ڈرائیور ڈھونڈ رہا ہوں۔ مین اسکرین پر اپنی سواری دیکھیے۔",
        "hint_vehicle": "نیچے دیے گئے آپشنز میں سے ایک چنیے، یا بول کر بتائیے۔",
        "hint_confirm": "نیچے آپ کے پاس دو آپشن ہیں، ان میں سے ایک پر ٹیپ کیجیے، یا ہاں یا نہیں کہہ دیجیے۔",
        "go_there": "🚕 {place} چلیں",
        "ask_spot": "{place} میں کہاں جانا ہے؟ نیچے سے جگہ چنیے، یا کوئی نشان بتائیے۔",
        "whole_area": "بس {place}",
        "already_there": "آپ تو پہلے سے {place} کے پاس ہیں! کہیں اور جانا ہو تو بتائیے۔",
        "nearby_found": "آپ کے قریب یہ {kind} ہیں: {places}۔ جس پر ٹیپ کریں گے، وہاں لے چلوں گا۔",
        "nearby_town": "{place} کے قریب یہ {kind} ہیں: {places}۔ جس پر ٹیپ کریں گے، وہاں لے چلوں گا۔",
        "nearby_none": "آپ کے 15 کلومیٹر کے اندر کوئی {kind} نہیں ملا۔",
        "no_note": "{place} کے بارے میں ابھی میری معلومات کم ہیں، لیکن وہاں کی سواری بک کر سکتا ہوں۔",
        "dropped": "ٹھیک ہے، یہ سفر ہٹا دیا۔ اب کہاں جانا ہے؟",
        "confirm_cancel": "{pickup} سے {dropoff} والی سواری منسوخ کر دوں؟",
        "cancelled": "آپ کی سواری منسوخ ہو گئی۔",
        "cant_cancel": "سفر شروع ہو چکا ہے، اس لیے اب یہ سواری منسوخ نہیں ہو سکتی۔",
        "kept": "ٹھیک ہے، آپ کی سواری بک رہے گی۔",
        "temples": "یہ رہے جموں کے مشہور مندر۔ جہاں جانا ہو، اس پر ٹیپ کیجیے۔",
        "closed": "یہ راستہ ابھی بند ہے، اس لیے یہ سفر بک نہیں ہو سکتا۔ {detail}",
        "outside": "یہ جگہ جموں و کشمیر میں ہمارے سروس ایریا سے باہر ہے۔",
        "too_close": "پک اپ اور ڈراپ بہت قریب ہیں۔ کوئی اور جگہ چنیے۔",
        "failed": "اس سفر کا کرایہ نہیں نکل سکا: {detail}",
        "searching": "{dropoff} کے لیے ابھی ڈرائیور ڈھونڈ رہا ہوں۔",
        "accepted": "{driver} {pickup} آ رہے ہیں۔",
        "arrived": "{driver} {pickup} پہنچ گئے ہیں۔",
        "in_progress": "آپ {dropoff} کے راستے پر ہیں۔",
        "no_ride": "ابھی آپ کی کوئی سواری نہیں چل رہی۔ کہاں جانا ہے؟",
        "calling": "{driver} کو کال کر رہا ہوں۔",
        "call_simulated": "{driver} ڈیمو ڈرائیور ہیں، اس لیے یہ کال صرف فرضی ہے۔",
        "call_wait": "ابھی کال کرنے کے لیے ڈرائیور نہیں ہے۔ ڈرائیور ڈھونڈ رہا ہوں۔",
        "no_history": "آپ نے ابھی تک کوئی سفر نہیں کیا۔",
        "history": "آپ کے پچھلے سفر: {trips}۔",
        "where_is": "{place} {town} کے پاس ہے۔ وہاں چلیں؟ بتائیے آپ کو کہاں سے لوں۔",
        "which_one": "اس نام کی کچھ جگہیں ملی ہیں۔ آپ کون سی کہہ رہے ہیں؟",
        "best_value": "سب سے سستا {vehicle} ہے، ₹{fare} میں، {pickup} سے {dropoff}، {km} کلومیٹر۔ بک کر دوں؟",
        "hello": "{greeting} {name} صاحب! میں راہی ہوں، آپ کا جموں و کشمیر کا مقامی گائیڈ۔ بتائیے آج کہاں چلنا ہے؟ کسی جگہ یا موسم کے بارے میں بھی پوچھ سکتے ہیں۔",
        "hello_again": "{greeting} {name} صاحب! پھر مل کر اچھا لگا۔ پھر {place} چلیں، یا آج کہیں اور؟",
        "locating": "جی ضرور، ابھی دیکھتا ہوں آپ کہاں ہیں۔",
        "located": "آپ {pickup} کے پاس ہیں۔",
        "ask_where": "اپنا علاقہ یا قریب کا کوئی نشان بتائیے، یا میں آپ کی موجودہ لوکیشن لے سکتا ہوں۔",
        "not_found": "معاف کیجیے، \"{place}\" نہیں ملا۔ قریب کا کوئی نشان یا بڑا علاقہ بتا دیجیے، یا نقشے پر پن لگا دیجیے۔",
        "approx": "میں نے پن {area} کے آس پاس لگایا ہے۔ درست نہ ہو تو نقشے پر صحیح جگہ چن لیجیے۔",
        "pin_prompt": "ٹھیک ہے، نقشے پر اس جگہ ٹیپ کیجیے۔",
        "home_saved": "ٹھیک ہے {name} صاحب، {place} آپ کا گھر محفوظ کر لیا۔ اب بس کہیے \"گھر چلو\"۔",
        "ask_home": "آپ کا گھر ابھی مجھے معلوم نہیں۔ ایسے بتائیے: \"میرا گھر بھارت نگر، تالاب تلو میں ہے\"۔",
        "btn_here": "📍 میری موجودہ لوکیشن", "btn_map": "🗺️ نقشے پر چنیں", "btn_home": "🏠 گھر",
    },
}

FAITH_NAMES = {
    "en": {"temple": "temples", "mosque": "mosques", "gurudwara": "gurudwaras"},
    "hinglish": {"temple": "mandir", "mosque": "masjidein", "gurudwara": "gurudware"},
    "hi": {"temple": "मंदिर", "mosque": "मस्जिदें", "gurudwara": "गुरुद्वारे"},
    "ur": {"temple": "مندر", "mosque": "مساجد", "gurudwara": "گردوارے"},
}
AND = {"en": "and", "hinglish": "aur", "hi": "और", "ur": "اور"}


def spoken_list(lang: str, items: list) -> str:
    """"A, B and C", the way it is said in each language."""
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} {AND[lang]} {items[-1]}"


BUTTON_LABELS = {
    "en": {"yes": "Yes, book it", "no": "No"},
    "hinglish": {"yes": "Haan, book karo", "no": "Nahi"},
    "hi": {"yes": "हां, बुक करें", "no": "नहीं"},
    "ur": {"yes": "ہاں، بک کریں", "no": "نہیں"},
}


# Short openers, so the assistant doesn't repeat one fixed sentence shape.
ACKS = {
    "en": ["Sure.", "Okay.", "Got it.", "Alright."],
    "hinglish": ["Ji.", "Theek hai.", "Achha.", "Bilkul."],
    "hi": ["जी।", "ठीक है।", "अच्छा।", "बिल्कुल।"],
    "ur": ["جی۔", "ٹھیک ہے۔", "اچھا۔", "بالکل۔"],
}
GREETINGS = {
    "en": ("Good morning", "Good afternoon", "Good evening"),
    "hinglish": ("Good morning", "Namaste", "Good evening"),
    "hi": ("सुप्रभात", "नमस्ते", "शुभ संध्या"),
    "ur": ("صبح بخیر", "آداب", "شام بخیر"),
}
SPOKEN_UNITS = {
    "en": ("rupees", "kilometres"), "hinglish": ("rupaye", "kilometre"),
    "hi": ("रुपये", "किलोमीटर"), "ur": ("روپے", "کلومیٹر"),
}


def greeting_for(lang: str, hour: int) -> str:
    return GREETINGS[lang][0 if hour < 12 else 1 if hour < 17 else 2]


def with_ack(lang: str, text: str, turn: int) -> str:
    return f"{ACKS[lang][turn % len(ACKS[lang])]} {text}"


def spoken(text: str, lang: str) -> str:
    """How a person would say this aloud: "₹899, 39.4 km" becomes rupees and kilometres."""
    rupees, km = SPOKEN_UNITS[lang]
    text = re.sub(r"₹\s?([\d,]+)", lambda m: f"{m.group(1).replace(',', '')} {rupees}", text)
    text = re.sub(r"(\d)\s?(km|किमी)\b", lambda m: f"{m.group(1)} {km}", text)
    text = re.sub(r"(\d)\s?(किमी)", lambda m: f"{m.group(1)} {km}", text)
    return re.sub(r"\([^)]*\)", "", text).replace("\"", "").strip()


def place_label(name: str, lang: str) -> str:
    """A place name in the rider's own script. Map pins and unknown names stay as they are."""
    script = {"hi": r"[\u0900-\u097f]", "ur": r"[\u0600-\u06ff]"}.get(lang)
    if script:
        for alias in ALIASES.get(name, []):
            if re.search(script, alias):
                return alias
    return name


def say(lang: str, key: str, **values) -> str:
    lang = lang or "en"
    for field_name in ("pickup", "dropoff", "place", "town"):
        if field_name in values:
            values[field_name] = place_label(values[field_name], lang)
    return REPLIES[lang][key].format(**values)
