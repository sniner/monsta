from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any, Callable, Mapping, Optional, Union

from fastapi import APIRouter

from .mon import (
    DEFAULT_ENDPOINT,
    UPDATE_HOLDOFF,
    InternalState,
    MonitoringState,
    StateCallback,
    StatusReporter,
    _now,
)

_logger = logging.getLogger(__name__)

AsyncStateCallback = Callable[[], Any]
AsyncStateType = Union[AsyncStateCallback, StateCallback, Mapping]


class AsyncStatusReporter:
    """Async version of StatusReporter for use with FastAPI and other async frameworks.

    This class provides the same status reporting functionality as StatusReporter but with
    native async/await support, making it ideal for FastAPI applications.
    """

    def __init__(
        self, *, endpoint: Optional[str] = None, update_holdoff: float = UPDATE_HOLDOFF
    ):
        """Initialize an async status reporter.

        Args:
            endpoint: Custom endpoint path for the status API
        """
        self._endpoint_path = endpoint or DEFAULT_ENDPOINT

        # Create a synchronous StatusReporter for state management
        self._sync_agent = StatusReporter(endpoint=endpoint, update_holdoff=update_holdoff)

        # Async-specific components
        self._async_state_callback: Optional[AsyncStateCallback] = None
        self._async_update_task: Optional[asyncio.Task] = None

        # Add async endpoint to router
        self.router = APIRouter()
        self.router.add_api_route(
            path=self._endpoint_path,
            endpoint=self._async_api_endpoint,
            methods=["GET"],
            response_model=MonitoringState,
        )

    def reset(self) -> None:
        """Reset the monitoring agent to its initial state."""
        self._sync_agent.reset()

    async def publish(self, state: AsyncStateType) -> None:
        """Set the application state asynchronously.

        Args:
            state: Either a callable that returns state data (can be async),
                   or a mapping/dictionary containing the state data directly

        Examples:
            # Direct state setting
            await agent.publish({"status": "running", "count": 42})

            # Using an async callback function
            async def get_current_state():
                return {"status": "running", "count": await get_count()}
            await agent.publish(get_current_state)

            # Using a sync callback function
            def get_current_state():
                return {"status": "running", "count": get_count()}
            await agent.publish(get_current_state)
        """
        if inspect.iscoroutinefunction(state):
            self._async_state_callback = state
            self._sync_agent._state_callback = None
            _state = await state()
            _logger.debug("Async state callback registered and executed")
            self._sync_agent._set_state(_state)
        else:
            self._async_state_callback = None
            self._sync_agent.publish(state)

    async def _update_state_async(self) -> None:
        """Update the monitoring state if sufficient time has passed.

        This method implements rate-limiting to prevent excessive state updates.
        Only updates the state if UPDATE_HOLDOFF seconds have passed since
        the last update.
        """

        if self._async_state_callback:
            now = _now()
            if self._sync_agent._is_throttled(now):
                return
            try:
                self._sync_agent._update_internal_state(now)
                _state = await self._async_state_callback()
                self._sync_agent._set_state(_state)
            except ValueError as ve:
                _logger.error("Invalid state value during async update: %s", ve)
            except RuntimeError as re:
                _logger.error("Runtime error during async state update: %s", re)
            except Exception as exc:
                _logger.error("Unexpected error during async state update: %s", exc)
        else:
            self._sync_agent._update_state()

    async def _async_api_endpoint(self) -> MonitoringState:
        try:
            await self._update_state_async()
            with self._sync_agent._state_lock:
                return self._sync_agent._state
        except Exception as exc:
            _logger.error("Failed to provide monitoring status: %s", exc)
            return MonitoringState(internal=InternalState(uptime=self._sync_agent._uptime()))

    async def start(
        self,
        *,
        state: Optional[AsyncStateType] = None,
        update_interval: int = UPDATE_HOLDOFF,
    ) -> None:
        """Start the async monitoring agent.

        Args:
            state: Initial state or callable to get initial state
            update_interval: Interval in seconds for automatic state updates
        """
        try:
            if self._async_update_task is not None and not self._async_update_task.done():
                raise RuntimeError("Monitoring agent already running")

            self.reset()
            await self.publish(state or {})

            # Start the async update task
            self._async_update_task = asyncio.create_task(
                self._periodic_update_async(update_interval)
            )
            _logger.info("Async monitoring agent started successfully")

        except Exception as exc:
            _logger.error("Failed to start async monitoring agent: %s", exc)
            raise

    async def _periodic_update_async(self, interval: int) -> None:
        """Background task for periodic state updates in async mode."""
        try:
            while True:
                await asyncio.sleep(interval)
                await self._update_state_async()
        except asyncio.CancelledError:
            _logger.info("Async update task cancelled")
        except Exception as exc:
            _logger.error("Async update task failed: %s", exc)

    async def stop(self) -> None:
        """Stop the async monitoring agent."""
        try:
            # Cancel async update task if running
            if self._async_update_task:
                self._async_update_task.cancel()
                try:
                    await self._async_update_task
                except asyncio.CancelledError:
                    pass
                self._async_update_task = None
                _logger.info("Async update task cancelled successfully")

            # Reset the sync agent state
            self._sync_agent.reset()
        except RuntimeError as re:
            _logger.error("Runtime error during async agent shutdown: %s", re)
        except Exception as exc:
            _logger.error("Unexpected error during async agent shutdown: %s", exc)
