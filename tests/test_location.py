"""Locations: exact-name search, honest labels, address details, and one trip shared by panel and assistant."""
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "data_pipeline"))

import testenv  # noqa: F401  (must precede the backend imports)
from fastapi.testclient import TestClient

import geocode
import placesdb
from main import app

JAMMU = {"lat": 32.7266, "lon": 74.857, "name": "Jammu City"}
IIT = {"lat": 32.8016, "lon": 74.8903}
_next_phone = [9810000000]


class SearchTests(unittest.TestCase):
    def first(self, text):
        return placesdb.search(text)[0]

    def test_exact_names_win_over_sound_alikes(self):
        for text in ("iit jammu", "IIT", "आईआईटी जम्मू", "indian institute of technology jammu"):
            self.assertEqual(self.first(text)["name"], "Indian Institute of Technology Jammu", text)
        # Nothing that merely sounds like "iit" comes along.
        self.assertEqual([r["name"] for r in placesdb.search("iit jammu")], ["Indian Institute of Technology Jammu"])
        for text in ("miet", "miet jammu", "model institute of engineering"):
            self.assertEqual(self.first(text)["name"], "Model Institute of Engineering and Technology", text)
        self.assertEqual(self.first("smvdu")["name"], "Shri Mata Vaishno Devi University")
        self.assertEqual(self.first("bharat nagar talab tillo")["name"], "Bharat Nagar, Talab Tillo, Jammu")
        # Misspellings still work when nothing matches exactly.
        self.assertEqual(self.first("bawe wali maat")["name"], "Bawe Wali Mata Mandir")

    def test_labels_name_the_real_neighbourhood(self):
        iit = self.first("iit jammu")
        self.assertEqual(iit["detail"], "University · near Jagti")
        self.assertAlmostEqual(iit["lat"], 32.8016, places=3)
        cantonment = self.first("nagrota cantonment")
        self.assertNotIn("Bahu Fort", cantonment["detail"])
        self.assertIn("near Jagti", cantonment["detail"])
        self.assertEqual(placesdb.area_label(32.9408, 74.9566, "x"), placesdb.area_label(32.9408, 74.9566, "x"))
        far = placesdb.area_label(32.94, 74.954, "Shri Mata Vaishno Devi University")
        self.assertTrue(far.startswith("near ") or " km from " in far, far)


class ApiTests(unittest.TestCase):
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
            self.client.post("/api/register", json={**account, "name": "Loc Rider", "email": "l@example.com"})
        self.headers = {"Authorization": "Bearer " + self.client.post("/api/login", json=account).json()["token"]}
        patcher = mock.patch.object(geocode, "search", mock.AsyncMock(return_value=[]))
        self.osm = patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        active = self.client.get("/api/rides/active", headers=self.headers).json()
        if active:
            self.client.post(f"/api/rides/{active['id']}/cancel", headers=self.headers)

    def say(self, message, **extra):
        response = self.client.post("/api/chat", headers=self.headers, json={"message": message, **extra})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def trip(self, pickup=None, dropoff=None):
        response = self.client.post("/api/chat/trip", headers=self.headers, json={"pickup": pickup, "dropoff": dropoff})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_address_search_asks_openstreetmap_only_without_an_exact_match(self):
        found = self.client.get("/api/address?q=iit jammu", headers=self.headers).json()
        self.assertEqual(found[0]["name"], "Indian Institute of Technology Jammu")
        self.osm.assert_not_called()
        self.osm.return_value = [{"lat": 32.75, "lon": 74.85, "name": "Some New College", "detail": "OSM", "approx": False}]
        found = self.client.get("/api/address?q=some new college", headers=self.headers).json()
        self.osm.assert_called_once()
        self.assertIn("Some New College", [r["name"] for r in found])

    def test_house_number_travels_with_the_ride_to_the_driver(self):
        body = {"pickup": {**JAMMU, "details": " House 63, Sector E "},
                "dropoff": {**IIT, "name": "Indian Institute of Technology Jammu", "details": "Main gate"},
                "vehicle": "cab"}
        quote = self.client.post("/api/quote", headers=self.headers, json=body).json()
        self.assertEqual(quote["pickup"]["details"], "House 63, Sector E")
        ride = self.client.post("/api/rides", headers=self.headers, json=body).json()
        self.assertEqual(ride["pickup"]["details"], "House 63, Sector E")
        self.assertEqual(ride["dropoff"]["details"], "Main gate")
        self.assertEqual((ride["dropoff"]["lat"], ride["dropoff"]["lon"]), (IIT["lat"], IIT["lon"]))
        # No details: nothing extra is stored.
        plain = self.client.post("/api/quote", headers=self.headers, json={"pickup": JAMMU, "dropoff": {**IIT, "name": "IIT"}}).json()
        self.assertNotIn("details", plain["pickup"])

    def test_a_spoken_yes_books_the_trip_set_in_the_panel_not_an_older_one(self):
        self.say("jammu se katra cab")                         # the assistant offers Jammu to Katra
        self.trip(JAMMU, {**IIT, "name": "Indian Institute of Technology Jammu"})
        self.assertNotIn("ride", self.say("haan"))             # the old offer is gone
        offer = self.say("cab")
        self.assertIn("Indian Institute of Technology Jammu", offer["text"])
        booked = self.say("haan")
        self.assertEqual(booked["ride"]["dropoff"]["name"], "Indian Institute of Technology Jammu")
        self.assertEqual((booked["ride"]["dropoff"]["lat"], booked["ride"]["dropoff"]["lon"]), (IIT["lat"], IIT["lon"]))

    def test_an_unknown_spoken_place_asks_for_typing_then_confirms(self):
        reply = self.say("mujhe qwzxy vihar jana hai")
        self.assertEqual(reply["type_location"], "dropoff")
        self.assertIn("neeche type kijiye", reply["text"])
        # Typed into the panel: the assistant confirms and carries on.
        answer = self.trip(None, {**IIT, "name": "Indian Institute of Technology Jammu"})
        self.assertTrue(answer["reply"]["text"].startswith("Theek hai, location confirm ho gayi."), answer["reply"]["text"])

    def test_typing_the_place_to_the_assistant_also_confirms(self):
        self.say("mujhe qwzxy vihar jana hai")
        reply = self.say("iit jammu")
        self.assertTrue(reply["text"].startswith("Theek hai, location confirm ho gayi."), reply["text"])
        self.assertEqual(reply["dropoff"]["name"], "Indian Institute of Technology Jammu")

    def test_trip_sync_without_a_pending_question_is_silent(self):
        self.assertEqual(self.trip(JAMMU, None), {"synced": True})


if __name__ == "__main__":
    unittest.main()
