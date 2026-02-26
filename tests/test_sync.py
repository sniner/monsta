"""
Synchronous tests for Monsta StatusReporter.

This module contains all synchronous tests for the StatusReporter class,
including callback-based state management and passive state updates.
"""

import http.client
import json
import threading
import time
import unittest

from monsta import mon

_test_event = threading.Event()
_test_value = 42


def my_test_state():
    """Test state callback function."""
    global _test_value
    global _test_event
    _test_event.set()
    return {"value": _test_value}


def get_state(client: http.client.HTTPConnection) -> dict:
    """Helper function to get current state from monitoring endpoint."""
    client.request("GET", "/mon/v1/state")
    res = client.getresponse()
    return json.loads(res.read())


# Initialize the monitoring system for tests
mon.UPDATE_HOLDOFF = 0
mon.start(blocking=False, state=my_test_state)
if not _test_event.wait(timeout=1):
    raise Exception("Timeout waiting for initial state update")
time.sleep(0.1)


class TestStatusReporterCallback(unittest.TestCase):
    """Test StatusReporter with callback-based state management."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.client = http.client.HTTPConnection("localhost", mon.DEFAULT_PORT)

    def setUp(self):
        """Set up test fixtures."""
        mon._get_instance()._state_callback = my_test_state

    def test_connection(self):
        """Test that the monitoring endpoint is accessible."""
        self.client.request("GET", "/mon/v1/state")
        res = self.client.getresponse()
        self.assertEqual(res.status, 200)

    def test_response_structure(self):
        """Test that the response has the correct structure."""
        state = get_state(self.client)
        self.assertIn("internal", state)
        self.assertIn("state", state)
        self.assertEqual(state["internal"].__class__, dict)
        self.assertEqual(state["state"].__class__, dict)

    def test_state_updates(self):
        """Test that state updates are reflected in the response."""
        global _test_value
        state = get_state(self.client)
        self.assertEqual(state["state"]["value"], _test_value)
        _test_value = 79
        state = get_state(self.client)
        self.assertEqual(state["state"]["value"], _test_value)

    def test_multiple_starts(self):
        """Test that multiple start calls raise exceptions."""
        with self.assertRaises(Exception):
            mon.start(blocking=False, state=my_test_state)


class TestStatusReporterPassive(unittest.TestCase):
    """Test StatusReporter with passive state management."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.client = http.client.HTTPConnection("localhost", mon.DEFAULT_PORT)

    def setUp(self):
        """Set up test fixtures."""
        mon._get_instance()._state_callback = None

    def test_direct_state_setting(self):
        """Test direct state setting via publish method."""
        mon.publish({"value": 24, "name": "abc"})
        state = get_state(self.client)
        self.assertEqual(state["state"]["value"], 24)
        self.assertEqual(state["state"]["name"], "abc")

    def test_internal_state_maintenance(self):
        """Test that internal state is properly maintained."""
        state = get_state(self.client)
        self.assertIn("uptime", state["internal"])
        self.assertIsInstance(state["internal"]["uptime"], int)
        self.assertGreaterEqual(state["internal"]["uptime"], 0)

    def test_state_persistence(self):
        """Test that state persists across multiple calls."""
        # Test that state persists across multiple calls
        test_data = {"counter": 1, "status": "testing"}
        mon.publish(test_data)

        # First call
        state1 = get_state(self.client)
        self.assertEqual(state1["state"]["counter"], 1)

        # Second call should return same data
        state2 = get_state(self.client)
        self.assertEqual(state2["state"]["counter"], 1)
        self.assertEqual(state1["state"], state2["state"])

    def test_invalid_state_handling(self):
        """Test handling of invalid state types."""
        mon.publish("invalid_string_state")  # type: ignore
        state = get_state(self.client)
        self.assertEqual(state["state"], {})

    def test_empty_state_handling(self):
        """Test handling of empty state."""
        mon.publish({})
        state = get_state(self.client)
        self.assertEqual(state["state"], {})
        self.assertIn("internal", state)


if __name__ == "__main__":
    unittest.main()
