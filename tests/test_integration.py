"""End-to-end test against a stub UniFi OS console.

Starts a real HTTPS server with a self-signed certificate - the same shape a
UniFi console presents - and drives the client through it. This covers the
parts unit tests cannot: URL construction, the X-API-KEY header, self-signed
certificate handling, action payloads, and error propagation.
"""

import http.server
import importlib.machinery
import importlib.util
import json
import os
import pathlib
import ssl
import subprocess
import tempfile
import threading
import unittest

BIN = pathlib.Path(__file__).resolve().parent.parent / "bin" / "omarchy-unifi"
spec = importlib.util.spec_from_loader(
    "omarchy_unifi", importlib.machinery.SourceFileLoader("omarchy_unifi", str(BIN))
)
uni = importlib.util.module_from_spec(spec)
spec.loader.exec_module(uni)

from test_unifi import CLIENTS, DEVICES, HEALTH  # noqa: E402

API_KEY = "test-key-abc123"
RESPONSES = {
    "stat/health": HEALTH,
    "stat/device": DEVICES,
    "stat/sta": CLIENTS,
    "rest/user": [
        {"mac": "de:ad:be:ef:00:01", "name": "Old Tablet", "blocked": True},
        {"mac": "de:ad:be:ef:00:02", "name": "Laptop", "blocked": False},
    ],
}

received = []
# Set to make the stub answer speed tests the way a USG-class gateway does.
refuse_speedtest = []


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def _send(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle(self, body=None):
        # Every request must carry the API key; a UniFi console rejects
        # anything else with 401.
        if self.headers.get("X-API-KEY") != API_KEY:
            self._send(401, {"meta": {"rc": "error", "msg": "api.err.Invalid"}})
            return
        prefix = "/proxy/network/api/s/default/"
        if not self.path.startswith(prefix):
            self._send(404, {"meta": {"rc": "error", "msg": "api.err.NoSiteContext"}})
            return
        endpoint = self.path[len(prefix):]
        received.append((endpoint, body))
        if endpoint in RESPONSES:
            self._send(200, {"meta": {"rc": "ok"}, "data": RESPONSES[endpoint]})
        elif endpoint.startswith("cmd/"):
            if refuse_speedtest and (body or {}).get("cmd") == "speedtest":
                self._send(400, {"meta": {"rc": "error",
                                          "msg": "api.err.SpeedTestNotSupported"},
                                 "data": []})
                return
            self._send(200, {"meta": {"rc": "ok"}, "data": []})
        else:
            self._send(404, {"meta": {"rc": "error", "msg": "api.err.UnknownEndpoint"}})

    def do_GET(self):
        self._handle()

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        self._handle(json.loads(raw) if raw else None)


class StubConsole:
    def __init__(self):
        self.tmp = tempfile.mkdtemp()
        cert = os.path.join(self.tmp, "cert.pem")
        key = os.path.join(self.tmp, "key.pem")
        subprocess.run(
            ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
             "-keyout", key, "-out", cert, "-days", "1", "-subj", "/CN=unifi.local"],
            check=True, capture_output=True)
        self.server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert, key)
        self.server.socket = ctx.wrap_socket(self.server.socket, server_side=True)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def host(self):
        return f"127.0.0.1:{self.server.server_address[1]}"

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


class TestAgainstStubConsole(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.console = StubConsole()

    @classmethod
    def tearDownClass(cls):
        cls.console.stop()

    def setUp(self):
        received.clear()
        self.cfg = {"host": self.console.host, "apiKey": API_KEY, "site": "default"}
        self.api = uni.UniFi(self.cfg)

    def test_self_signed_certificate_is_accepted(self):
        # A console's own cert is never CA-signed; verification off by default.
        self.assertEqual(len(self.api.legacy("stat/health")), len(HEALTH))

    def test_verify_ssl_on_rejects_self_signed(self):
        strict = uni.UniFi(dict(self.cfg, verifySsl=True))
        with self.assertRaises(uni.UniFiError):
            strict.legacy("stat/health")

    def test_collect_produces_a_complete_state(self):
        state = uni.collect(self.api)
        self.assertTrue(state["ok"])
        self.assertTrue(state["wan"]["up"])
        self.assertEqual(state["wan"]["ip"], "203.0.113.42")
        self.assertEqual(state["clients"]["total"], 3)
        self.assertEqual(state["devices"]["total"], 3)
        self.assertEqual(state["devices"]["offline"], 1)
        self.assertIn("1 device offline", state["alerts"])

    def test_blocked_clients_are_filtered_from_rest_user(self):
        state = uni.collect(self.api)
        self.assertEqual([b["name"] for b in state["blockedList"]], ["Old Tablet"])

    def test_bad_api_key_is_reported_actionably(self):
        bad = uni.UniFi(dict(self.cfg, apiKey="wrong"))
        with self.assertRaises(uni.UniFiError) as ctx:
            bad.legacy("stat/health")
        self.assertEqual(ctx.exception.status, 401)
        self.assertIn("API key rejected", str(ctx.exception))

    def test_unreachable_host_is_reported_actionably(self):
        dead = uni.UniFi({"host": "127.0.0.1:1", "apiKey": API_KEY, "timeoutSec": 2})
        with self.assertRaises(uni.UniFiError) as ctx:
            dead.legacy("stat/health")
        self.assertIn("cannot reach", str(ctx.exception))

    def test_action_payloads_match_the_unifi_command_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            uni.STATE_DIR, uni.STATE_PATH = tmp, os.path.join(tmp, "state.json")
            original = uni.load_config
            uni.load_config = lambda: dict(self.cfg)
            try:
                uni.cmd_restart(type("A", (), {"mac": "AA:BB:CC:DD:EE:02"}))
                uni.cmd_block(type("A", (), {"mac": "11:22:33:44:55:03"}))
                uni.cmd_unblock(type("A", (), {"mac": "de:ad:be:ef:00:01"}))
                uni.cmd_kick(type("A", (), {"mac": "11:22:33:44:55:01"}))
            finally:
                uni.load_config = original
        sent = {ep: body for ep, body in received if ep.startswith("cmd/")}
        self.assertEqual(sent["cmd/devmgr"],
                         {"cmd": "restart", "mac": "aa:bb:cc:dd:ee:02"})
        # stamgr carries the last of block/unblock/kick; assert each was sent.
        commands = [b["cmd"] for ep, b in received if ep == "cmd/stamgr"]
        self.assertEqual(commands, ["block-sta", "unblock-sta", "kick-sta"])

    def test_macs_are_lowercased_before_sending(self):
        # UniFi stores MACs lowercase; an uppercase MAC silently matches nothing.
        with tempfile.TemporaryDirectory() as tmp:
            uni.STATE_DIR, uni.STATE_PATH = tmp, os.path.join(tmp, "state.json")
            original = uni.load_config
            uni.load_config = lambda: dict(self.cfg)
            try:
                uni.cmd_block(type("A", (), {"mac": "AA:BB:CC:DD:EE:FF"}))
            finally:
                uni.load_config = original
        body = next(b for ep, b in received if ep == "cmd/stamgr")
        self.assertEqual(body["mac"], "aa:bb:cc:dd:ee:ff")

    def test_unsupported_speedtest_is_explained_and_remembered(self):
        # A USG-class gateway refuses controller-run speed tests. The panel
        # should stop offering the button rather than fail on every click.
        refuse_speedtest.append(True)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                uni.STATE_DIR, uni.STATE_PATH = tmp, os.path.join(tmp, "state.json")
                original = uni.load_config
                uni.load_config = lambda: dict(self.cfg)
                try:
                    uni.cmd_poll(None)
                    self.assertTrue(json.load(open(uni.STATE_PATH))["speedtestSupported"])
                    rc = uni.cmd_speedtest(type("A", (), {"wait": False}))
                finally:
                    uni.load_config = original
                state = json.load(open(uni.STATE_PATH))
            self.assertEqual(rc, 1)
            self.assertFalse(state["speedtestSupported"])
        finally:
            refuse_speedtest.clear()

    def test_unsupported_verdict_survives_the_next_poll(self):
        refuse_speedtest.append(True)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                uni.STATE_DIR, uni.STATE_PATH = tmp, os.path.join(tmp, "state.json")
                original = uni.load_config
                uni.load_config = lambda: dict(self.cfg)
                try:
                    uni.cmd_speedtest(type("A", (), {"wait": False}))
                    # A later poll must not resurrect the button.
                    uni.cmd_poll(None)
                finally:
                    uni.load_config = original
                state = json.load(open(uni.STATE_PATH))
            self.assertFalse(state["speedtestSupported"])
        finally:
            refuse_speedtest.clear()

    def test_api_error_message_reaches_the_caller(self):
        refuse_speedtest.append(True)
        try:
            with self.assertRaises(uni.UniFiError) as ctx:
                self.api.legacy("cmd/devmgr", {"cmd": "speedtest"})
            self.assertEqual(ctx.exception.api_code, "api.err.SpeedTestNotSupported")
            self.assertIn("does not support", str(ctx.exception))
        finally:
            refuse_speedtest.clear()

    def test_poll_writes_state_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            uni.STATE_DIR, uni.STATE_PATH = tmp, os.path.join(tmp, "state.json")
            original = uni.load_config
            uni.load_config = lambda: dict(self.cfg)
            try:
                self.assertEqual(uni.cmd_poll(None), 0)
            finally:
                uni.load_config = original
            state = json.load(open(uni.STATE_PATH))
        self.assertTrue(state["ok"])
        self.assertEqual(state["devices"]["online"], 2)

    def test_poll_failure_writes_stale_state_rather_than_crashing(self):
        with tempfile.TemporaryDirectory() as tmp:
            uni.STATE_DIR, uni.STATE_PATH = tmp, os.path.join(tmp, "state.json")
            original = uni.load_config
            uni.load_config = lambda: {"host": "127.0.0.1:1", "apiKey": "k",
                                       "timeoutSec": 2}
            try:
                self.assertEqual(uni.cmd_poll(None), 1)
            finally:
                uni.load_config = original
            state = json.load(open(uni.STATE_PATH))
        self.assertFalse(state["ok"])
        self.assertTrue(state["stale"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
