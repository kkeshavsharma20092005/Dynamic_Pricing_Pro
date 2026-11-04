"""End-to-end ride flows against the real app, using a throwaway database."""
import sqlite3
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "data_pipeline"))

import testenv  # noqa: F401  (must precede the backend imports)
from fastapi.testclient import TestClient

import appdb
import business
import fares
import places
import rides
import routing
from main import app

JAMMU = {"lat": 32.7266, "lon": 74.8570, "name": "Jammu City"}
GANDHI_NAGAR = {"lat": 32.7100, "lon": 74.8600, "name": "Gandhi Nagar"}
SRINAGAR = {"lat": 34.0700, "lon": 74.8100, "name": "Lal Chowk"}
DELHI = {"lat": 28.6139, "lon": 77.2090, "name": "Delhi"}
_next_phone = [9100000000]


def wait_for(fetch, condition, seconds=70):
    deadline = time.time() + seconds
    while time.time() < deadline:
        value = fetch()
        if condition(value):
            return value
        time.sleep(0.25)
    raise AssertionError(f"Timed out; last value: {value}")


class RideAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.client.__enter__()
        admin = cls.client.post("/api/login", json={"phone": "9000000001", "password": "admin-test-password", "role": "admin"})
        cls.admin = {"Authorization": "Bearer " + admin.json()["token"]}

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)

    def setUp(self):
        self.clear_conditions()

    def clear_conditions(self):
        for region, temperature in (("JMU", 24), ("KSH", 12), ("HIL", 15)):
            self.set_conditions(region, temperature=temperature)
        self.client.put("/api/admin/caps", headers=self.admin, json={"normal": 1.3, "hardship": 1.15})
        appdb.set_setting("rival_rates", fares.DEFAULT_RIVAL_RATES)

    def set_conditions(self, region, temperature=20, precipitation=0, weather="Clear", closed=False, hour=14, pilgrim=0.0):
        response = self.client.put(f"/api/admin/conditions/{region}", headers=self.admin, json={
            "temperature": temperature, "precipitation": precipitation, "weather_condition": weather,
            "road_closed": closed, "hour_override": hour, "pilgrim_override": pilgrim})
        self.assertEqual(response.status_code, 200, response.text)

    def set_rates(self, rival, vehicle, base, per_km):
        response = self.client.put(f"/api/admin/rival-rates/{rival}/{vehicle}", headers=self.admin,
                                   json={"base": base, "per_km": per_km})
        self.assertEqual(response.status_code, 200, response.text)

    def account(self, role="rider", vehicle=None):
        _next_phone[0] += 1
        response = self.client.post("/api/register", json={
            "phone": str(_next_phone[0]), "name": f"Test {role}", "password": "password123",
            "role": role, "vehicle": vehicle})
        self.assertEqual(response.status_code, 200, response.text)
        return {"Authorization": "Bearer " + response.json()["token"]}

    def quote(self, headers, pickup=JAMMU, dropoff=GANDHI_NAGAR):
        return self.client.post("/api/quote", headers=headers, json={"pickup": pickup, "dropoff": dropoff})

    # ---------------------------------------------------------------- business model
    def book(self, rider, vehicle="cab"):
        response = self.client.post("/api/rides", headers=rider, json={
            "pickup": JAMMU, "dropoff": GANDHI_NAGAR, "vehicle": vehicle})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_business_numbers_are_admin_only(self):
        rider = self.account()
        ride = self.book(rider)
        try:
            self.assertNotIn("business", ride["quote"])
            self.assertEqual(self.client.get("/api/admin/business", headers=rider).status_code, 403)
            report = self.client.get("/api/admin/business", headers=self.admin).json()
            row = next(r for r in report["rides"] if r["id"] == ride["id"])
            econ = row["economics"]
            self.assertFalse(row["counted"])          # not completed, so not in the profit totals
            self.assertAlmostEqual(econ["fare"], ride["fare"])
            self.assertAlmostEqual(econ["gst"] + econ["commission"] + econ["driver_payout"], econ["fare"], places=1)
            self.assertAlmostEqual(econ["profit"], econ["commission"] - econ["platform_costs"], places=1)
            self.assertIn("cab", report["sample_10km"])
        finally:
            self.client.post(f"/api/rides/{ride['id']}/cancel", headers=rider)

    def test_new_business_rates_apply_to_new_rides_only(self):
        rider = self.account()
        before = self.book(rider)
        self.client.post(f"/api/rides/{before['id']}/cancel", headers=rider)
        try:
            bad = self.client.put("/api/admin/business", headers=self.admin, json={"commission_pct": {"cab": 90}})
            self.assertEqual(bad.status_code, 422)
            ok = self.client.put("/api/admin/business", headers=self.admin, json={"commission_pct": {"cab": 30}})
            self.assertEqual(ok.status_code, 200, ok.text)
            after = self.book(rider)
            self.client.post(f"/api/rides/{after['id']}/cancel", headers=rider)
            rows = {r["id"]: r for r in self.client.get("/api/admin/business", headers=self.admin).json()["rides"]}
            self.assertEqual(rows[before["id"]]["economics"]["commission_pct"], 20.0)
            self.assertEqual(rows[after["id"]]["economics"]["commission_pct"], 30.0)
        finally:
            appdb.set_setting("business_model", business.DEFAULT_ASSUMPTIONS)

    # ---------------------------------------------------------------- accounts
    def test_wrong_password_and_bad_phone_are_rejected(self):
        self.assertEqual(self.client.post("/api/login", json={"phone": "9000000001", "password": "nope", "role": "admin"}).status_code, 401)
        bad = self.client.post("/api/register", json={"phone": "123", "name": "Xy", "password": "password123"})
        self.assertEqual(bad.status_code, 422)

    def test_one_number_can_hold_separate_rider_and_driver_accounts(self):
        body = {"phone": "9222222222", "name": "Both Roles", "password": "password123"}
        rider = self.client.post("/api/register", json={**body, "role": "rider"})
        driver = self.client.post("/api/register", json={**body, "role": "driver", "vehicle": "cab", "password": "different456"})
        self.assertEqual((rider.status_code, driver.status_code), (200, 200), driver.text)
        self.assertNotEqual(rider.json()["user"]["id"], driver.json()["user"]["id"])
        self.assertEqual(self.client.post("/api/register", json={**body, "role": "rider"}).status_code, 409)

        login = lambda role, pw: self.client.post("/api/login", json={"phone": body["phone"], "password": pw, "role": role})
        self.assertEqual(login("driver", "different456").json()["user"]["role"], "driver")
        self.assertEqual(login("driver", "password123").status_code, 401)
        self.assertEqual(login("admin", "password123").status_code, 401)

    def test_nobody_can_register_as_admin(self):
        response = self.client.post("/api/register", json={
            "phone": "9111111111", "name": "Sneaky", "password": "password123", "role": "admin"})
        self.assertEqual(response.status_code, 422)

    def test_passwords_are_not_stored_in_plain_text(self):
        with appdb.connect() as conn:
            rows = conn.execute("SELECT password_hash FROM users").fetchall()
        self.assertTrue(rows)
        self.assertFalse(any("password" in r["password_hash"] for r in rows))

    def test_endpoints_need_login(self):
        self.assertEqual(self.client.post("/api/quote", json={"pickup": JAMMU, "dropoff": GANDHI_NAGAR}).status_code, 401)
        self.assertEqual(self.client.get("/api/admin/overview").status_code, 401)

    def test_rider_cannot_use_admin_endpoints(self):
        self.assertEqual(self.client.get("/api/admin/overview", headers=self.account()).status_code, 403)

    # ---------------------------------------------------------------- quotes
    def test_quote_outside_jk_is_rejected(self):
        self.assertEqual(self.quote(self.account(), dropoff=DELHI).status_code, 422)

    def test_jammu_to_srinagar_estimate_is_realistic(self):
        route = places.plan_route(JAMMU["lat"], JAMMU["lon"], SRINAGAR["lat"], SRINAGAR["lon"])
        self.assertGreater(route["km"], 220)
        self.assertLess(route["km"], 320)
        self.assertIn("HIL", route["regions"])

    def test_long_trip_only_offers_long_distance_vehicles(self):
        response = self.quote(self.account(), dropoff=SRINAGAR)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual({o["vehicle"] for o in response.json()["options"]}, {"cab"})

    def test_closed_highway_blocks_jammu_to_srinagar_but_not_local_trips(self):
        rider = self.account()
        self.set_conditions("HIL", temperature=2, precipitation=9, weather="Stormy", closed=True)
        self.assertEqual(self.quote(rider, dropoff=SRINAGAR).status_code, 409)
        self.assertEqual(self.quote(rider).status_code, 200)

    def test_rush_hour_costs_more_and_explains_why(self):
        rider = self.account()
        self.set_conditions("JMU", temperature=24, hour=14)
        quiet = self.quote(rider).json()["options"][0]
        self.set_conditions("JMU", temperature=24, hour=18)
        rush = self.quote(rider).json()["options"][0]
        self.assertGreater(rush["fare"], quiet["fare"])
        self.assertIn("Rush hour", [r["factor"] for r in rush["reasons"]])

    def test_fair_cap_limits_the_fare_during_hardship(self):
        rider = self.account()
        self.set_conditions("KSH", temperature=-2, precipitation=8, weather="Snowy", hour=18, pilgrim=0.0)
        pickup, dropoff = {"lat": 34.07, "lon": 74.81}, {"lat": 34.13, "lon": 74.84}
        for option in self.quote(rider, pickup, dropoff).json()["options"]:
            self.assertLessEqual(option["multiplier"], 1.15)
            if option["model_multiplier"] > 1.15:
                self.assertTrue(option["fair_capped"])
                self.assertGreater(option["saved_by_cap"], 0)

    def test_rivals_are_labelled_ranges_only_on_local_trips(self):
        rider = self.account()
        local = {o["vehicle"]: o for o in self.quote(rider).json()["options"]}
        rival = local["cab"]["rivals"][0]
        self.assertLess(rival["low"], rival["high"])
        self.assertEqual(local["erickshaw"]["rivals"], [])
        far = self.quote(rider, dropoff=SRINAGAR).json()["options"][0]
        self.assertEqual(far["rivals"], [])
        self.assertFalse(far["recommendation"]["confident"])

    def test_rival_rates_move_the_recommendation_and_the_fare(self):
        rider = self.account()
        self.set_rates("rapido", "cab", 1, 1)
        cheap = {o["vehicle"]: o for o in self.quote(rider).json()["options"]}["cab"]
        self.assertEqual(cheap["recommendation"]["pick"], "rapido")
        self.set_rates("rapido", "cab", 500, 100)
        self.set_rates("uber", "cab", 500, 100)
        dear = {o["vehicle"]: o for o in self.quote(rider).json()["options"]}["cab"]
        self.assertEqual(dear["recommendation"]["pick"], "raahi")
        self.assertTrue(dear["recommendation"]["confident"])
        self.assertGreater(dear["fare"], cheap["fare"])

    # ---------------------------------------------------------------- booking
    def test_client_cannot_choose_its_own_fare(self):
        rider = self.account()
        real = self.quote(rider).json()["options"][0]
        ride = self.client.post("/api/rides", headers=rider, json={
            "pickup": JAMMU, "dropoff": GANDHI_NAGAR, "vehicle": real["vehicle"], "fare": 1}).json()
        self.assertEqual(ride["fare"], real["fare"])
        self.client.post(f"/api/rides/{ride['id']}/cancel", headers=rider)

    def test_simulated_trip_runs_to_completion_with_chat(self):
        rider = self.account()
        vehicle = self.quote(rider).json()["options"][0]["vehicle"]
        ride = self.client.post("/api/rides", headers=rider, json={
            "pickup": JAMMU, "dropoff": GANDHI_NAGAR, "vehicle": vehicle}).json()
        self.assertEqual(ride["status"], "searching")
        self.assertEqual(self.client.post("/api/rides", headers=rider, json={
            "pickup": JAMMU, "dropoff": GANDHI_NAGAR, "vehicle": vehicle}).status_code, 409)

        ride_url = f"/api/rides/{ride['id']}"
        get_active = lambda: self.client.get("/api/rides/active", headers=rider).json()
        accepted = wait_for(get_active, lambda r: r and r["driver"])
        self.assertTrue(accepted["driver"]["simulated"])

        sent = self.client.post(ride_url + "/messages", headers=rider, json={"body": "Main gate par hoon"})
        self.assertEqual(sent.status_code, 200, sent.text)
        wait_for(lambda: self.client.get(ride_url + "/messages", headers=rider).json(), lambda m: len(m) == 2)

        wait_for(get_active, lambda r: r is None)
        history = self.client.get("/api/rides", headers=rider).json()
        self.assertEqual(history[0]["status"], "completed")

    def test_real_driver_gets_first_offer_and_runs_the_trip(self):
        rider, driver = self.account(), self.account("driver", "cab")
        online = self.client.post("/api/driver/state", headers=driver, json={"online": True, "lat": 32.72, "lon": 74.86})
        self.assertEqual(online.status_code, 200, online.text)
        ride = self.client.post("/api/rides", headers=rider, json={
            "pickup": JAMMU, "dropoff": GANDHI_NAGAR, "vehicle": "cab"}).json()
        url = f"/api/rides/{ride['id']}"

        # Another driver must not be able to take someone else's offer.
        outsider = self.account("driver", "cab")
        self.assertEqual(self.client.post(url + "/accept", headers=outsider).status_code, 409)

        accepted = wait_for(lambda: self.client.post(url + "/accept", headers=driver), lambda r: r.status_code == 200, 5).json()
        self.assertFalse(accepted["driver"]["simulated"])
        seen_by_rider = self.client.get("/api/rides/active", headers=rider).json()
        self.assertTrue(seen_by_rider["driver"]["phone"])

        self.assertEqual(self.client.post(url + "/advance/completed", headers=driver).status_code, 409)
        for step in ("arrived", "in_progress", "completed"):
            self.assertEqual(self.client.post(f"{url}/advance/{step}", headers=driver).status_code, 200)
        final = self.client.get("/api/rides", headers=rider).json()[0]
        self.assertEqual(final["status"], "completed")
        self.assertIsNone(final["driver"]["phone"])
        self.client.post("/api/driver/state", headers=driver, json={"online": False})

    def test_driver_goes_offline_when_the_connection_drops(self):
        driver = self.account("driver", "cab")
        token = driver["Authorization"].removeprefix("Bearer ")
        driver_id = self.client.get("/api/me", headers=driver).json()["id"]
        with self.client.websocket_connect(f"/api/ws?token={token}"):
            self.client.post("/api/driver/state", headers=driver, json={"online": True, "lat": 32.72, "lon": 74.86})
            self.assertIn(driver_id, rides.hub.drivers)
        wait_for(lambda: driver_id in rides.hub.drivers, lambda online: not online, 5)

    def test_only_participants_can_read_a_ride_chat(self):
        rider, stranger = self.account(), self.account()
        ride = self.client.post("/api/rides", headers=rider, json={
            "pickup": JAMMU, "dropoff": GANDHI_NAGAR, "vehicle": "cab"}).json()
        self.assertEqual(self.client.get(f"/api/rides/{ride['id']}/messages", headers=stranger).status_code, 404)
        self.assertEqual(self.client.post(f"/api/rides/{ride['id']}/cancel", headers=stranger).status_code, 404)
        self.client.post(f"/api/rides/{ride['id']}/cancel", headers=rider)


@unittest.skipIf(appdb.USE_POSTGRES, "upgrades an old SQLite file; PostgreSQL databases start new")
class MigrationTests(unittest.TestCase):
    def test_old_one_account_per_number_database_is_upgraded(self):
        original = appdb.DB_PATH
        appdb.DB_PATH = original + ".old"
        try:
            conn = sqlite3.connect(appdb.DB_PATH)
            conn.executescript("""CREATE TABLE users (id INTEGER PRIMARY KEY, phone TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL, role TEXT NOT NULL, vehicle TEXT, password_hash TEXT NOT NULL,
                salt TEXT NOT NULL, created_at REAL NOT NULL);
                INSERT INTO users VALUES (1, '9333333333', 'Old', 'rider', NULL, 'h', '00', 1.0);""")
            conn.close()
            appdb.init_db()
            appdb.create_user("9333333333", "Old Driver", "driver", "password123", "cab")
            self.assertEqual(appdb.get_user(1)["name"], "Old")
        finally:
            appdb.DB_PATH = original


class FareTests(unittest.TestCase):
    def test_every_vehicle_has_a_fare_card(self):
        from config import PRODUCTS
        self.assertTrue({s["vehicle"] for s in PRODUCTS.values()} <= set(fares.VEHICLES))

    def test_every_town_is_inside_the_service_area(self):
        for place in places.BY_NAME.values():
            self.assertTrue(places.in_service_area(place["lat"], place["lon"]), place["name"])

    def test_sialkot_and_delhi_are_outside_the_service_area(self):
        self.assertFalse(places.in_service_area(32.49, 74.53))
        self.assertFalse(places.in_service_area(28.61, 77.21))


class BusinessModelTests(unittest.TestCase):
    def test_every_rupee_of_the_fare_is_accounted_for(self):
        e = business.ride_economics(105, 10, "cab", 100, business.DEFAULT_ASSUMPTIONS)
        self.assertAlmostEqual(e["gst"], 5.0)                 # 5% GST inside a ₹105 fare
        self.assertAlmostEqual(e["commission"], 20.0)         # 20% of the ₹100 net fare
        self.assertAlmostEqual(e["driver_payout"], 80.0)
        self.assertAlmostEqual(e["driver_fuel"], (10 + 1.5) * 7.5)
        self.assertAlmostEqual(e["profit"], 20 - 105 * 0.02 - 2 - 3)
        self.assertAlmostEqual(e["pricing_effect"], 5.0)

    def test_out_of_range_assumptions_are_refused(self):
        with self.assertRaises(ValueError):
            business.validate({"gst_pct": 40})
        with self.assertRaises(ValueError):
            business.validate({"fuel_per_km": {"rocket": 3}})


class RoadRoutingTests(unittest.TestCase):
    def setUp(self):
        routing._cache.clear()
        routing._down_until = 0.0
        patcher = mock.patch.object(routing, "ENABLED", True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_route_follows_the_road_when_routing_answers(self):
        answer = mock.Mock(status_code=200)
        answer.json.return_value = {"code": "Ok", "routes": [{"distance": 7200.0, "duration": 600.0, "geometry": {
            "coordinates": [[74.857, 32.727], [74.850, 32.715], [74.845, 32.700], [74.838, 32.690], [74.837, 32.689]]}}]}
        with mock.patch.object(routing.httpx, "get", return_value=answer):
            route = places.plan_route(32.7266, 74.8570, 32.6891, 74.8374)
        self.assertTrue(route["routed"])
        self.assertEqual(route["km"], 7.2)
        self.assertEqual(route["minutes"], 12)                # 10 min of free-flow driving, plus traffic
        self.assertEqual(route["path"][0], [32.7266, 74.8570])  # starts at the pin, not the road
        self.assertEqual(len(route["path"]), 7)

    def test_falls_back_to_the_estimate_when_routing_fails(self):
        with mock.patch.object(routing.httpx, "get", side_effect=routing.httpx.ConnectError("down")) as get:
            first = places.plan_route(32.7266, 74.8570, 32.6891, 74.8374)
            places.plan_route(32.7266, 74.8570, 34.07, 74.81)
        self.assertFalse(first["routed"])
        self.assertGreater(first["km"], 0)
        self.assertEqual(get.call_count, 1)                   # backs off instead of waiting again


if __name__ == "__main__":
    unittest.main()
