"""The assistant as a local guide: Dogri, everyday phrasings, place notes, weather and nearby temples."""
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "data_pipeline"))

import testenv  # noqa: F401  (must precede the backend imports)
import httpx
from fastapi.testclient import TestClient

import chatbot
import jkinfo
import placesdb
from chatbot import parse
from main import app
from places import BY_NAME

JAMMU = {"lat": 32.7266, "lon": 74.857}
_next_phone = [9800000000]


class GuideParsingTests(unittest.TestCase):
    def test_dogri_trips(self):
        for text, pickup, dropoff in (
            ("मिगी जम्मू थमां कटरा जाना ऐ", "Jammu City", "Katra"),
            ("jammu thaman katra gaddi chahidi ae", "Jammu City", "Katra"),
            # "Airport" alone is found near the rider later, when the place is looked up.
            ("इत्थूं एयरपोर्ट जाना ऐ", chatbot.CURRENT, "एयरपोर्ट"),
            ("ithun airport jana ae", chatbot.CURRENT, "airport"),
            ("मिगी इत्थूं कटरा जाना ऐ", chatbot.CURRENT, "Katra"),
        ):
            p = parse(text)
            self.assertEqual((p.pickup, p.dropoff), (pickup, dropoff), text)
        self.assertEqual(parse("jammu thaman katra gaddi chahidi ae").vehicle, "cab")
        self.assertEqual(parse("migi katra jana ae").lang, "hinglish")
        self.assertEqual(parse("मैं कटरा जाना ऐ").dropoff, "Katra")
        self.assertEqual(parse("कटरा दा किराया किन्ना ऐ").place, "Katra")

    def test_everyday_phrasings_name_the_destination(self):
        for text, place in (("vaishno devi kaise jaun", "Katra"), ("mujhe abhi katra ke liye gaadi chahiye", "Katra"),
                            ("patnitop kitni door hai", "Patnitop"), ("how far is Patnitop", "Patnitop"),
                            ("पटनीटॉप कितनी दूर है", "Patnitop")):
            p = parse(text)
            self.assertEqual(p.dropoff or p.place, place, text)

    def test_yes_with_kar_do_is_still_a_plain_yes(self):
        for text in ("haan book kar do", "haan ji book karo", "हां जी", "yes please book it", "ok book this"):
            p = parse(text)
            self.assertTrue(p.confirm, text)
            self.assertFalse(p.has_place or p.free, text)

    def test_questions_are_not_trips(self):
        for text, place in (("katra mein kya dekhna hai", "Katra"), ("vaishno devi ki yatra kab hoti hai", "Katra"),
                            ("jammu mein ghoomne ki jagah batao", "Jammu City"), ("गुलमर्ग के बारे में बताओ", "Gulmarg")):
            p = parse(text)
            self.assertTrue(p.info, text)
            self.assertEqual(p.about, place, text)
        self.assertTrue(parse("aaj mausam kaisa hai").weather)
        self.assertEqual(parse("srinagar ka mausam batao").about, "Srinagar, Lal Chowk")
        # A trip that mentions a place's sights is still a trip.
        self.assertFalse(parse("katra jana hai darshan ke liye").info)

    def test_nearby_places_of_worship(self):
        for text, faith, near in (
            ("mujhe jammu ke mandir dekhne hai apni current location se jo paas mai hai", "temple", chatbot.CURRENT),
            ("temples near me", "temple", chatbot.CURRENT), ("मेरे पास के मंदिर दिखाओ", "temple", chatbot.CURRENT),
            ("इत्थूं कोल मंदिर", "temple", chatbot.CURRENT), ("mere paas ki masjid dikhao", "mosque", chatbot.CURRENT),
            ("nearest gurudwara", "gurudwara", chatbot.CURRENT), ("katra ke paas mandir", "temple", "Katra"),
        ):
            p = parse(text)
            self.assertEqual((p.nearby, p.near), (faith, near), text)
        # Without "near", Jammu's temples are still the photo tour.
        self.assertTrue(parse("jammu ke mandir dikhao").temples)


class KnowledgeTests(unittest.TestCase):
    def test_every_note_and_tip_is_about_a_known_place_in_three_languages(self):
        for table in (jkinfo.PLACE_NOTES, jkinfo.PLACE_TIPS):
            for name, texts in table.items():
                self.assertIn(name, BY_NAME)
                self.assertEqual(len(texts), 3)
                self.assertTrue(all(texts), name)
        self.assertTrue(set(jkinfo.OVERVIEW_PLACES) <= set(BY_NAME))
        self.assertEqual(jkinfo.place_note("Katra", "ur"), jkinfo.place_note("Katra", "en"))

    def test_weather_codes(self):
        self.assertEqual([jkinfo.sky_kind(c) for c in (0, 2, 45, 53, 63, 81, 73, 86, 95)],
                         ["clear", "cloudy", "fog", "drizzle", "rain", "rain", "snow", "snow", "storm"])

    def test_live_weather_and_its_fallback(self):
        conditions = {"JMU": {"temperature": 30.4, "weather_condition": "Clear", "road_closed": False},
                      "KSH": {"temperature": 5.0, "weather_condition": "Snowy", "road_closed": True}}
        places = [("Jammu City", "JMU"), ("Gulmarg", "KSH")]
        label = lambda name: name   # noqa: E731
        jkinfo._weather_cache.clear()
        live = httpx.Response(200, json=[{"current": {"temperature_2m": 17.3, "weather_code": 0}},
                                         {"current": {"temperature_2m": -2.4, "weather_code": 73}}],
                              request=httpx.Request("GET", jkinfo.WEATHER_URL))
        with mock.patch.dict("os.environ", {"LIVE_WEATHER": "1"}), mock.patch.object(jkinfo.httpx, "get", return_value=live):
            text = jkinfo.weather_text("en", places, conditions, label)
        self.assertEqual(text, "Weather now: Jammu City: 17°C, clear; Gulmarg: -2°C, snowing (the road there is closed right now).")
        jkinfo._weather_cache.clear()
        with mock.patch.dict("os.environ", {"LIVE_WEATHER": "1"}), \
                mock.patch.object(jkinfo.httpx, "get", side_effect=httpx.ConnectError("down")):
            text = jkinfo.weather_text("hinglish", places, conditions, label)
        self.assertTrue(text.startswith("App mein di gayi jaankari (live mausam nahi): Jammu City: 30°C, saaf aasmaan"), text)

    def test_road_advisory_warns_in_bad_weather(self):
        jkinfo._weather_cache.clear()
        answer = httpx.Response(200, json=[{"current": {"temperature_2m": 9, "weather_code": 0}},
                                           {"current": {"temperature_2m": 1, "weather_code": 73}},
                                           {"current": {"temperature_2m": 4, "weather_code": 3}}],
                                request=httpx.Request("GET", jkinfo.WEATHER_URL))
        with mock.patch.dict("os.environ", {"LIVE_WEATHER": "1"}), mock.patch.object(jkinfo.httpx, "get", return_value=answer):
            text = jkinfo.road_advisory("hinglish", "nh44", jkinfo.HIGHWAY_POINTS, lambda n: n)
        self.assertEqual(text, "Raaste ka alert: Jammu-Srinagar highway (NH-44) par abhi mausam kharab hai (Ramban 9°C saaf aasmaan, "
                               "Banihal 1°C barfbaari, Qazigund 4°C halke baadal). Is mausam mein landslide, patthar girne aur jaam "
                               "ka khatra rehta hai. Nikalne se pehle J&K Traffic Police ki advisory zaroor dekh lijiye.")
        jkinfo._weather_cache.clear()

    def test_area_spots_are_real_places_not_statues(self):
        from places import BY_NAME as places
        area = places["Gandhi Nagar, Jammu"]
        names = [s["name"] for s in placesdb.spots_in(area["lat"], area["lon"], 1.2)]
        self.assertIn("District Hospital Gandhi Nagar", names)
        self.assertLessEqual(len(names), 6)
        jammu = places["Jammu City"]
        self.assertNotIn("Mahatma Gandhi", [s["name"] for s in placesdb.spots_in(jammu["lat"], jammu["lon"], 2.0)])

    def test_nearby_worship_sorts_by_distance_and_skips_unnamed_places(self):
        temples = placesdb.nearby_worship(JAMMU["lat"], JAMMU["lon"], "temple")
        self.assertTrue(temples)
        self.assertEqual(temples, sorted(temples, key=lambda t: t["km"]))
        self.assertTrue(all(t["km"] <= 15 for t in temples))
        self.assertIn("Raghunath Mandir", [t["name"] for t in temples])
        mosques = placesdb.nearby_worship(JAMMU["lat"], JAMMU["lon"], "mosque")
        self.assertTrue(all(placesdb.faith_of({"name": m["name"], "forms": []}) == "mosque" for m in mosques))
        self.assertFalse([t for t in temples if t["name"].lower() in ("mandir", "temple")])


class GuideConversationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)

    def setUp(self):
        _next_phone[0] += 1
        account = {"phone": str(_next_phone[0]), "password": "password123", "role": "rider"}
        with mock.patch("mailer.send_quietly"):
            self.client.post("/api/register", json={**account, "name": "Guide Rider", "email": "g@example.com"})
        token = self.client.post("/api/login", json=account).json()["token"]
        self.headers = {"Authorization": "Bearer " + token}

    def say(self, message, **extra):
        response = self.client.post("/api/chat", headers=self.headers, json={"message": message, **extra})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def tearDown(self):
        active = self.client.get("/api/rides/active", headers=self.headers).json()
        if active:
            self.client.post(f"/api/rides/{active['id']}/cancel", headers=self.headers)

    def test_kar_do_books_and_a_local_tip_follows(self):
        offer = self.say("jammu se katra cab")
        self.assertIn("do option hain", offer["text"])
        booked = self.say("haan book kar do")
        self.assertIn("ride", booked)
        self.assertIn("Main screen par apni ride dekhiye", booked["text"])
        self.assertIn("Jai Mata Di!", booked["text"])

    def test_vehicle_question_says_how_to_answer(self):
        self.assertIn("Neeche diye options", self.say("jammu se katra jana hai")["text"])

    def test_missing_pickup_lets_the_app_use_the_riders_location(self):
        reply = self.say("mujhe katra jana hai")
        self.assertTrue(reply["ask_location"])
        self.assertEqual(reply["buttons"][0]["action"], "location")

    def test_place_question_gets_a_note_and_a_way_there(self):
        reply = self.say("katra mein kya dekhna hai")
        self.assertIn("Vaishno Devi", reply["text"])
        self.assertEqual(reply["buttons"], [{"label": "🚕 Katra chalein", "send": "to Katra"}])
        overview = self.say("ghoomne ki jagah batao")
        self.assertEqual(len(overview["buttons"]), len(jkinfo.OVERVIEW_PLACES))
        self.assertIn("jaankari kam", self.say("samba ke baare mein batao")["text"])

    def test_weather_uses_the_apps_conditions_when_live_weather_is_off(self):
        reply = self.say("aaj mausam kaisa hai")
        self.assertTrue(reply["text"].startswith("App mein di gayi jaankari"), reply["text"])
        self.assertIn("Patnitop", reply["text"])

    def test_temples_near_me_then_a_tap_goes_straight_to_fares(self):
        asked = self.say("mujhe jammu ke mandir dekhne hai apni current location se jo paas mai hai")
        self.assertEqual(asked["need_location"], "nearby:temple")
        found = self.say("", location=JAMMU, target="nearby:temple")
        self.assertIn("Aapke paas yeh mandir hain", found["text"])
        self.assertIn("pickup", found)
        first = found["buttons"][0]
        self.assertEqual((first["action"], first["target"]), ("point", "dropoff"))
        fares = self.say("", location=first["point"], target="dropoff")
        self.assertIn("Kaunsi gaadi chahiye", fares["text"])
        self.assertEqual(self.client.post("/api/chat", headers=self.headers, json={
            "message": "", "location": JAMMU, "target": "nearby:casino"}).status_code, 422)

    def tap(self, button):
        return self.say("", location=button["point"], target=button["target"])

    def test_an_area_drop_off_asks_where_in_it(self):
        reply = self.say("mereko gandhi nagar jana hai")
        self.assertTrue(reply["text"].endswith("Gandhi Nagar, Jammu mein kahan jana hai? Neeche se jagah chuniye, ya koi landmark bataiye."),
                        reply["text"])
        labels = [b["label"] for b in reply["buttons"]]
        self.assertIn("District Hospital Gandhi Nagar", labels)
        self.assertEqual(labels[-1], "Bas Gandhi Nagar, Jammu")
        pickup_question = self.tap(reply["buttons"][0])
        self.assertTrue(pickup_question["ask_location"])
        self.assertIn("exact jagah", pickup_question["text"])
        self.assertTrue(pickup_question["locating_text"].endswith("abhi dekhta hoon aap kahan hain."))

    def test_a_landmark_answer_is_found_inside_the_area(self):
        self.say("mujhe gandhi nagar jana hai")
        reply = self.say("district hospital")
        self.assertEqual(reply["dropoff"]["name"], "District Hospital Gandhi Nagar")

    def test_already_there(self):
        whole = self.say("gandhinagar jana hai")["buttons"][-1]
        self.tap(whole)
        inside = self.say("", location={"lat": 32.7101, "lon": 74.8601}, target="pickup")
        self.assertIn("Aap to pehle se Gandhi Nagar, Jammu ke paas hain", inside["text"])

    def test_city_drop_offs_offer_their_best_known_places(self):
        reply = self.say("katra se jammu jana hai")
        self.assertIn("Jammu Railway Station", [b["label"] for b in reply["buttons"]])

    def test_hill_trips_get_road_advice_once(self):
        vehicles = self.say("jammu se gulmarg jana hai")
        self.assertIn("Jammu-Srinagar highway (NH-44)", vehicles["text"])
        self.assertIn("J&K Traffic Police ki advisory", vehicles["text"])
        self.assertNotIn("NH-44", self.say("cab")["text"])            # said once per trip
        self.assertNotIn("highway", self.say("jammu se bahu fort cab")["text"])   # a city trip

    def test_admins_post_todays_highway_update(self):
        admin = self.client.post("/api/login", json={"phone": "9000000001", "password": "admin-test-password", "role": "admin"})
        admin = {"Authorization": "Bearer " + admin.json()["token"]}
        self.assertEqual(self.client.put("/api/admin/highway", headers=self.headers, json={"note": "x"}).status_code, 403)
        saved = self.client.put("/api/admin/highway", headers=admin, json={"note": " Highway one-way from Jammu today "})
        self.assertEqual(saved.json(), {"note": "Highway one-way from Jammu today"})
        try:
            self.assertEqual(self.client.get("/api/admin/conditions", headers=admin).json()["highway_note"],
                             "Highway one-way from Jammu today")
            reply = self.say("jammu se gulmarg cab")
            self.assertIn("Raahi ki aaj ki jaankari: Highway one-way from Jammu today. ", reply["text"])
        finally:
            self.assertEqual(self.client.put("/api/admin/highway", headers=admin, json={"note": ""}).json(), {"note": None})

    def test_temples_near_a_named_town_need_no_location(self):
        reply = self.say("katra ke paas mandir")
        self.assertTrue(reply["text"].startswith("Katra ke paas yeh mandir hain"), reply["text"])
        self.assertNotIn("pickup", reply)


if __name__ == "__main__":
    unittest.main()
