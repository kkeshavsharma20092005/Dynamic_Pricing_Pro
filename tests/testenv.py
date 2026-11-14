"""Point the app at a throwaway database. Import this before anything from the backend."""
import os
import tempfile

_tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["APP_DB_PATH"] = os.path.join(_tmp.name, "test.db")
os.environ["ADMIN_PHONE"] = "9000000001"
os.environ["ADMIN_PASSWORD"] = "admin-test-password"
os.environ["ROAD_ROUTING"] = "0"      # tests must not depend on a public routing server
os.environ["LIVE_WEATHER"] = "0"     # nor on a public weather service
