"""The assistant understands each language, and only books after an explicit yes."""
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "data_pipeline"))

import testenv  # noqa: F401  (must precede the backend imports)
from fastapi.testclient import TestClient

import chatbot
import geocode
import localities
import places
import placesdb
from chatbot import parse, spoken
from main import app


class AddressParsingTests(unittest.TestCase):
    def test_any_words_can_be_an_address(self):
        for text, pickup, dropoff in (
            ("bharat nagar talab tillo se roop nagar jana hai", "bharat nagar talab tillo", "roop nagar"),
            ("bharat nagar to roop nagar", "bharat nagar", "roop nagar"),
            ("from house 12 gandhi lane to shastri colony", "house 12 gandhi lane", "shastri colony"),
            ("भारत नगर तालाब तिल्लो से रूप नगर जाना है", "भारत नगर तालाब तिल्लो", "रूप नगर"),
            ("بھارت نگر سے روپ نگر جانا ہے", "بھارت نگر", "روپ نگر"),
        ):
            p = parse(text)
            self.assertEqual((p.pickup, p.dropoff), (pickup, dropoff), text)

    def test_current_location_in_every_language(self):
        for text in ("mereko meri current location se pick karna hai", "from my current location", "pick me up from here",
                     "yahan se", "मेरी लोकेशन से", "मौजूदा लोकेशन से", "میری لوکیشن سے", "یہاں سے"):
            self.assertEqual(parse(text).pickup, chatbot.CURRENT, text)
        p = parse("meri location se katra jana hai")
        self.assertEqual((p.pickup, p.dropoff), (chatbot.CURRENT, "Katra"))

    def test_saying_where_you_are(self):
        self.assertEqual(parse("main bharat nagar mein hoon").pickup, "bharat nagar")
        self.assertEqual(parse("i am at roop nagar").pickup, "roop nagar")

    def test_home_as_an_address_and_a_destination(self):
        self.assertEqual(parse("mera ghar bharat nagar talab tillo mein hai").save_home, "bharat nagar talab tillo")
        self.assertEqual(parse("my home is in roop nagar").save_home, "roop nagar")
        self.assertEqual(parse("ghar jana hai").dropoff, chatbot.HOME)
        self.assertIsNone(parse("mera ghar jana hai").save_home)
        self.assertEqual(parse("apne ghar se katra").pickup, chatbot.HOME)

    def test_a_neighbourhood_is_found_in_every_script(self):
        for text in ("Roop Nagar", "रूप नगर", "روپ نگر", "roop nagar jammu"):
            self.assertEqual(localities.lookup(text)["area"], "Roop Nagar", text)

    def test_areas_are_named_in_the_riders_script(self):
        self.assertEqual(chatbot.place_label("Roop Nagar, Jammu", "hi"), "रूप नगर")
        self.assertEqual(chatbot.place_label("Roop Nagar, Jammu", "ur"), "روپ نگر")
        self.assertEqual(chatbot.place_label("Roop Nagar, Jammu", "en"), "Roop Nagar, Jammu")

    def test_extra_address_words_stay_as_the_label(self):
        found = localities.lookup("house 12 lane 3 talab tillo")
        self.assertEqual(found["area"], "Talab Tillo")
        self.assertTrue(found["approx"])
        self.assertIn("House 12", found["name"])


class WholeOfJkTests(unittest.TestCase):
    def assertFinds(self, text, expected):
        results = placesdb.search(text)
        self.assertTrue(results, text)
        self.assertIn(expected, results[0]["name"], f"{text} -> {results[0]['name']}")

    def test_famous_jammu_places_in_any_spelling_or_script(self):
        for text in ("Bawe Wali Mata", "bawe wali mata mandir", "bawe wali maat", "bave wali mata", "बावे वाली माता", "باوے والی ماتا"):
            self.assertFinds(text, "Bawe Wali")
        self.assertFinds("Ranbireshwar", "Ranbireshwar")
        self.assertFinds("Purmandal", "Purmandal")
        self.assertFinds("Sudh Mahadev", "Sudh Mahadev")

    def test_a_misheard_word_is_forgiven_when_the_rest_is_clear(self):
        self.assertFinds("talab tilon", "Talab Tillo")

    def test_villages_and_towns_across_the_state(self):
        for name in ("Kishtwar", "Gulmarg", "Hamirpur"):
            self.assertFinds(name, name)
        self.assertGreater(len(placesdb._rows), 5000)

    def test_across_the_border_is_not_included_or_served(self):
        self.assertFalse(placesdb.search("Sialkot"))
        self.assertFalse(places.in_service_area(32.49, 74.53))
        self.assertTrue(places.in_service_area(33.31, 75.77))

    def test_chatter_is_not_mistaken_for_a_place(self):
        for text in ("what is the weather", "there", "tell me a joke"):
            self.assertFalse(placesdb.search(text, strict=True), text)

    def test_fixed_holidays_only_in_live_pricing(self):
        from season import FIXED_HOLIDAYS
        self.assertIn((8, 15), FIXED_HOLIDAYS)
        self.assertNotIn((11, 2), FIXED_HOLIDAYS)


class SearchSafetyTests(unittest.TestCase):
    def test_a_result_must_contain_the_words_asked_for(self):
        words = geocode.important_words("Bharat Nagar, Jammu")
        self.assertFalse(geocode.is_genuine_match(words, "Jammu Airport, Airport Rd, Ashok Nagar, Jammu"))
        self.assertTrue(geocode.is_genuine_match(geocode.important_words("Roop Nagar Jammu"), "Roop Nagar, NH144A, Jammu"))

    def test_hindi_is_spelled_for_the_map(self):
        self.assertEqual(geocode.transliterate("भारत"), "bharat")
        self.assertEqual(geocode.transliterate("नगर"), "nagar")
        self.assertEqual(geocode.transliterate("तालाब"), "talab")
        self.assertIn("roop nagar", geocode.search_forms("रूप नगर"))

    def test_urdu_is_not_sent_for_a_guess(self):
        self.assertEqual(geocode.search_forms("بھارت نگر"), [])


class SpeechTests(unittest.TestCase):
    def test_symbols_are_said_as_words(self):
        self.assertIn("899 rupees", spoken("₹899 for 39.4 km.", "en"))
        self.assertIn("39.4 kilometres", spoken("₹899 for 39.4 km.", "en"))
        self.assertIn("899 रुपये", spoken("39.4 किमी के ₹899", "hi"))
        self.assertIn("39.4 किलोमीटर", spoken("39.4 किमी के ₹899", "hi"))
        self.assertIn("1200 rupaye", spoken("₹1,200", "hinglish"))
        self.assertNotIn("assumed", spoken("Cheaper (assumed rates).", "en"))


class ParsingTests(unittest.TestCase):
    def assertTrip(self, text, pickup, dropoff, vehicle=None, lang=None):
        p = parse(text)
        self.assertEqual((p.pickup, p.dropoff), (pickup, dropoff), text)
        self.assertEqual(p.vehicle, vehicle, text)
        if lang:
            self.assertEqual(p.lang, lang, text)

    def test_english(self):
        self.assertTrip("I want a cab from Jammu to Katra", "Jammu City", "Katra", "cab", "en")
        self.assertTrip("to Katra from Jammu", "Jammu City", "Katra")
        self.assertTrip("Gulmarg to Srinagar airport by taxi", "Gulmarg", "Srinagar Airport", "cab")

    def test_hindi(self):
        self.assertTrip("मुझे जम्मू से कटरा जाना है", "Jammu City", "Katra", None, "hi")
        self.assertTrip("श्रीनगर से गुलमर्ग के लिए टैक्सी चाहिए", "Srinagar, Lal Chowk", "Gulmarg", "cab", "hi")
        self.assertTrip("कटरा जाना है जम्मू से ऑटो", "Jammu City", "Katra", "auto", "hi")

    def test_urdu(self):
        self.assertTrip("مجھے جموں سے کٹرہ جانا ہے", "Jammu City", "Katra", None, "ur")
        self.assertTrip("سرینگر سے گلمرگ ٹیکسی چاہیے", "Srinagar, Lal Chowk", "Gulmarg", "cab", "ur")

    def test_roman_hindi_and_urdu(self):
        self.assertTrip("mujhe jammu se katra jana hai auto chahiye", "Jammu City", "Katra", "auto", "hinglish")
        self.assertTrip("srinagar se pahalgam tak gaadi", "Srinagar, Lal Chowk", "Pahalgam", "cab", "hinglish")

    def test_typos_in_place_names(self):
        self.assertTrip("from jamu to srinagr", "Jammu City", "Srinagar, Lal Chowk")

    def test_longest_place_name_wins(self):
        self.assertEqual(parse("from jammu airport to katra").pickup, "Jammu Airport")

    def test_temple_and_shrine_destinations(self):
        self.assertEqual(parse("रघुनाथ मंदिर जाना है").dropoff, "Raghunath Temple")
        self.assertEqual(parse("vaishno devi jana hai").dropoff, "Katra")
        for text in ("jammu ke mandir dikhao", "show me temples", "जम्मू के मंदिर", "جموں کے مندر"):
            self.assertTrue(parse(text).temples, text)
            self.assertFalse(parse(text).has_place, text)

    def test_yes_and_no_in_each_language(self):
        for word in ("yes", "haan", "हां", "ہاں"):
            self.assertTrue(parse(word).confirm, word)
        for word in ("no", "nahi", "नहीं", "نہیں"):
            self.assertTrue(parse(word).deny, word)
            self.assertFalse(parse(word).confirm, word)

    def test_bare_answers_keep_the_conversation_language(self):
        self.assertIsNone(parse("cab").lang)
        self.assertIsNone(parse("ok").lang)


class ConversationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)

    def setUp(self):
        phone = str(int(time.time() * 1000))[-9:]
        account = {"phone": "9" + phone, "password": "password123"}
        response = self.client.post("/api/register", json={
            **account, "name": "Chat Rider", "email": "chat@example.com"})
        self.assertEqual(response.status_code, 200, response.text)
        login = self.client.post("/api/login", json=account)
        self.headers = {"Authorization": "Bearer " + login.json()["token"]}
        time.sleep(0.01)

    def say(self, message):
        response = self.client.post("/api/chat", headers=self.headers, json={"message": message})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def active(self):
        return self.client.get("/api/rides/active", headers=self.headers).json()

    def cancel_active(self):
        ride = self.active()
        if ride:
            self.client.post(f"/api/rides/{ride['id']}/cancel", headers=self.headers)

    def test_hindi_booking_only_happens_after_yes(self):
        reply = self.say("मुझे जम्मू से कटरा कैब चाहिए")
        self.assertIn("बुक कर दूं", reply["text"])
        self.assertIsNone(self.active(), "must not book before the rider says yes")
        booked = self.say("हां")
        self.assertIn("बुक हो गया", booked["text"])
        self.assertEqual(booked["ride"]["dropoff"]["name"], "Katra")
        self.assertEqual(self.active()["id"], booked["ride"]["id"])
        self.cancel_active()

    def test_replies_name_places_in_the_riders_script(self):
        self.assertIn("कटरा", self.say("मुझे कटरा जाना है")["text"])
        self.assertNotIn("Katra", self.say("जम्मू से कटरा")["text"])

    def test_urdu_conversation_asks_for_what_is_missing(self):
        first = self.say("مجھے کٹرہ جانا ہے")["text"]
        self.assertIn("کٹرہ", first)
        self.assertIn("کہاں سے", first)
        vehicles = self.say("جموں")
        self.assertIn("کون سی گاڑی", vehicles["text"])
        self.assertTrue(vehicles["buttons"])
        self.assertIn("بک کر دوں", self.say("ٹیکسی")["text"])
        self.assertIsNone(self.active())

    def test_no_clears_the_pending_trip(self):
        self.say("jammu se katra cab")
        self.assertIn("hata diya", self.say("nahi")["text"])
        self.assertIsNone(self.active())
        self.assertNotIn("Book", self.say("haan")["text"].split(":")[0])
        self.assertIsNone(self.active())

    def test_a_new_request_never_books_on_its_own_book_word(self):
        self.say("Jammu to Katra by cab")
        reply = self.say("book a cab from Jammu to Samba")
        self.assertIn("Shall I book", reply["text"])
        self.assertIsNone(self.active())

    def test_ride_status_and_cancel_need_confirmation(self):
        self.say("Jammu to Katra by cab")
        self.say("yes")
        self.assertTrue(self.say("where is my ride")["text"])
        self.assertIn("Cancel your ride", self.say("cancel")["text"])
        self.assertIsNotNone(self.active())
        self.assertIn("cancelled", self.say("yes")["text"])
        self.assertIsNone(self.active())

    def test_lane_level_trip_like_a_local_would_say_it(self):
        reply = self.say("bharat nagar talab tillo se roop nagar jana hai")
        self.assertEqual(reply["pickup"]["area"] if "area" in reply["pickup"] else "", "Bharat Nagar, Talab Tillo")
        self.assertEqual(reply["dropoff"]["area"], "Roop Nagar")
        self.assertTrue(reply["buttons"])
        self.assertLess(abs(reply["dropoff"]["lat"] - 32.76), 0.01)

    def test_current_location_asks_the_app_then_continues(self):
        asked = self.say("meri current location se roop nagar jana hai")
        self.assertEqual(asked["need_location"], "pickup")
        self.assertEqual(asked["dropoff"]["area"], "Roop Nagar")
        response = self.client.post("/api/chat", headers=self.headers, json={
            "location": {"lat": 32.72, "lon": 74.86, "name": "Gandhi Nagar lane"}, "target": "pickup"})
        reply = response.json()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("Gandhi Nagar lane", reply["text"])
        self.assertEqual(reply["pickup"]["lat"], 32.72)
        self.assertTrue(reply["buttons"])

    def test_position_outside_jk_is_refused(self):
        self.say("meri location se katra")
        response = self.client.post("/api/chat", headers=self.headers, json={
            "location": {"lat": 28.61, "lon": 77.21, "name": "Delhi"}, "target": "pickup"})
        self.assertIn("service area", response.json()["text"])

    def test_unknown_address_never_gets_a_guessed_pin(self):
        original = geocode._fetch

        async def nothing(path, params):
            return []
        geocode._fetch = nothing
        try:
            reply = self.say("from zzqx nowhere lane to katra")
        finally:
            geocode._fetch = original
        self.assertIn("zzqx", reply["text"])
        self.assertNotIn("pickup", reply)
        self.assertTrue(any(b.get("action") == "map" for b in reply["buttons"]))

    def test_home_is_remembered_and_used(self):
        self.assertIn("don't know your home", self.say("take me home")["text"])
        self.assertIn("saved", self.say("my home is in Bharat Nagar, Talab Tillo")["text"])
        reply = self.say("ghar jana hai")
        self.assertEqual(reply["dropoff"]["area"], "Bharat Nagar, Talab Tillo")

    def test_greets_by_name_and_remembers_the_last_trip(self):
        hello = self.client.get("/api/chat/hello", headers=self.headers).json()
        self.assertIn("Chat", hello["text"])
        self.assertTrue(any(b.get("action") == "location" for b in hello["buttons"]))

    def test_only_questions_reopen_the_microphone(self):
        self.assertTrue(self.say("mujhe katra jana hai")["listen"])
        self.assertTrue(self.say("jammu")["listen"])
        self.assertNotIn("listen", self.say("cab"), "the booking question must not auto-listen")

    def test_asking_where_a_place_is(self):
        reply = self.say("bawe wali maat kaha hai")
        self.assertIn("Bawe Wali", reply["text"])
        self.assertIn("Bawe Wali", reply["dropoff"]["name"])
        self.assertEqual(reply["dropoff"]["lat"] > 32.7, True)
        vehicles = self.say("jammu")
        self.assertIn("Bawe Wali", vehicles["dropoff"]["name"])
        self.assertTrue(vehicles["buttons"])

    def test_naming_a_temple_alone_makes_it_the_destination(self):
        reply = self.say("Bawe Wali Mata")
        self.assertIn("Bawe Wali", reply["dropoff"]["name"])
        self.assertIn("pick you up", reply["text"])

    def test_cheapest_option_is_picked_when_asked(self):
        self.say("jammu se akhnoor")
        reply = self.say("sabse optimal price batao")
        self.assertIn("Sabse sasta", reply["text"])
        self.assertIn("Book kar dun", reply["text"])
        self.assertIsNone(self.active())

    def test_misheard_answer_still_finds_the_area(self):
        self.say("akhnoor jana hai")
        reply = self.say("Talab tilon se")
        self.assertTrue(reply["pickup"]["name"].startswith("Talab Tillo"), reply["pickup"]["name"])

    def test_temple_request_returns_jammu_temples(self):
        reply = self.say("mandir dikhao")
        self.assertIn("raghunath-temple", reply["temples"])
        self.assertGreaterEqual(len(reply["temples"]), 6)

    def test_place_outside_service_is_explained_not_crashed(self):
        reply = self.say("hello there")
        self.assertTrue(reply["text"])
        self.assertTrue(self.say("what is the weather")["text"])

    def test_spoken_commands_for_history_and_calling(self):
        self.assertIn("haven't taken", self.say("show my trips")["text"])
        self.assertIn("active ride", self.say("call the driver")["text"])
        self.say("Jammu to Katra by cab")
        self.say("yes")
        self.assertTrue(self.say("call the driver")["text"])
        self.assertIsNotNone(self.active(), "asking to call must not change the ride")
        self.cancel_active()

    def test_reply_says_which_language_to_speak(self):
        self.assertEqual(self.say("मुझे कटरा जाना है")["lang"], "hi")
        self.assertEqual(self.say("ok")["lang"], "hi")
        self.assertEqual(self.say("مجھے جموں جانا ہے")["lang"], "ur")

    def test_chat_needs_a_rider_account(self):
        self.assertEqual(self.client.post("/api/chat", json={"message": "hi"}).status_code, 401)


if __name__ == "__main__":
    unittest.main()
