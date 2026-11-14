"""End-to-end ride flows against the real app, using a throwaway database."""
import re
import sqlite3
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

import mailer

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
import sms
from main import app

JAMMU = {"lat": 32.7266, "lon": 74.8570, "name": "Jammu City"}
GANDHI_NAGAR = {"lat": 32.7100, "lon": 74.8600, "name": "Gandhi Nagar"}
SRINAGAR = {"lat": 34.0700, "lon": 74.8100, "name": "Lal Chowk"}
DELHI = {"lat": 28.6139, "lon": 77.2090, "name": "Delhi"}
_next_phone = [9100000000]
_next_plate = [1000]
PHOTO = "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAP8="


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

    def account(self, role="rider", vehicle=None, email="test@example.com"):
        _next_phone[0] += 1
        phone = str(_next_phone[0])
        response = self.client.post("/api/register", json={
            "phone": phone, "name": f"Test {role}", "password": "password123",
            "role": role, "vehicle": vehicle, "email": email})
        self.assertEqual(response.status_code, 200, response.text)
        return self.login(phone, "password123", role)

    def login(self, phone, password, role="rider"):
        response = self.client.post("/api/login", json={"phone": phone, "password": password, "role": role})
        self.assertEqual(response.status_code, 200, response.text)
        return {"Authorization": "Bearer " + response.json()["token"]}

    def emailed_code(self, phone, role="rider"):
        """Ask for a reset code and return it, reading the email the app would send."""
        sent = []
        with mock.patch.object(mailer, "send", lambda to, subject, body: sent.append((to, body))):
            response = self.client.post("/api/password/forgot", json={"phone": phone, "role": role})
        self.assertEqual(response.status_code, 200, response.text)
        return sent

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
        bad = self.client.post("/api/register", json={"phone": "123", "name": "Xy", "password": "password123", "email": "a@b.co"})
        self.assertEqual(bad.status_code, 422)

    def test_signing_up_does_not_log_in(self):
        response = self.client.post("/api/register", json={
            "phone": "9444444441", "name": "New Rider", "password": "password123", "email": "New.Rider@Gmail.com"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn("token", response.json())
        self.assertEqual(response.json()["user"]["email"], "new.rider@gmail.com")
        self.assertEqual(self.client.get("/api/me", headers=self.login("9444444441", "password123"))
                         .json()["phone"], "9444444441")

    def test_sign_up_needs_a_valid_email(self):
        body = {"phone": "9444444442", "name": "No Mail", "password": "password123"}
        self.assertEqual(self.client.post("/api/register", json=body).status_code, 422)
        self.assertEqual(self.client.post("/api/register", json={**body, "email": "not-an-email"}).status_code, 422)

    def test_forgot_password_emails_a_code_that_sets_a_new_password(self):
        self.client.post("/api/register", json={
            "phone": "9444444443", "name": "Forgetful", "password": "password123", "email": "forgetful@gmail.com"})
        old_session = self.login("9444444443", "password123")
        sent = self.emailed_code("9444444443")
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0][0], "forgetful@gmail.com")
        code = re.search(r"\b(\d{6})\b", sent[0][1]).group(1)

        wrong = "000000" if code != "000000" else "111111"
        reset = lambda c: self.client.post("/api/password/reset", json={
            "phone": "9444444443", "code": c, "password": "brand-new-pass"})
        self.assertEqual(reset(wrong).status_code, 400)
        self.assertEqual(reset(code).status_code, 200)
        self.assertEqual(reset(code).status_code, 400, "a code works only once")

        self.assertEqual(self.client.post("/api/login", json={"phone": "9444444443", "password": "password123"}).status_code, 401)
        self.login("9444444443", "brand-new-pass")
        self.assertEqual(self.client.get("/api/me", headers=old_session).status_code, 401,
                         "changing the password signs out older sessions")

    def test_reset_code_is_locked_after_five_wrong_guesses(self):
        self.client.post("/api/register", json={
            "phone": "9444444444", "name": "Guessed", "password": "password123", "email": "g@example.com"})
        code = re.search(r"\b(\d{6})\b", self.emailed_code("9444444444")[0][1]).group(1)
        wrong = "000000" if code != "000000" else "111111"
        for _ in range(5):
            self.client.post("/api/password/reset", json={"phone": "9444444444", "code": wrong, "password": "whatever123"})
        response = self.client.post("/api/password/reset", json={"phone": "9444444444", "code": code, "password": "whatever123"})
        self.assertEqual(response.status_code, 400)

    def test_forgot_password_does_not_reveal_who_has_an_account(self):
        unknown = self.emailed_code("9444444449")
        self.assertEqual(unknown, [])
        known = self.client.post("/api/password/forgot", json={"phone": "9444444449", "role": "rider"})
        self.client.post("/api/register", json={
            "phone": "9444444445", "name": "Known", "password": "password123", "email": "k@example.com"})
        with mock.patch.object(mailer, "send", lambda *a: None):
            exists = self.client.post("/api/password/forgot", json={"phone": "9444444445", "role": "rider"})
        self.assertEqual(known.json(), exists.json())

    def test_admin_login_follows_admin_phone_and_password_settings(self):
        with mock.patch.dict("os.environ", {"ADMIN_PHONE": "6000000009", "ADMIN_PASSWORD": "moved-pass-1"}):
            appdb.ensure_admin()
            self.login("6000000009", "moved-pass-1", "admin")
            self.assertEqual(self.client.post("/api/login", json={
                "phone": "9000000001", "password": "admin-test-password", "role": "admin"}).status_code, 401)
        appdb.ensure_admin()   # back to the test settings
        # The password change signed out the shared admin session, so sign in again.
        type(self).admin = self.login("9000000001", "admin-test-password", "admin")

    def test_admin_password_cannot_be_reset_by_email(self):
        self.assertEqual(self.emailed_code("9000000001", "admin"), [])

    def test_one_number_can_hold_separate_rider_and_driver_accounts(self):
        body = {"phone": "9222222222", "name": "Both Roles", "password": "password123", "email": "both@example.com"}
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
            "phone": "9111111111", "name": "Sneaky", "password": "password123", "role": "admin", "email": "s@example.com"})
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
        self.assertRegex(accepted["driver"]["plate"], r"^JK\d{2} [A-Z]{2} \d{4}$")

        sent = self.client.post(ride_url + "/messages", headers=rider, json={"body": "Main gate par hoon"})
        self.assertEqual(sent.status_code, 200, sent.text)
        wait_for(lambda: self.client.get(ride_url + "/messages", headers=rider).json(), lambda m: len(m) == 2)

        wait_for(get_active, lambda r: r is None)
        history = self.client.get("/api/rides", headers=rider).json()
        self.assertEqual(history[0]["status"], "completed")

    def test_real_driver_gets_first_offer_and_runs_the_trip(self):
        rider, driver = self.account(), self.driver()
        online = self.client.post("/api/driver/state", headers=driver, json={"online": True, "lat": 32.72, "lon": 74.86})
        self.assertEqual(online.status_code, 200, online.text)
        ride = self.client.post("/api/rides", headers=rider, json={
            "pickup": JAMMU, "dropoff": GANDHI_NAGAR, "vehicle": "cab"}).json()
        url = f"/api/rides/{ride['id']}"

        # Another driver must not be able to take someone else's offer, and an unchecked one
        # cannot accept anything at all.
        outsider = self.driver()
        self.assertEqual(self.client.post(url + "/accept", headers=outsider).status_code, 409)
        unchecked = self.account("driver", "cab")
        self.assertEqual(self.client.post(url + "/accept", headers=unchecked).status_code, 403)

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

    # ---------------------------------------------------------------- Women Raahi
    def gendered(self, gender, role="rider", vehicle=None):
        headers = self.account(role, vehicle)
        response = self.client.post("/api/me/gender", headers=headers, json={"gender": gender})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["gender"], gender)
        return headers

    def send_kyc(self, headers, **changes):
        _next_plate[0] += 1
        return self.client.post("/api/kyc", headers=headers, json={
            "document": "aadhaar", "id_image": PHOTO, "selfie": PHOTO, "licence_image": PHOTO, "rc_image": PHOTO,
            "plate": f"jk02-ab {_next_plate[0]}", "consent": True, **changes})

    def pending_check(self, headers):
        phone = self.client.get("/api/me", headers=headers).json()["phone"]
        pending = self.client.get("/api/admin/verifications", headers=self.admin).json()["pending"]
        return next(v for v in pending if v["phone"] == phone)

    def review(self, headers, approve=True, gender=None, note=""):
        check = self.pending_check(headers)
        return self.client.post(f"/api/admin/verifications/{check['id']}", headers=self.admin,
                                json={"approve": approve, "gender": gender, "note": note})

    def verify(self, headers, gender):
        sent = self.send_kyc(headers)
        self.assertEqual(sent.status_code, 200, sent.text)
        self.assertEqual(sent.json()["kyc"], "pending")
        approved = self.review(headers, True, gender)
        self.assertEqual(approved.status_code, 200, approved.text)
        return headers

    def driver(self, vehicle="cab", gender="male"):
        return self.verify(self.account("driver", vehicle), gender)

    def woman_rider(self):
        return self.verify(self.gendered("female"), "female")

    def test_gender_is_asked_once_and_cannot_be_switched(self):
        rider = self.account()
        self.assertIsNone(self.client.get("/api/me", headers=rider).json()["gender"])
        self.assertEqual(self.client.post("/api/me/gender", headers=rider, json={"gender": "robot"}).status_code, 422)
        self.assertEqual(self.client.post("/api/me/gender", headers=rider, json={"gender": "unspecified"}).status_code, 200)
        again = self.client.post("/api/me/gender", headers=rider, json={"gender": "female"})
        self.assertEqual(again.status_code, 409)
        self.assertEqual(self.client.get("/api/me", headers=rider).json()["gender"], "unspecified")
        self.assertEqual(self.client.post("/api/me/gender", headers=self.admin, json={"gender": "male"}).status_code, 403)

    def test_only_women_can_book_women_raahi(self):
        for gender in (None, "male", "other", "unspecified"):
            rider = self.gendered(gender) if gender else self.account()
            response = self.client.post("/api/rides", headers=rider, json={
                "pickup": JAMMU, "dropoff": GANDHI_NAGAR, "vehicle": "cab", "women_only": True})
            self.assertEqual(response.status_code, 403, gender)

    def test_women_raahi_skips_men_and_goes_to_a_woman_driver(self):
        rider = self.woman_rider()
        man = self.driver(gender="male")
        woman = self.driver(gender="female")
        for driver in (man, woman):
            online = self.client.post("/api/driver/state", headers=driver, json={"online": True, "lat": 32.72, "lon": 74.86})
            self.assertEqual(online.status_code, 200, online.text)
        try:
            ride = self.client.post("/api/rides", headers=rider, json={
                "pickup": JAMMU, "dropoff": GANDHI_NAGAR, "vehicle": "cab", "women_only": True}).json()
            self.assertTrue(ride["women_only"])
            url = f"/api/rides/{ride['id']}"
            accepted = wait_for(lambda: self.client.post(url + "/accept", headers=woman), lambda r: r.status_code == 200, 5).json()
            self.assertTrue(accepted["women_only"])
            self.assertEqual(self.client.post(url + "/accept", headers=man).status_code, 409)
            self.client.post(url + "/cancel", headers=rider)
        finally:
            for driver in (man, woman):
                self.client.post("/api/driver/state", headers=driver, json={"online": False})

    def test_women_raahi_demo_driver_is_a_woman(self):
        rider = self.woman_rider()
        man = self.driver(gender="male")
        self.client.post("/api/driver/state", headers=man, json={"online": True, "lat": 32.72, "lon": 74.86})
        try:
            ride = self.client.post("/api/rides", headers=rider, json={
                "pickup": JAMMU, "dropoff": GANDHI_NAGAR, "vehicle": "cab", "women_only": True}).json()
            accepted = wait_for(lambda: self.client.get("/api/rides/active", headers=rider).json(),
                                lambda r: r and r["driver"], 10)
            self.assertTrue(accepted["driver"]["simulated"])
            self.assertIn(accepted["driver"]["name"], rides.SIM_WOMEN_NAMES)
            self.client.post(f"/api/rides/{ride['id']}/cancel", headers=rider)
        finally:
            self.client.post("/api/driver/state", headers=man, json={"online": False})

    def test_normal_rides_are_not_women_only(self):
        rider = self.gendered("female")
        ride = self.book(rider)
        self.assertFalse(ride["women_only"])
        self.client.post(f"/api/rides/{ride['id']}/cancel", headers=rider)

    # ---------------------------------------------------------------- ID checks
    def test_unverified_driver_cannot_go_online(self):
        driver = self.account("driver", "cab")
        state = {"online": True, "lat": 32.72, "lon": 74.86}
        self.assertEqual(self.client.post("/api/driver/state", headers=driver, json=state).status_code, 403)
        self.send_kyc(driver)
        self.assertEqual(self.client.post("/api/driver/state", headers=driver, json=state).status_code, 403)
        self.review(driver, True, "male")
        self.assertEqual(self.client.post("/api/driver/state", headers=driver, json=state).status_code, 200)
        self.client.post("/api/driver/state", headers=driver, json={"online": False})

    def test_women_raahi_needs_a_verified_id(self):
        rider = self.gendered("female")
        booking = {"pickup": JAMMU, "dropoff": GANDHI_NAGAR, "vehicle": "cab", "women_only": True}
        self.assertEqual(self.client.post("/api/rides", headers=rider, json=booking).status_code, 403)
        self.verify(rider, "female")
        ride = self.client.post("/api/rides", headers=rider, json=booking)
        self.assertEqual(ride.status_code, 200, ride.text)
        self.client.post(f"/api/rides/{ride.json()['id']}/cancel", headers=rider)

    def test_only_women_riders_can_ask_for_women_raahi_checks(self):
        for gender in ("male", "other", "unspecified"):
            self.assertEqual(self.send_kyc(self.gendered(gender)).status_code, 403, gender)
        self.assertEqual(self.send_kyc(self.account()).status_code, 403)
        self.assertEqual(self.send_kyc(self.admin).status_code, 403)

    def test_kyc_upload_is_checked(self):
        driver = self.account("driver", "cab")
        self.assertEqual(self.send_kyc(driver, consent=False).status_code, 422)
        self.assertEqual(self.send_kyc(driver, licence_image=None).status_code, 422)
        self.assertEqual(self.send_kyc(driver, rc_image=None).status_code, 422)
        self.assertEqual(self.send_kyc(driver, rc_image="not a picture").status_code, 422)
        self.assertEqual(self.send_kyc(driver, document="library card").status_code, 422)
        self.assertEqual(self.send_kyc(driver, selfie="<script>alert(1)</script>").status_code, 422)
        self.assertEqual(self.send_kyc(driver, id_image="data:image/svg+xml;base64,PHN2Zz4=").status_code, 422)
        self.assertEqual(self.send_kyc(driver).status_code, 200)
        self.assertEqual(self.send_kyc(driver).status_code, 409)       # already waiting

    def test_drivers_must_give_a_real_looking_number_plate(self):
        driver = self.account("driver", "cab")
        for bad in (None, "", "12345", "HELLO WORLD", "JK02AB12345"):
            self.assertEqual(self.send_kyc(driver, plate=bad).status_code, 422, bad)
        sent = self.send_kyc(driver, plate="22 BH 1234 AA")      # Bharat series
        self.assertEqual(sent.status_code, 200, sent.text)
        self.assertEqual(sent.json()["plate"], "22BH1234AA")

    def test_two_drivers_cannot_share_a_number_plate(self):
        first, second = self.account("driver", "cab"), self.account("driver", "cab")
        self.assertEqual(self.send_kyc(first, plate="JK21 C 4321").status_code, 200)
        self.assertEqual(self.send_kyc(second, plate="jk-21-c-4321").status_code, 409)
        # A rejected driver's plate is free again.
        self.review(first, False, note="Blurry licence")
        self.assertEqual(self.send_kyc(second, plate="JK21C4321").status_code, 200)

    def test_rider_sees_the_driver_number_plate(self):
        rider, driver = self.account(), self.account("driver", "cab")
        self.send_kyc(driver, plate="jk01 xy 0042")
        self.assertEqual(self.pending_check(driver)["plate"], "JK01 XY 0042")
        self.review(driver, True, "male")
        self.client.post("/api/driver/state", headers=driver, json={"online": True, "lat": 32.72, "lon": 74.86})
        try:
            ride = self.client.post("/api/rides", headers=rider, json={
                "pickup": JAMMU, "dropoff": GANDHI_NAGAR, "vehicle": "cab"}).json()
            url = f"/api/rides/{ride['id']}"
            wait_for(lambda: self.client.post(url + "/accept", headers=driver), lambda r: r.status_code == 200, 5)
            seen = self.client.get("/api/rides/active", headers=rider).json()
            self.assertEqual(seen["driver"]["plate"], "JK01 XY 0042")
            self.client.post(url + "/cancel", headers=rider)
        finally:
            self.client.post("/api/driver/state", headers=driver, json={"online": False})

    def outbox(self):
        """Capture emails and SMS instead of sending them."""
        mails, texts = [], []
        patches = (mock.patch.object(mailer, "send", lambda to, subject, body: mails.append((to, subject, body))),
                   mock.patch.object(sms, "send", lambda phone, text: texts.append((phone, text))))
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        return mails, texts

    def test_driver_gets_approval_by_email_and_sms(self):
        mails, texts = self.outbox()
        driver = self.account("driver", "cab", email="gauri@example.com")
        me = self.client.get("/api/me", headers=driver).json()
        self.assertEqual([m[1] for m in mails], ["Welcome to Raahi: one step left before you can drive"])
        self.send_kyc(driver, plate="JK02 GT 7001")
        self.assertEqual(mails[1][:2], ("gauri@example.com", "We have received your Raahi driver application"))
        self.assertIn("JK02 GT 7001", mails[1][2])
        self.assertEqual(texts, [])                         # no SMS until the decision
        self.review(driver, True, "female")
        self.assertEqual(len(mails), 3)
        to, subject, body = mails[2]
        self.assertEqual(to, "gauri@example.com")
        self.assertEqual(subject, "Verification completed: you can now drive with Raahi")
        self.assertIn("JK02 GT 7001", body)
        self.assertIn("go online, accept rides and drive with Raahi", body)
        self.assertEqual(texts[0][0], me["phone"])
        self.assertIn("go online, accept rides and drive with Raahi", texts[0][1])

    def test_women_raahi_rejection_reason_reaches_the_rider(self):
        mails, texts = self.outbox()
        rider = self.gendered("female")
        self.send_kyc(rider)
        self.review(rider, False, note="The photo is blurry")
        self.assertEqual(mails[-1][1], "We could not verify your ID for Women Raahi")
        self.assertIn("The photo is blurry", mails[-1][2])
        self.assertIn("The photo is blurry", texts[0][1])

    def test_women_raahi_approval_message(self):
        mails, texts = self.outbox()
        rider = self.verify(self.gendered("female"), "female")
        self.assertEqual([m[1] for m in mails], ["Welcome to Raahi", "We have received your ID for Women Raahi",
                                                 "Women Raahi is ready for you"])
        self.assertIn("women drivers", texts[0][1])

    def test_new_rider_gets_a_welcome_email(self):
        mails, _ = self.outbox()
        self.account("rider", email="asha@example.com")
        self.assertEqual(len(mails), 1)
        self.assertEqual(mails[0][:2], ("asha@example.com", "Welcome to Raahi"))
        self.assertIn("Hello Test", mails[0][2])

    def test_rejected_driver_hears_why_by_email(self):
        mails, _ = self.outbox()
        driver = self.account("driver", "cab", email="dev@example.com")
        self.send_kyc(driver)
        self.review(driver, False, note="RC photo is cut off")
        self.assertEqual([m[1] for m in mails], [
            "Welcome to Raahi: one step left before you can drive",
            "We have received your Raahi driver application",
            "We could not approve your Raahi driver registration yet"])
        self.assertIn("RC photo is cut off", mails[2][2])

    def test_mail_failure_does_not_block_signup_or_documents(self):
        def broken(*args):
            raise mailer.MailError("server down")
        with mock.patch.object(mailer, "send", broken):
            driver = self.account("driver", "cab")
            self.assertEqual(self.send_kyc(driver).status_code, 200)
        self.assertEqual(self.client.get("/api/me", headers=driver).json()["kyc"], "pending")

    def test_mail_failure_does_not_block_the_review(self):
        def broken(*args):
            raise mailer.MailError("server down")
        driver = self.account("driver", "cab")
        self.send_kyc(driver)
        with mock.patch.object(mailer, "send", broken), mock.patch.object(sms, "send", lambda *a: None):
            self.assertEqual(self.review(driver, True, "male").status_code, 200)
        self.assertEqual(self.client.get("/api/me", headers=driver).json()["kyc"], "approved")

    def test_rejection_explains_why_and_allows_a_new_try(self):
        driver = self.account("driver", "cab")
        self.send_kyc(driver)
        self.assertEqual(self.review(driver, False, note="").status_code, 422)
        self.assertEqual(self.review(driver, False, note="Selfie is too dark").status_code, 200)
        me = self.client.get("/api/me", headers=driver).json()
        self.assertEqual((me["kyc"], me["kyc_note"]), ("rejected", "Selfie is too dark"))
        self.verify(driver, "male")
        self.assertEqual(self.client.get("/api/me", headers=driver).json()["kyc"], "approved")
        self.assertEqual(self.send_kyc(driver).status_code, 409)

    def test_document_photos_are_deleted_after_review(self):
        driver = self.verify(self.account("driver", "cab"), "male")
        user_id = self.client.get("/api/me", headers=driver).json()["id"]
        with appdb.connect() as conn:
            row = conn.execute("SELECT * FROM verifications WHERE user_id = ?", (user_id,)).fetchone()
        self.assertEqual((row["id_image"], row["selfie"], row["licence_image"], row["rc_image"]), ("", "", None, None))
        reviewed = self.client.get("/api/admin/verifications", headers=self.admin).json()["reviewed"]
        self.assertNotIn("selfie", next(v for v in reviewed if v["id"] == row["id"]))

    def test_the_document_decides_gender_not_the_answer(self):
        driver = self.gendered("female", "driver", "cab")
        self.verify(driver, "male")
        self.assertEqual(self.client.get("/api/me", headers=driver).json()["gender"], "male")
        rider = self.gendered("female")
        self.send_kyc(rider)
        self.assertEqual(self.review(rider, True, "male").status_code, 422)
        self.assertEqual(self.review(rider, True, None).status_code, 422)

    def test_only_admins_see_id_checks(self):
        rider = self.account()
        self.assertEqual(self.client.get("/api/admin/verifications", headers=rider).status_code, 403)
        self.assertEqual(self.client.post("/api/admin/verifications/1", headers=rider, json={"approve": True}).status_code, 403)

    def test_driver_who_comes_online_after_booking_can_accept_and_rider_is_told(self):
        rider, driver = self.account(), self.driver("auto")
        rider_token = rider["Authorization"].removeprefix("Bearer ")
        with self.client.websocket_connect(f"/api/ws?token={rider_token}") as rider_ws:
            ride = self.book(rider, "auto")
            # The driver goes online only after the ride was booked, before the demo driver steps in.
            time.sleep(0.5)
            self.client.post("/api/driver/state", headers=driver, json={"online": True, "lat": 32.73, "lon": 74.86})
            url = f"/api/rides/{ride['id']}"
            accepted = wait_for(lambda: self.client.post(url + "/accept", headers=driver),
                                lambda r: r.status_code == 200, 5).json()
            self.assertFalse(accepted["driver"]["simulated"])

            while True:
                event = rider_ws.receive_json()
                if event["type"] == "confirmed":
                    break
            told = event["ride"]
            self.assertEqual(told["id"], ride["id"])
            self.assertEqual(told["driver"]["name"], "Test driver")
            self.assertEqual(told["driver"]["vehicle"], "Auto")
            self.assertRegex(told["driver"]["plate"], r"^JK02 AB \d{4}$")   # shown on the pop-up
            self.assertTrue(told["driver"]["phone"])
            self.assertGreater(told["driver"]["to_pickup"]["minutes"], 0)
            self.assertNotIn("business", told["quote"])
        self.client.post(url + "/cancel", headers=rider)
        self.client.post("/api/driver/state", headers=driver, json={"online": False})

    def test_demo_driver_waits_while_a_real_driver_holds_the_offer(self):
        rider, driver = self.account(), self.driver("bike")
        self.client.post("/api/driver/state", headers=driver, json={"online": True, "lat": 32.72, "lon": 74.86})
        ride = self.book(rider, "bike")
        url = f"/api/rides/{ride['id']}"
        # Well past the no-driver wait, the ride is still kept for the real driver.
        time.sleep(rides.NO_DRIVER_WAIT_SECONDS + 2)
        self.assertEqual(self.client.get("/api/rides/active", headers=rider).json()["status"], "searching")
        # Once they decline, the demo system takes over as before.
        self.assertEqual(self.client.post(url + "/decline", headers=driver).status_code, 200)
        accepted = wait_for(lambda: self.client.get("/api/rides/active", headers=rider).json(),
                            lambda r: r and r["driver"], 10)
        self.assertTrue(accepted["driver"]["simulated"])
        self.client.post(url + "/cancel", headers=rider)
        self.client.post("/api/driver/state", headers=driver, json={"online": False})

    def test_unanswered_offer_goes_to_the_demo_driver_when_time_is_up(self):
        self.assertEqual((rides.OFFER_SECONDS, rides.REAL_SEARCH_SECONDS), (60, 60))
        rider, driver = self.account(), self.driver("cab")
        self.client.post("/api/driver/state", headers=driver, json={"online": True, "lat": 32.72, "lon": 74.86})
        # The same rule as the real minute, shortened so the test runs quickly.
        with mock.patch.object(rides, "OFFER_SECONDS", 3), mock.patch.object(rides, "REAL_SEARCH_SECONDS", 3):
            ride = self.book(rider, "cab")
            time.sleep(1.5)
            self.assertEqual(self.client.get("/api/rides/active", headers=rider).json()["status"], "searching")
            taken = wait_for(lambda: self.client.get("/api/rides/active", headers=rider).json(),
                             lambda r: r and r["driver"], 10)
        self.assertTrue(taken["driver"]["simulated"])
        # The driver's offer has expired, so they can no longer take it.
        self.assertEqual(self.client.post(f"/api/rides/{ride['id']}/accept", headers=driver).status_code, 409)
        self.client.post(f"/api/rides/{ride['id']}/cancel", headers=rider)
        self.client.post("/api/driver/state", headers=driver, json={"online": False})

    def test_rider_can_rate_a_completed_trip_once_or_skip(self):
        rider, driver = self.account(), self.driver("erickshaw")
        self.client.post("/api/driver/state", headers=driver, json={"online": True, "lat": 32.72, "lon": 74.86})
        ride = self.book(rider, "erickshaw")
        url = f"/api/rides/{ride['id']}"
        good = {"rating": 5, "tags": ["safe", "polite"], "comment": "Very nice ride"}
        wait_for(lambda: self.client.post(url + "/accept", headers=driver), lambda r: r.status_code == 200, 5)
        self.assertEqual(self.client.post(url + "/feedback", headers=rider, json=good).status_code, 409)
        for step in ("arrived", "in_progress", "completed"):
            self.client.post(f"{url}/advance/{step}", headers=driver)
        self.client.post("/api/driver/state", headers=driver, json={"online": False})

        # Skipping sends nothing: the trip simply has no feedback.
        self.assertIsNone(self.client.get("/api/rides", headers=rider).json()[0]["feedback"])
        self.assertEqual(self.client.post(url + "/feedback", headers=driver, json=good).status_code, 403)
        self.assertEqual(self.client.post(url + "/feedback", headers=rider, json={"rating": 6}).status_code, 422)
        self.assertEqual(self.client.post(url + "/feedback", headers=rider, json={"rating": 4, "tags": ["bogus"]}).status_code, 422)

        sent = self.client.post(url + "/feedback", headers=rider, json=good)
        self.assertEqual(sent.status_code, 200, sent.text)
        self.assertEqual(self.client.post(url + "/feedback", headers=rider, json=good).status_code, 409)
        seen = self.client.get("/api/rides", headers=rider).json()[0]["feedback"]
        self.assertEqual((seen["rating"], seen["tags"], seen["comment"]), (5, ["safe", "polite"], "Very nice ride"))
        self.assertEqual(self.client.get("/api/rides", headers=driver).json()[0]["feedback"]["rating"], 5)
        overview = self.client.get("/api/admin/overview", headers=self.admin).json()
        self.assertGreaterEqual(overview["ratings"]["count"], 1)

    def finished_ride(self, vehicle="bike"):
        """A real driver takes a ride and drives it to the end. Returns (rider, driver, url, ride)."""
        rider, driver = self.account(), self.driver(vehicle)
        self.client.post("/api/driver/state", headers=driver, json={"online": True, "lat": 32.72, "lon": 74.86})
        ride = self.book(rider, vehicle)
        url = f"/api/rides/{ride['id']}"
        wait_for(lambda: self.client.post(url + "/accept", headers=driver), lambda r: r.status_code == 200, 5)
        for step in ("arrived", "in_progress"):
            self.client.post(f"{url}/advance/{step}", headers=driver)
        return rider, driver, url, ride

    def test_rider_pays_by_scanning_the_qr_then_both_apps_move_on(self):
        rider, driver, url, ride = self.finished_ride()
        self.assertIsNone(self.client.get("/api/rides/active", headers=rider).json()["payment"])
        self.client.post(f"{url}/advance/completed", headers=driver)
        self.client.post("/api/driver/state", headers=driver, json={"online": False})

        due = self.client.get("/api/rides", headers=rider).json()[0]["payment"]
        self.assertEqual(due["status"], "due")
        pay_path = due["pay_path"]
        self.assertEqual(self.client.get("/api/rides", headers=driver).json()[0]["payment"]["pay_path"], pay_path)
        admin_view = next(r for r in self.client.get("/api/admin/overview", headers=self.admin).json()["recent"] if r["id"] == ride["id"])
        self.assertIsNone(admin_view["payment"]["pay_path"])   # the link is for the rider and driver only

        qr = self.client.get(pay_path + "/qr.svg")
        self.assertEqual(qr.status_code, 200)
        self.assertIn("image/svg+xml", qr.headers["content-type"])
        self.assertEqual(self.client.get(pay_path).status_code, 200)        # the page the QR opens
        token = pay_path.rsplit("/", 1)[1]
        details = self.client.get(f"/api/pay/{token}").json()
        self.assertEqual((details["fare"], details["paid"], details["demo"]), (ride["fare"], False, True))

        rider_token = rider["Authorization"].removeprefix("Bearer ")
        with self.client.websocket_connect(f"/api/ws?token={rider_token}") as rider_ws:
            paid = self.client.post(f"/api/pay/{token}")
            self.assertEqual(paid.status_code, 200, paid.text)
            self.assertTrue(paid.json()["paid"])
            while (event := rider_ws.receive_json())["type"] != "paid":
                pass
        self.assertEqual(event["ride"]["payment"]["status"], "paid")
        self.assertEqual(event["ride"]["payment"]["method"], "qr_demo")
        self.assertIsNone(event["ride"]["payment"]["pay_path"])
        # Scanning again just shows it is paid.
        self.assertEqual(self.client.post(f"/api/pay/{token}").status_code, 200)
        self.assertEqual(self.client.get("/api/rides", headers=driver).json()[0]["payment"]["status"], "paid")

    def test_scanned_page_pays_with_a_plain_form_without_scripts(self):
        # In-app browsers (Google Lens, camera apps) may drop a script's background request,
        # so the page itself is built on the server and pays with an ordinary form POST.
        rider, driver, url, ride = self.finished_ride("cab")
        with appdb.connect() as conn:
            token = conn.execute("SELECT pay_token FROM rides WHERE id = ?", (ride["id"],)).fetchone()["pay_token"]
        early = self.client.get(f"/pay/{token}")
        self.assertIn("You can pay once the trip has ended", early.text)
        self.assertEqual(self.client.post(f"/pay/{token}", follow_redirects=False).status_code, 409)
        self.client.post(f"{url}/advance/completed", headers=driver)
        self.client.post("/api/driver/state", headers=driver, json={"online": False})

        page = self.client.get(f"/pay/{token}")
        self.assertEqual(page.status_code, 200)
        self.assertIn(f'<form id="pay-form" method="post" action="/pay/{token}">', page.text)
        self.assertIn("DEMO PAYMENT", page.text)
        rider_token = rider["Authorization"].removeprefix("Bearer ")
        with self.client.websocket_connect(f"/api/ws?token={rider_token}") as rider_ws:
            sent = self.client.post(f"/pay/{token}", follow_redirects=False)
            self.assertEqual(sent.status_code, 303)
            self.assertEqual(sent.headers["location"], f"/pay/{token}")
            while rider_ws.receive_json()["type"] != "paid":
                pass
        receipt = self.client.get(f"/pay/{token}")
        self.assertIn("Payment received", receipt.text)
        self.assertNotIn("pay-form", receipt.text)
        # Refreshing or resubmitting changes nothing.
        self.assertEqual(self.client.post(f"/pay/{token}", follow_redirects=False).status_code, 303)
        self.assertEqual(self.client.get("/api/rides", headers=rider).json()[0]["payment"]["method"], "qr_demo")
        bad = self.client.get("/pay/not-a-real-link")
        self.assertEqual(bad.status_code, 404)
        self.assertIn("Payment not done", bad.text)

    def test_payment_waits_for_the_trip_to_end_and_bad_links_fail(self):
        rider, driver, url, ride = self.finished_ride("auto")
        token = self.client.get("/api/rides/active", headers=rider).json()
        with appdb.connect() as conn:
            token = conn.execute("SELECT pay_token FROM rides WHERE id = ?", (ride["id"],)).fetchone()["pay_token"]
        self.assertEqual(self.client.post(f"/api/pay/{token}").status_code, 409)       # still on the trip
        self.assertEqual(self.client.post("/api/pay/not-a-real-link").status_code, 404)
        self.assertEqual(self.client.get("/pay/not-a-real-link/qr.svg").status_code, 404)
        self.client.post(f"{url}/advance/completed", headers=driver)
        self.client.post("/api/driver/state", headers=driver, json={"online": False})
        self.assertEqual(self.client.post(url + "/cash", headers=rider).status_code, 403)
        self.assertEqual(self.client.post(url + "/cash", headers=self.driver("auto")).status_code, 404)
        cash = self.client.post(url + "/cash", headers=driver)
        self.assertEqual(cash.status_code, 200, cash.text)
        self.assertEqual(cash.json()["payment"]["method"], "cash")
        self.assertTrue(self.client.get(f"/api/pay/{token}").json()["paid"])

    def test_driver_goes_offline_when_the_connection_drops(self):
        driver = self.driver()
        token = driver["Authorization"].removeprefix("Bearer ")
        driver_id = self.client.get("/api/me", headers=driver).json()["id"]
        with self.client.websocket_connect(f"/api/ws?token={token}"):
            self.client.post("/api/driver/state", headers=driver, json={"online": True, "lat": 32.72, "lon": 74.86})
            self.assertIn(driver_id, rides.hub.drivers)
        wait_for(lambda: driver_id in rides.hub.drivers, lambda online: not online, 5)

    def test_rider_can_ask_for_help_during_a_ride_and_admin_sees_it(self):
        rider = self.account()
        ride = self.client.post("/api/rides", headers=rider, json={
            "pickup": JAMMU, "dropoff": GANDHI_NAGAR, "vehicle": "auto"}).json()
        stranger = self.account()
        ask = lambda who, body: self.client.post(f"/api/rides/{ride['id']}/help", headers=who, json=body)
        self.assertEqual(ask(stranger, {"topic": "safety"}).status_code, 404)
        self.assertEqual(ask(rider, {"topic": "nonsense"}).status_code, 422)
        self.assertEqual(ask(self.admin, {"topic": "safety"}).status_code, 403)
        response = ask(rider, {"topic": "safety", "note": "Driver is speeding", "lat": 32.72, "lon": 74.85})
        self.assertEqual(response.status_code, 200, response.text)

        listed = self.client.get("/api/admin/help", headers=self.admin).json()
        mine = next(h for h in listed if h["id"] == response.json()["id"])
        self.assertEqual(mine["topic_label"], "I feel unsafe")
        self.assertIn("Driver is speeding", mine["note"])
        self.assertIn("32.72", mine["note"])
        self.assertEqual(self.client.get("/api/admin/help", headers=rider).status_code, 403)

        self.client.post(f"/api/rides/{ride['id']}/cancel", headers=rider)
        self.assertEqual(ask(rider, {"topic": "other"}).status_code, 409)

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

    def test_remote_corners_of_jk_can_be_booked(self):
        # Spots far from any town, with no named place nearby, are still inside J&K.
        for name, lat, lon in (("Gurez", 34.63, 74.84), ("Machil", 34.55, 74.37), ("Paddar", 33.25, 76.15),
                               ("Bani", 32.69, 75.81), ("Lakhanpur", 32.39, 75.57)):
            self.assertTrue(places.in_service_area(lat, lon), name)

    def test_neighbouring_states_and_ladakh_are_outside(self):
        for name, lat, lon in (("Pathankot", 32.27, 75.65), ("Leh", 34.15, 77.58), ("Muzaffarabad", 34.37, 73.47)):
            self.assertFalse(places.in_service_area(lat, lon), name)

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
