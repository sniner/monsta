"""
Asynchronous tests for Monsta AsyncStatusReporter.

This module contains all asynchronous tests for the AsyncStatusReporter class,
including async state management and lifecycle testing.
"""

import unittest

from monsta.aiomon import AsyncStatusReporter


class TestAsyncStatusReporter(unittest.IsolatedAsyncioTestCase):
    """Test AsyncStatusReporter functionality."""

    async def test_async_state_methods(self):
        """Test async state methods without starting server."""
        # Create a test instance
        test_mon = AsyncStatusReporter()

        # Test async state setting with direct data
        await test_mon.publish({"test": "async_data"})
        with test_mon._sync_agent._state_lock:
            self.assertEqual(test_mon._sync_agent._state.state["test"], "async_data")

        # Test async state setting with async callback
        async def get_async_state():
            return {"async_callback": True, "value": 42}

        await test_mon.publish(get_async_state)
        with test_mon._sync_agent._state_lock:
            self.assertTrue(test_mon._sync_agent._state.state["async_callback"])
            self.assertEqual(test_mon._sync_agent._state.state["value"], 42)

        # Test async state setting with sync callback
        def get_sync_state():
            return {"sync_callback": True}

        await test_mon.publish(get_sync_state)
        with test_mon._sync_agent._state_lock:
            self.assertTrue(test_mon._sync_agent._state.state["sync_callback"])

    async def test_async_start_stop_lifecycle(self):
        """Test async start/stop lifecycle management."""
        test_mon = AsyncStatusReporter()

        # Test that async start sets up the update task
        await test_mon.start(state={"initial": "state"})
        self.assertIsNotNone(test_mon._async_update_task)

        # Test async stop cleans up the update task
        await test_mon.stop()
        self.assertIsNone(test_mon._async_update_task)

        # Test multiple start/stop cycles
        await test_mon.start()
        await test_mon.stop()
        self.assertIsNone(test_mon._async_update_task)


if __name__ == "__main__":
    unittest.main()
