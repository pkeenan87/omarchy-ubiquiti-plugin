"""Unit tests for the omarchy-unifi state shaping.

Fixtures mirror real UniFi OS `stat/health`, `stat/device` and `stat/sta`
payloads, including the quirks that matter: hyphenated rate keys, string
numbers, and subsystems that report `unknown`.
"""

import importlib.util
import json
import os
import pathlib
import sys
import tempfile
import time
import unittest

BIN = pathlib.Path(__file__).resolve().parent.parent / "bin" / "omarchy-unifi"
spec = importlib.util.spec_from_loader(
    "omarchy_unifi", importlib.machinery.SourceFileLoader("omarchy_unifi", str(BIN))
)
uni = importlib.util.module_from_spec(spec)
spec.loader.exec_module(uni)

# Redirect every user-owned path into a temp dir before any test runs. Without
# this the suite reads the real ~/.config/omarchy-unifi - which on a machine
# with a pinned console makes the stub tests fail against the operator's own
# certificate, and risks touching their files.
_SANDBOX = tempfile.mkdtemp(prefix="omarchy-unifi-tests-")
uni.CONFIG_DIR = _SANDBOX
uni.CONFIG_PATH = os.path.join(_SANDBOX, "config.json")
uni.CERT_PATH = os.path.join(_SANDBOX, "console.pem")
uni.STATE_DIR = os.path.join(_SANDBOX, "state")
uni.STATE_PATH = os.path.join(uni.STATE_DIR, "state.json")


HEALTH = [
    {"subsystem": "wan", "status": "ok", "gw_mac": "aa:bb:cc:dd:ee:01",
     "gw_name": "Dream Machine", "wan_ip": "203.0.113.42",
     "rx_bytes-r": 1_250_000, "tx_bytes-r": 140_000, "uptime": 864000,
     "num_gw": 1, "num_adopted": 1, "num_disconnected": 0},
    {"subsystem": "www", "status": "ok", "latency": 12,
     "xput_down": 934.2, "xput_up": 887.1},
    {"subsystem": "wlan", "status": "ok", "num_user": 18, "num_guest": 2,
     "num_ap": 3, "num_adopted": 3, "num_disconnected": 0},
    {"subsystem": "lan", "status": "ok", "num_user": 6, "num_sw": 2,
     "num_adopted": 2, "num_disconnected": 0},
    {"subsystem": "vpn", "status": "unknown"},
]

DEVICES = [
    {"_id": "1", "mac": "aa:bb:cc:dd:ee:01", "name": "Dream Machine", "type": "ugw",
     "model": "UDMPRO", "ip": "192.168.1.1", "state": 1, "version": "9.0.114",
     "upgradable": False, "num_sta": 24, "uptime": 864000,
     "system-stats": {"cpu": "14.2", "mem": "48.6"}, "satisfaction": 99},
    {"_id": "2", "mac": "aa:bb:cc:dd:ee:02", "name": "Office AP", "type": "uap",
     "model": "U6LR", "ip": "192.168.1.20", "state": 1, "version": "6.6.55",
     "upgradable": True, "num_sta": 11, "uptime": 432000,
     "system-stats": {"cpu": "7.1", "mem": "61.0"}},
    {"_id": "3", "mac": "aa:bb:cc:dd:ee:03", "name": "Garage Switch", "type": "usw",
     "model": "USW8P60", "ip": "192.168.1.30", "state": 0, "version": "6.5.32",
     "upgradable": False, "num_sta": 0, "uptime": 0, "system-stats": {}},
]

CLIENTS = [
    {"mac": "11:22:33:44:55:01", "hostname": "laptop", "ip": "192.168.1.50",
     "is_wired": False, "is_guest": False, "essid": "Home", "signal": -52,
     "rx_bytes-r": 900_000, "tx_bytes-r": 50_000, "uptime": 7200, "network": "LAN"},
    {"mac": "11:22:33:44:55:02", "name": "NAS", "ip": "192.168.1.60",
     "is_wired": True, "is_guest": False, "rx_bytes-r": 20_000,
     "tx_bytes-r": 5_000, "uptime": 864000, "network": "LAN"},
    {"mac": "11:22:33:44:55:03", "oui": "Amazon", "ip": "192.168.1.99",
     "is_wired": False, "is_guest": True, "essid": "Guest", "signal": -71,
     "uptime": 600, "network": "Guest"},
]


class TestWan(unittest.TestCase):
    def setUp(self):
        self.wan = uni.build_wan(uni._subsystems(HEALTH))

    def test_reports_up_and_address(self):
        self.assertTrue(self.wan["up"])
        self.assertEqual(self.wan["status"], "ok")
        self.assertEqual(self.wan["ip"], "203.0.113.42")

    def test_uses_instantaneous_rate_keys(self):
        # The hyphenated `*_bytes-r` keys are rates, not counters.
        self.assertEqual(self.wan["downBps"], 1_250_000)
        self.assertEqual(self.wan["upBps"], 140_000)

    def test_latency_comes_from_www_subsystem(self):
        self.assertEqual(self.wan["latencyMs"], 12)

    def test_wan_down_is_detected(self):
        health = [dict(h) for h in HEALTH]
        health[0]["status"] = "error"
        wan = uni.build_wan(uni._subsystems(health))
        self.assertFalse(wan["up"])

    def test_missing_subsystems_do_not_raise(self):
        wan = uni.build_wan({})
        self.assertFalse(wan["up"])
        self.assertEqual(wan["downBps"], 0)
        self.assertEqual(wan["latencyMs"], -1)


class TestDevices(unittest.TestCase):
    def setUp(self):
        self.devices = uni.build_devices(DEVICES)

    def test_counts(self):
        self.assertEqual(self.devices["total"], 3)
        self.assertEqual(self.devices["online"], 2)
        self.assertEqual(self.devices["offline"], 1)
        self.assertEqual(self.devices["updatable"], 1)

    def test_offline_devices_sort_first(self):
        self.assertFalse(self.devices["list"][0]["online"])
        self.assertEqual(self.devices["list"][0]["name"], "Garage Switch")

    def test_device_kinds_are_labelled(self):
        kinds = {d["name"]: d["kind"] for d in self.devices["list"]}
        self.assertEqual(kinds["Dream Machine"], "Gateway")
        self.assertEqual(kinds["Office AP"], "Access Point")
        self.assertEqual(kinds["Garage Switch"], "Switch")

    def test_string_numbers_are_coerced(self):
        gw = next(d for d in self.devices["list"] if d["name"] == "Dream Machine")
        self.assertAlmostEqual(gw["cpuPct"], 14.2)
        self.assertAlmostEqual(gw["memPct"], 48.6)

    def test_missing_system_stats_yield_sentinel(self):
        sw = next(d for d in self.devices["list"] if d["name"] == "Garage Switch")
        self.assertEqual(sw["cpuPct"], -1)

    def test_empty_input(self):
        empty = uni.build_devices([])
        self.assertEqual(empty["total"], 0)
        self.assertEqual(empty["list"], [])


class TestClients(unittest.TestCase):
    def test_split_by_medium(self):
        counts = uni.build_clients(uni._subsystems(HEALTH), CLIENTS)
        self.assertEqual(counts["total"], 3)
        self.assertEqual(counts["wireless"], 2)
        self.assertEqual(counts["wired"], 1)
        self.assertEqual(counts["guest"], 1)

    def test_falls_back_to_health_counts_when_list_unavailable(self):
        # stat/sta can fail while stat/health still succeeds.
        counts = uni.build_clients(uni._subsystems(HEALTH), [])
        self.assertEqual(counts["wireless"], 18)
        self.assertEqual(counts["wired"], 6)
        self.assertEqual(counts["total"], 24)

    def test_names_fall_back_through_hostname_and_oui(self):
        names = {c["mac"]: c["name"] for c in uni.build_client_list(CLIENTS)}
        self.assertEqual(names["11:22:33:44:55:01"], "laptop")
        self.assertEqual(names["11:22:33:44:55:02"], "NAS")
        self.assertEqual(names["11:22:33:44:55:03"], "Amazon")

    def test_sorted_by_current_throughput(self):
        listed = uni.build_client_list(CLIENTS)
        self.assertEqual(listed[0]["name"], "laptop")


class TestUntrustedNames(unittest.TestCase):
    """Client names are chosen by the client (DHCP option 12), so they are
    attacker-controlled on any network with an untrusted device on it."""

    def test_control_characters_are_stripped(self):
        hostile = [{"mac": "aa:bb:cc:dd:ee:ff", "hostname": "NAS\nFAKE ROW",
                    "is_wired": True, "ip": "192.168.1.5"}]
        name = uni.build_client_list(hostile)[0]["name"]
        self.assertNotIn("\n", name)
        self.assertEqual(name, "NASFAKE ROW")

    def test_markup_is_preserved_verbatim_not_stripped(self):
        # The QML renders PlainText, so markup must show as literal text
        # rather than be silently mangled here.
        hostile = [{"mac": "aa:bb:cc:dd:ee:ff", "hostname": "<b>Router</b>",
                    "is_wired": True}]
        self.assertEqual(uni.build_client_list(hostile)[0]["name"], "<b>Router</b>")

    def test_absurdly_long_names_are_capped(self):
        hostile = [{"mac": "aa:bb:cc:dd:ee:ff", "hostname": "A" * 5000,
                    "is_wired": True}]
        self.assertEqual(len(uni.build_client_list(hostile)[0]["name"]), 64)

    def test_device_names_are_cleaned_too(self):
        devices = uni.build_devices([
            {"mac": "aa:bb:cc:dd:ee:01", "name": "Switch\u0000\u009b", "type": "usw",
             "state": 1, "system-stats": {}}])
        self.assertEqual(devices["list"][0]["name"], "Switch")

    def test_blank_name_falls_back(self):
        hostile = [{"mac": "aa:bb:cc:dd:ee:ff", "hostname": "\n\n", "is_wired": True}]
        self.assertEqual(uni.build_client_list(hostile)[0]["name"], "Unknown")


class TestAlerts(unittest.TestCase):
    def test_healthy_network_has_no_alerts(self):
        health = [dict(h) for h in HEALTH]
        devices = uni.build_devices(DEVICES[:2])
        devices["updatable"] = 0
        for d in devices["list"]:
            d["updatable"] = False
        alerts = uni.build_alerts(uni.build_wan(uni._subsystems(health)), devices)
        self.assertEqual(alerts, [])

    def test_wan_down_and_offline_device_both_reported(self):
        health = [dict(h) for h in HEALTH]
        health[0]["status"] = "error"
        alerts = uni.build_alerts(
            uni.build_wan(uni._subsystems(health)), uni.build_devices(DEVICES))
        self.assertIn("Internet is down", alerts)
        self.assertIn("1 device offline", alerts)

    def test_offline_plural_agreement(self):
        devices = uni.build_devices(DEVICES)
        devices["offline"] = 2
        alerts = uni.build_alerts({"up": True}, devices)
        self.assertIn("2 devices offline", alerts)

    def test_firmware_updates_are_notices_not_alerts(self):
        # A deferred update is a normal state to sit in for months; it must
        # not colour the bar the same as an outage.
        devices = uni.build_devices(DEVICES)
        alerts = uni.build_alerts({"up": True}, devices)
        notices = uni.build_notices(devices)
        self.assertEqual([a for a in alerts if "firmware" in a], [])
        self.assertEqual(notices, ["1 firmware update available"])

    def test_notice_plural_agreement(self):
        devices = uni.build_devices(DEVICES)
        devices["updatable"] = 3
        self.assertEqual(uni.build_notices(devices), ["3 firmware updates available"])

    def test_healthy_network_has_neither(self):
        devices = uni.build_devices(DEVICES[:2])
        devices["offline"] = 0
        devices["updatable"] = 0
        self.assertEqual(uni.build_alerts({"up": True}, devices), [])
        self.assertEqual(uni.build_notices(devices), [])


class TestApiErrors(unittest.TestCase):
    class FakeHttpError:
        def __init__(self, payload):
            self._payload = payload

        def read(self):
            return self._payload.encode()

    def test_known_code_is_translated(self):
        err = self.FakeHttpError(
            '{"meta":{"rc":"error","msg":"api.err.NoSiteContext"},"data":[]}')
        code, message = uni._api_error(err)
        self.assertEqual(code, "api.err.NoSiteContext")
        self.assertIn("site not found", message)

    def test_unknown_code_is_passed_through_verbatim(self):
        err = self.FakeHttpError('{"meta":{"rc":"error","msg":"api.err.Weird"}}')
        code, message = uni._api_error(err)
        self.assertEqual(code, "api.err.Weird")
        self.assertEqual(message, "api.err.Weird")

    def test_non_json_body_is_survivable(self):
        self.assertEqual(uni._api_error(self.FakeHttpError("<html>502</html>")), ("", ""))

    def test_body_without_a_message(self):
        self.assertEqual(uni._api_error(self.FakeHttpError('{"meta":{"rc":"ok"}}')), ("", ""))


class TestFormatting(unittest.TestCase):
    def test_bits_per_second_scaling(self):
        self.assertEqual(uni.human_bps(0), "0")
        self.assertEqual(uni.human_bps(1_250_000), "10M")      # 10 Mbps
        self.assertEqual(uni.human_bps(125_000_000), "1.0G")   # 1 Gbps
        self.assertEqual(uni.human_bps(1000), "8.0k")

    def test_uptime_is_compact(self):
        self.assertEqual(uni.human_uptime(90), "1m")
        self.assertEqual(uni.human_uptime(3700), "1h 1m")
        self.assertEqual(uni.human_uptime(200000), "2d 7h")


class TestStatePersistence(unittest.TestCase):
    def test_state_is_written_private_and_reread(self):
        with tempfile.TemporaryDirectory() as tmp:
            uni.STATE_DIR = tmp
            uni.STATE_PATH = os.path.join(tmp, "state.json")
            uni.write_state({"schema": 1, "ok": True, "wan": {"up": True}})
            mode = os.stat(uni.STATE_PATH).st_mode & 0o777
            # The state file is an inventory of the home network.
            self.assertEqual(mode, 0o600)
            self.assertTrue(uni.read_state()["ok"])

    def test_error_state_keeps_the_original_reading_age(self):
        # Stamping "now" on a failed poll made week-old data report itself as
        # "updated 0m ago".
        with tempfile.TemporaryDirectory() as tmp:
            uni.STATE_DIR, uni.STATE_PATH = tmp, os.path.join(tmp, "state.json")
            old_time = time.time() - 86400
            uni.write_state({"updatedAt": old_time, "wan": {"up": True}})
            state = uni.error_state(
                uni.UniFi({"host": "h", "apiKey": "k"}), "cannot reach h")
            self.assertEqual(state["updatedAt"], old_time)
            self.assertGreater(state["lastAttemptAt"], old_time)

    def test_error_state_preserves_last_good_reading(self):
        with tempfile.TemporaryDirectory() as tmp:
            uni.STATE_DIR = tmp
            uni.STATE_PATH = os.path.join(tmp, "state.json")
            uni.write_state({"wan": {"up": True, "ip": "203.0.113.42"},
                             "devices": {"total": 3}})
            api = uni.UniFi({"host": "unifi.example", "apiKey": "k"})
            state = uni.error_state(api, "cannot reach unifi.example")
            self.assertFalse(state["ok"])
            self.assertTrue(state["stale"])
            self.assertEqual(state["wan"]["ip"], "203.0.113.42")
            self.assertEqual(state["devices"]["total"], 3)
            self.assertIn("cannot reach", state["alerts"][0])

    def test_error_state_flags_missing_configuration(self):
        # No host/key means "not set up", which the panel renders as a setup
        # card rather than as an internet outage.
        with tempfile.TemporaryDirectory() as tmp:
            uni.STATE_DIR, uni.STATE_PATH = tmp, os.path.join(tmp, "state.json")
            blank = uni.error_state(uni.UniFi({}), "no host configured")
            self.assertFalse(blank["configured"])
            ready = uni.error_state(
                uni.UniFi({"host": "h", "apiKey": "k"}), "cannot reach h")
            self.assertTrue(ready["configured"])

    def test_read_state_missing_file_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            uni.STATE_PATH = os.path.join(tmp, "nope.json")
            self.assertEqual(uni.read_state(), {})


class TestConfigAndDaemonSafety(unittest.TestCase):
    def test_api_key_env_override_is_not_honoured(self):
        # A full-admin credential in the environment is readable in
        # /proc/*/environ and inherited by every spawned process.
        os.environ["UNIFI_API_KEY"] = "leaked-via-environment"
        try:
            self.assertNotEqual(uni.load_config().get("apiKey"),
                                "leaked-via-environment")
        finally:
            del os.environ["UNIFI_API_KEY"]

    def test_api_key_file_override_is_honoured(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "key")
            with open(path, "w") as fh:
                fh.write("from-a-file\n")
            os.environ["UNIFI_API_KEY_FILE"] = path
            try:
                self.assertEqual(uni.load_config()["apiKey"], "from-a-file")
            finally:
                del os.environ["UNIFI_API_KEY_FILE"]

    def test_error_state_tolerates_a_missing_client(self):
        # The daemon can fail before it constructs one (unreadable config).
        state = uni.error_state(None, "configuration unreadable")
        self.assertFalse(state["ok"])
        self.assertFalse(state["configured"])
        self.assertEqual(state["alerts"], ["configuration unreadable"])


class TestMacValidation(unittest.TestCase):
    def test_common_formats_normalise(self):
        for value in ("AA:BB:CC:DD:EE:FF", "aa-bb-cc-dd-ee-ff", "aabbccddeeff",
                      "  aa:bb:cc:dd:ee:ff  "):
            self.assertEqual(uni.normalise_mac(value), "aa:bb:cc:dd:ee:ff")

    def test_a_name_is_rejected_rather_than_posted(self):
        # UniFi answers 200 for a MAC that matches nothing, so an unvalidated
        # name looked like a successful block that silently did nothing.
        with self.assertRaises(uni.UniFiError) as ctx:
            uni.normalise_mac("laptop")
        self.assertIn("not a MAC address", str(ctx.exception))
        self.assertIn("clients", str(ctx.exception))

    def test_malformed_values_are_rejected(self):
        for value in ("", "aa:bb:cc:dd:ee", "aa:bb:cc:dd:ee:ff:00", "zz:bb:cc:dd:ee:ff",
                      None, "192.168.1.5"):
            with self.assertRaises(uni.UniFiError):
                uni.normalise_mac(value)


class TestHostValidation(unittest.TestCase):
    def test_accepts_real_addresses(self):
        for value in ("192.168.1.9", "192.168.1.9:8443", "unifi.lan",
                      "unifi.example.com", "[fe80::1]", "[fe80::1]:8443"):
            self.assertTrue(uni.HOST_RE.match(value), value)

    def test_rejects_urls_and_paths(self):
        for value in ("user@evil.example", "192.168.1.9/network", "a b", ""):
            self.assertFalse(uni.HOST_RE.match(value), value)


class TestClient(unittest.TestCase):
    def test_scheme_is_stripped_from_host(self):
        self.assertEqual(uni.UniFi({"host": "https://192.168.1.1/"}).host, "192.168.1.1")
        self.assertEqual(uni.UniFi({"host": "http://unifi.lan"}).host, "unifi.lan")

    def test_missing_credentials_raise_actionable_errors(self):
        with self.assertRaises(uni.UniFiError) as ctx:
            uni.UniFi({"host": "", "apiKey": ""}).legacy("stat/health")
        self.assertIn("setup", str(ctx.exception))
        with self.assertRaises(uni.UniFiError) as ctx:
            uni.UniFi({"host": "h", "apiKey": ""}).legacy("stat/health")
        self.assertIn("API key", str(ctx.exception))

    def test_site_defaults(self):
        self.assertEqual(uni.UniFi({"host": "h", "apiKey": "k"}).site, "default")
        self.assertEqual(uni.UniFi({"host": "h", "apiKey": "k", "site": "alt"}).site, "alt")


if __name__ == "__main__":
    unittest.main(verbosity=2)
