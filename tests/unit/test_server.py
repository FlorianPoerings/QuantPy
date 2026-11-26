import importlib
import os
import tempfile
import time
import unittest

import pyotp

H = {"X-Requested-With": "QuantPy"}


class TestServerAuth(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.secret = pyotp.random_base32()
        with open(os.path.join(cls.tmp.name, "tester.totp"), "w") as f:
            f.write(cls.secret)
        os.environ.update(QUANT_USER="tester", QUANT_PASSWORD="pw-123456",
                          QUANTPY_SECRETS_DIR=cls.tmp.name, SECRET_KEY="x" * 40,
                          QUANTPY_AUDIT_PATH=os.path.join(cls.tmp.name, "audit.jsonl"))
        import server
        cls.server = importlib.reload(server)

    def setUp(self):
        self.server._fail.clear()
        self.server._last_totp.clear()
        self.c = self.server.app.test_client()

    def login(self, pw="pw-123456"):
        return self.c.post("/api/auth/login", json={"username": "tester", "password": pw}, headers=H)

    def test_password_alone_does_not_authenticate(self):
        self.assertEqual(self.login().status_code, 200)
        self.assertEqual(self.c.get("/api/status").status_code, 401)
        self.assertFalse(self.c.get("/api/auth/me").json["authenticated"])

    def test_full_flow_with_totp_and_replay_protection(self):
        self.login()
        code = pyotp.TOTP(self.secret).now()
        r = self.c.post("/api/auth/verify_2fa", json={"code": code}, headers=H)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.c.get("/api/status").status_code, 200)
        c2 = self.server.app.test_client()
        c2.post("/api/auth/login", json={"username": "tester", "password": "pw-123456"}, headers=H)
        r = c2.post("/api/auth/verify_2fa", json={"code": code}, headers=H)
        self.assertEqual(r.status_code, 401)           # same code cannot be reused

    def test_wrong_password_and_lockout(self):
        for _ in range(5):
            self.assertEqual(self.login("bad").status_code, 401)
        self.assertEqual(self.login().status_code, 429)

    def test_csrf_header_required(self):
        r = self.c.post("/api/auth/login", json={"username": "tester", "password": "pw-123456"})
        self.assertEqual(r.status_code, 403)

    def test_start_requires_legal_ack(self):
        self.login()
        self.c.post("/api/auth/verify_2fa", json={"code": pyotp.TOTP(self.secret).now()}, headers=H)
        r = self.c.post("/api/start", json={"capital": 1000, "symbols": ["AAPL"]}, headers=H)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json["code"], "legal_required")

    def test_input_validation(self):
        with self.assertRaises(ValueError):
            self.server._parse_params({"capital": 1000, "symbols": ["AAPL; DROP"]})
        with self.assertRaises(ValueError):
            self.server._parse_params({"capital": 5, "symbols": ["AAPL"]})
        self.assertEqual(self.server._parse_params({"capital": 500, "symbols": ["aapl", "BRK.B"]})[1],
                         ["AAPL", "BRK.B"])

    def test_legal_page_served(self):
        self.assertEqual(self.c.get("/legal").status_code, 200)
