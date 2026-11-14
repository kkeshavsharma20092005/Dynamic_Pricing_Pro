"""
What the assistant knows about Jammu & Kashmir beyond booking: short notes on the places
riders ask about most, and today's weather.

The notes are written by hand and kept short and general (what a place is, when people go),
so they stay true; fares and distances always come from the app itself. Weather is live from
Open-Meteo, which is free and needs no key or account. Set LIVE_WEATHER=0 to turn it off; the
assistant then reports the conditions the admin has set, which is also the fallback whenever
Open-Meteo can't be reached.
"""
import os
import time

import httpx

from places import BY_NAME

WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
WEATHER_CACHE_SECONDS = 600
_weather_cache: dict[tuple, tuple[float, dict]] = {}

# Where each region's weather is read when the rider names no place.
REGION_POINTS = {"JMU": "Jammu City", "KSH": "Srinagar, Lal Chowk", "HIL": "Patnitop"}

# (English, Roman Hindi, Hindi) for each place.
PLACE_NOTES = {
    "Katra": (
        "Katra is the base town for the Mata Vaishno Devi shrine in the Trikuta hills. The walk from Katra to the Bhawan is about 13 km; the yatra is open all year and is busiest during Navratri and the summer holidays. Pilgrims need a yatra registration before starting.",
        "Katra Mata Vaishno Devi ke darshan ka base town hai, Trikuta pahadiyon mein. Katra se Bhawan tak lagbhag 13 km ki chadhai hai; yatra saal bhar khuli rehti hai, aur Navratri aur garmiyon ki chhuttiyon mein sabse zyada bheed hoti hai. Chadhai se pehle yatra registration zaroori hai.",
        "कटरा त्रिकुटा पहाड़ियों में माता वैष्णो देवी के दर्शन का बेस टाउन है। कटरा से भवन तक लगभग 13 किमी की चढ़ाई है; यात्रा साल भर खुली रहती है, और नवरात्रि और गर्मियों की छुट्टियों में सबसे ज़्यादा भीड़ होती है। चढ़ाई से पहले यात्रा पंजीकरण ज़रूरी है।"),
    "Jammu City": (
        "Jammu is called the City of Temples. Popular stops are the Raghunath Temple, Bahu Fort with the Bawe Wali Mata temple, the Mubarak Mandi palace and the Peer Kho cave temple. Jammu is also the starting point for trips to Katra and Kashmir.",
        "Jammu ko mandiron ka shehar kehte hain. Yahan Raghunath Mandir, Bawe Wali Mata ke mandir wala Bahu Kila, Mubarak Mandi mahal aur Peer Kho gufa mandir dekhne layak hain. Katra aur Kashmir ki yatra bhi yahin se shuru hoti hai.",
        "जम्मू को मंदिरों का शहर कहते हैं। यहां रघुनाथ मंदिर, बावे वाली माता के मंदिर वाला बाहु किला, मुबारक मंडी महल और पीर खोह गुफा मंदिर देखने लायक हैं। कटरा और कश्मीर की यात्रा भी यहीं से शुरू होती है।"),
    "Raghunath Temple": (
        "The Raghunath Temple in the heart of Jammu is a large 19th-century temple complex dedicated to Lord Ram, started by Maharaja Gulab Singh and completed by Maharaja Ranbir Singh.",
        "Jammu ke beech mein Raghunath Mandir Bhagwan Ram ko samarpit 19vi sadi ka bada mandir parisar hai. Ise Maharaja Gulab Singh ne shuru kiya aur Maharaja Ranbir Singh ne poora kiya.",
        "जम्मू के बीच में रघुनाथ मंदिर भगवान राम को समर्पित 19वीं सदी का बड़ा मंदिर परिसर है। इसे महाराजा गुलाब सिंह ने शुरू किया और महाराजा रणबीर सिंह ने पूरा किया।"),
    "Bahu Fort": (
        "Bahu Fort stands above the Tawi river in Jammu. Inside is the Bawe Wali Mata (Mahakali) temple, which is busiest on Tuesdays and Sundays, and the Bagh-e-Bahu garden is next to it.",
        "Bahu Kila Jammu mein Tawi nadi ke upar bana hai. Iske andar Bawe Wali Mata (Mahakali) ka mandir hai, jahan Mangalvar aur Ravivar ko sabse zyada bheed hoti hai. Paas mein Bagh-e-Bahu bagicha hai.",
        "बाहु किला जम्मू में तवी नदी के ऊपर बना है। इसके अंदर बावे वाली माता (महाकाली) का मंदिर है, जहां मंगलवार और रविवार को सबसे ज़्यादा भीड़ होती है। पास में बाग़-ए-बाहु बगीचा है।"),
    "Patnitop": (
        "Patnitop is a hill station on the Jammu-Srinagar highway, about 2,000 m up, with pine forests and walking trails. It usually gets snow in winter; Nathatop and Sanasar are nearby.",
        "Patnitop Jammu-Srinagar highway par lagbhag 2,000 m ki oonchai par hill station hai, cheed ke jungle aur paidal raaston ke saath. Sardiyon mein aksar barf girti hai; paas mein Nathatop aur Sanasar hain.",
        "पटनीटॉप जम्मू-श्रीनगर हाईवे पर लगभग 2,000 मीटर की ऊंचाई पर हिल स्टेशन है, चीड़ के जंगल और पैदल रास्तों के साथ। सर्दियों में अक्सर बर्फ़ गिरती है; पास में नत्थाटॉप और सनासर हैं।"),
    "Shiv Khori": (
        "Shiv Khori is a cave shrine of Lord Shiva in Reasi district, with a natural Shiva lingam inside. Pilgrims walk about 3 km from the Ransoo base to the cave; it is crowded around Mahashivratri.",
        "Shiv Khori Reasi zile mein Bhagwan Shiv ki gufa hai, jiske andar prakritik Shivling hai. Ransoo base se gufa tak lagbhag 3 km paidal chalna hota hai; Mahashivratri par bahut bheed hoti hai.",
        "शिव खोड़ी रियासी ज़िले में भगवान शिव की गुफा है, जिसके अंदर प्राकृतिक शिवलिंग है। रनसू बेस से गुफा तक लगभग 3 किमी पैदल चलना होता है; महाशिवरात्रि पर बहुत भीड़ होती है।"),
    "Mansar Lake": (
        "Mansar is a forest-ringed lake in Samba district, good for a day trip from Jammu, with boating and an old Sheshnag temple on its bank.",
        "Mansar Samba zile mein jungle se ghiri jheel hai, Jammu se ek din ki trip ke liye achhi. Yahan boating hoti hai aur kinare par purana Sheshnag mandir hai.",
        "मानसर सांबा ज़िले में जंगल से घिरी झील है, जम्मू से एक दिन की यात्रा के लिए अच्छी। यहां नौका विहार होता है और किनारे पर पुराना शेषनाग मंदिर है।"),
    "Baba Dhansar": (
        "Baba Dhansar is a shrine near Katra in Reasi district, beside a spring and waterfall, often visited together with Vaishno Devi.",
        "Baba Dhansar Reasi zile mein Katra ke paas ek dhaam hai, ek jharne aur jal-dhara ke kinare. Log aksar ise Vaishno Devi ke saath dekhte hain.",
        "बाबा धनसर रियासी ज़िले में कटरा के पास एक धाम है, एक झरने और जलधारा के किनारे। लोग अक्सर इसे वैष्णो देवी के साथ देखते हैं।"),
    "Krimchi Temples": (
        "The Krimchi temples near Udhampur are a group of ancient stone temples, protected as a heritage site.",
        "Udhampur ke paas Krimchi mandir purane pathar ke mandiron ka samooh hain, jo dharohar sthal ke roop mein surakshit hain.",
        "उधमपुर के पास क्रिमची मंदिर पुराने पत्थर के मंदिरों का समूह हैं, जो धरोहर स्थल के रूप में सुरक्षित हैं।"),
    "Srinagar, Lal Chowk": (
        "Srinagar, the summer capital, is known for Dal Lake shikara rides and houseboats, the Mughal gardens such as Nishat and Shalimar, and the Hazratbal shrine. Lal Chowk is its central market.",
        "Srinagar garmiyon ki rajdhani hai, Dal Jheel ke shikara aur houseboat, Nishat aur Shalimar jaise Mughal bagh, aur Hazratbal dargah ke liye mashhoor. Lal Chowk yahan ka mukhya bazaar hai.",
        "श्रीनगर गर्मियों की राजधानी है, डल झील के शिकारा और हाउसबोट, निशात और शालीमार जैसे मुग़ल बाग़, और हज़रतबल दरगाह के लिए मशहूर। लाल चौक यहां का मुख्य बाज़ार है।"),
    "Dal Gate": (
        "Dal Lake in Srinagar is known for shikara rides, houseboats and the early-morning floating vegetable market. Dal Gate is the usual starting point.",
        "Srinagar ki Dal Jheel shikara sawari, houseboat aur subah-subah ki tairti sabzi mandi ke liye mashhoor hai. Dal Gate se aam taur par shuruaat hoti hai.",
        "श्रीनगर की डल झील शिकारा सवारी, हाउसबोट और सुबह-सुबह की तैरती सब्ज़ी मंडी के लिए मशहूर है। डल गेट से आम तौर पर शुरुआत होती है।"),
    "Gulmarg": (
        "Gulmarg is a meadow resort known for the Gulmarg Gondola cable car and for skiing in winter, roughly December to March. In summer it is green and good for walks.",
        "Gulmarg ek maidani resort hai, Gulmarg Gondola cable car aur sardiyon (lagbhag December se March) mein skiing ke liye mashhoor. Garmiyon mein yahan hariyali hoti hai aur ghoomna achha lagta hai.",
        "गुलमर्ग एक मैदानी रिज़ॉर्ट है, गुलमर्ग गोंडोला केबल कार और सर्दियों (लगभग दिसंबर से मार्च) में स्कीइंग के लिए मशहूर। गर्मियों में यहां हरियाली होती है और घूमना अच्छा लगता है।"),
    "Pahalgam": (
        "Pahalgam lies in the Lidder valley, with Betaab Valley, Aru and Chandanwari nearby. It is a base for the Amarnath Yatra, usually held in July and August.",
        "Pahalgam Lidder ghati mein hai, paas mein Betaab Valley, Aru aur Chandanwari hain. Yeh Amarnath Yatra ka base hai, jo aam taur par July-August mein hoti hai.",
        "पहलगाम लिद्दर घाटी में है, पास में बेताब घाटी, अरु और चंदनवाड़ी हैं। यह अमरनाथ यात्रा का बेस है, जो आम तौर पर जुलाई-अगस्त में होती है।"),
    "Sonamarg": (
        "Sonamarg, the 'meadow of gold', is known for the Thajiwas glacier and is a base for the Baltal route to Amarnath. The road can close in winter because of snow.",
        "Sonamarg yaani 'sone ka maidan', Thajiwas glacier ke liye mashhoor hai aur Amarnath ke Baltal raaste ka base hai. Sardiyon mein barf se raasta band ho sakta hai.",
        "सोनमर्ग यानी 'सोने का मैदान', थाजीवास ग्लेशियर के लिए मशहूर है और अमरनाथ के बालटाल रास्ते का बेस है। सर्दियों में बर्फ़ से रास्ता बंद हो सकता है।"),
    "Betaab Valley": (
        "Betaab Valley is a green valley near Pahalgam with a stream, meadows and mountain views, named after the film Betaab shot there.",
        "Betaab Valley Pahalgam ke paas hari-bhari ghati hai, nadi, maidan aur pahadon ke nazare ke saath. Iska naam yahan shoot hui film Betaab par pada.",
        "बेताब घाटी पहलगाम के पास हरी-भरी घाटी है, नदी, मैदान और पहाड़ों के नज़ारे के साथ। इसका नाम यहां शूट हुई फ़िल्म बेताब पर पड़ा।"),
    "Nishat Bagh": (
        "Nishat Bagh is a terraced Mughal garden on the bank of Dal Lake in Srinagar, with fountains and chinar trees.",
        "Nishat Bagh Srinagar mein Dal Jheel ke kinare seedhiyon wala Mughal bagh hai, fawwaron aur chinar ke pedon ke saath.",
        "निशात बाग़ श्रीनगर में डल झील के किनारे सीढ़ीदार मुग़ल बाग़ है, फव्वारों और चिनार के पेड़ों के साथ।"),
    "Hazratbal": (
        "The Hazratbal shrine is a white marble mosque on the shore of Dal Lake in Srinagar, one of the most revered shrines in Kashmir.",
        "Hazratbal dargah Srinagar mein Dal Jheel ke kinare safed sangmarmar ki masjid hai, Kashmir ki sabse pavitra dargahon mein se ek.",
        "हज़रतबल दरगाह श्रीनगर में डल झील के किनारे सफ़ेद संगमरमर की मस्जिद है, कश्मीर की सबसे पवित्र दरगाहों में से एक।"),
}
LANG_INDEX = {"en": 0, "hinglish": 1, "hi": 2}

# A local's advice, added after a booking to these places. (English, Roman Hindi, Hindi)
PLACE_TIPS = {
    "Katra": ("Jai Mata Di! Get your yatra registration done before the climb, and wear comfortable shoes.",
              "Jai Mata Di! Chadhai se pehle yatra registration karwa lijiye, aur aaram wale joote pehniye.",
              "जय माता दी! चढ़ाई से पहले यात्रा पंजीकरण करवा लीजिए, और आरामदायक जूते पहनिए।"),
    "Bahu Fort": ("Jai Mata Di! The temple is busiest on Tuesdays and Sundays.",
                  "Jai Mata Di! Mangalvar aur Ravivar ko mandir mein sabse zyada bheed hoti hai.",
                  "जय माता दी! मंगलवार और रविवार को मंदिर में सबसे ज़्यादा भीड़ होती है।"),
    "Shiv Khori": ("Jai Bhole! Keep some water with you for the walk to the cave.",
                   "Jai Bhole! Gufa tak paidal raaste ke liye paani saath rakhiye.",
                   "जय भोले! गुफा तक पैदल रास्ते के लिए पानी साथ रखिए।"),
    "Patnitop": ("It gets cold up there, so carry warm clothes.",
                 "Wahan thand hoti hai, garam kapde saath rakhiye.",
                 "वहां ठंड होती है, गर्म कपड़े साथ रखिए।"),
    "Gulmarg": ("Carry warm clothes; it is much colder than the plains.",
                "Garam kapde saath rakhiye, wahan maidani ilaakon se kaafi zyada thand hoti hai.",
                "गर्म कपड़े साथ रखिए, वहां मैदानी इलाकों से काफ़ी ज़्यादा ठंड होती है।"),
    "Sonamarg": ("Carry warm clothes, and check the road is open in winter.",
                 "Garam kapde rakhiye, aur sardiyon mein raasta khula hai ya nahi, pehle pata kar lijiye.",
                 "गर्म कपड़े रखिए, और सर्दियों में रास्ता खुला है या नहीं, पहले पता कर लीजिए।"),
    "Pahalgam": ("Carry a warm layer; evenings get cool.",
                 "Ek garam kapda saath rakhiye, shaam ko thand ho jaati hai.",
                 "एक गर्म कपड़ा साथ रखिए, शाम को ठंड हो जाती है।"),
    "Dal Gate": ("Settle the shikara fare before you board.",
                 "Shikara mein baithne se pehle kiraya tay kar lijiye.",
                 "शिकारा में बैठने से पहले किराया तय कर लीजिए।"),
}

OVERVIEW = {
    "en": "Popular places: around Jammu, the Raghunath Temple, Bahu Fort, Mansar Lake and Patnitop; Katra for Vaishno Devi, with Shiv Khori and Baba Dhansar nearby; in Kashmir, Srinagar's Dal Lake and Mughal gardens, Gulmarg, Pahalgam and Sonamarg. Ask me about any of them, or tap one to go there.",
    "hinglish": "Mashhoor jagahen: Jammu ke paas Raghunath Mandir, Bahu Kila, Mansar Jheel aur Patnitop; Vaishno Devi ke liye Katra, paas mein Shiv Khori aur Baba Dhansar; Kashmir mein Srinagar ki Dal Jheel aur Mughal bagh, Gulmarg, Pahalgam aur Sonamarg. Kisi ke baare mein puchiye, ya tap karke wahan chaliye.",
    "hi": "मशहूर जगहें: जम्मू के पास रघुनाथ मंदिर, बाहु किला, मानसर झील और पटनीटॉप; वैष्णो देवी के लिए कटरा, पास में शिव खोड़ी और बाबा धनसर; कश्मीर में श्रीनगर की डल झील और मुग़ल बाग़, गुलमर्ग, पहलगाम और सोनमर्ग। किसी के बारे में पूछिए, या टैप करके वहां चलिए।",
}
OVERVIEW_PLACES = ["Raghunath Temple", "Bahu Fort", "Katra", "Shiv Khori", "Patnitop", "Mansar Lake",
                   "Dal Gate", "Gulmarg", "Pahalgam", "Sonamarg"]

# WMO weather codes, grouped.
SKY = {
    "en": {"clear": "clear", "cloudy": "partly cloudy", "fog": "foggy", "drizzle": "drizzle",
           "rain": "raining", "snow": "snowing", "storm": "thunderstorms"},
    "hinglish": {"clear": "saaf aasmaan", "cloudy": "halke baadal", "fog": "kohra", "drizzle": "boonda-baandi",
                 "rain": "baarish", "snow": "barfbaari", "storm": "aandhi-toofan"},
    "hi": {"clear": "साफ़ आसमान", "cloudy": "हल्के बादल", "fog": "कोहरा", "drizzle": "बूंदाबांदी",
           "rain": "बारिश", "snow": "बर्फ़बारी", "storm": "आंधी-तूफ़ान"},
}
WEATHER_TEXT = {
    "en": {"line": "{place}: {temp}°C, {sky}", "closed": "the road there is closed right now",
           "live": "Weather now: {lines}.", "set": "Conditions in the app (not live weather): {lines}."},
    "hinglish": {"line": "{place}: {temp}°C, {sky}", "closed": "wahan ka raasta abhi band hai",
                 "live": "Abhi ka mausam: {lines}.", "set": "App mein di gayi jaankari (live mausam nahi): {lines}."},
    "hi": {"line": "{place}: {temp}°C, {sky}", "closed": "वहां का रास्ता अभी बंद है",
           "live": "अभी का मौसम: {lines}।", "set": "ऐप में दी गई जानकारी (लाइव मौसम नहीं): {lines}।"},
}
# The app's own condition names, for when live weather is off.
CONDITION_SKY = {"Clear": "clear", "Cloudy": "cloudy", "Foggy": "fog", "Rainy": "rain", "Stormy": "storm", "Snowy": "snow"}


def text_lang(lang: str) -> str:
    """These notes exist in English, Roman Hindi and Hindi; Urdu readers get the English."""
    return lang if lang in LANG_INDEX else "en"


def place_note(name: str, lang: str) -> str | None:
    notes = PLACE_NOTES.get(name)
    return notes[LANG_INDEX[text_lang(lang)]] if notes else None


def place_tip(name: str, lang: str) -> str | None:
    tips = PLACE_TIPS.get(name)
    return tips[LANG_INDEX[text_lang(lang)]] if tips else None


def sky_kind(code: int) -> str:
    if code == 0:
        return "clear"
    if code in (45, 48):
        return "fog"
    if 51 <= code <= 57:
        return "drizzle"
    if 61 <= code <= 67 or 80 <= code <= 82:
        return "rain"
    if 71 <= code <= 77 or code in (85, 86):
        return "snow"
    if code >= 95:
        return "storm"
    return "cloudy"


def live_weather(names: list[str]) -> list[dict] | None:
    """Current temperature and sky at these places, or None if live weather is off or failing."""
    if os.environ.get("LIVE_WEATHER", "1") == "0":
        return None
    key = tuple(names)
    cached = _weather_cache.get(key)
    if cached and time.time() - cached[0] < WEATHER_CACHE_SECONDS:
        return cached[1]
    points = [BY_NAME[n] for n in names]
    try:
        response = httpx.get(WEATHER_URL, timeout=5, params={
            "latitude": ",".join(str(p["lat"]) for p in points),
            "longitude": ",".join(str(p["lon"]) for p in points),
            "current": "temperature_2m,weather_code", "timezone": "Asia/Kolkata"})
        response.raise_for_status()
        data = response.json()
        data = data if isinstance(data, list) else [data]
        result = [{"temp": round(d["current"]["temperature_2m"]), "sky": sky_kind(int(d["current"]["weather_code"]))}
                  for d in data]
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as e:
        print(f"[weather] Open-Meteo failed: {e}")
        return None
    _weather_cache[key] = (time.time(), result)
    return result


def weather_text(lang: str, places: list[tuple[str, str]], conditions: dict, label) -> str:
    """places: [(place name, region)]; conditions: region -> the app's conditions; label: name in the rider's script."""
    lang = text_lang(lang)
    words, sky = WEATHER_TEXT[lang], SKY[lang]
    live = live_weather([name for name, _ in places])
    lines = []
    for i, (name, region) in enumerate(places):
        if live:
            temp, kind = live[i]["temp"], live[i]["sky"]
        else:
            temp = round(conditions[region]["temperature"])
            kind = CONDITION_SKY.get(conditions[region]["weather_condition"], "cloudy")
        line = words["line"].format(place=label(name), temp=temp, sky=sky[kind])
        if conditions[region].get("road_closed"):
            line += f" ({words['closed']})"
        lines.append(line)
    return words["live" if live else "set"].format(lines="; ".join(lines))
