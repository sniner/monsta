from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Mapping, Optional, Self, Union

import uvicorn
from fastapi import APIRouter, FastAPI
from pydantic import BaseModel, Field

_logger = logging.getLogger(__name__)

UPDATE_HOLDOFF = 5  # seconds: rate limit for state updates
DEFAULT_PORT = 4242
DEFAULT_HOST = "0.0.0.0"

DEFAULT_ENDPOINT = "/mon/v1/state"

StateValue = Mapping[str, Any]
StateCallback = Callable[[], StateValue]
StateSource = Union[StateCallback, StateValue]


class InternalState(BaseModel):
    uptime: int = 0


class MonitoringState(BaseModel):
    # "internal" holds library-generated stats (like uptime)
    internal: InternalState = Field(default_factory=InternalState)
    # "state" holds the application state
    state: StateValue = {}


def _now() -> float:
    return time.monotonic()


class StatusReporter:
    def __init__(
        self, *, endpoint: Optional[str] = None, update_holdoff: float = UPDATE_HOLDOFF
    ):
        self._state: MonitoringState = MonitoringState()
        self._state_lock: threading.RLock = threading.RLock()
        self._state_callback: Optional[StateCallback] = None
        self._update_time: float = 0.0
        self._update_holdoff = update_holdoff
        self._startup_time: float = _now()

        self._worker_thread: Optional[threading.Thread] = None
        self._uvicorn_server: Optional[uvicorn.Server] = None

        self.router = APIRouter()
        self.router.add_api_route(
            path=endpoint or DEFAULT_ENDPOINT,
            endpoint=self._api_endpoint,
            methods=["GET"],
            response_model=MonitoringState,
        )

    def reset(self) -> None:
        """Reset the monitoring agent to its initial state.

        Clears all state variables and resets timers, but does not stop
        any running threads. Use stop() method to stop the monitoring agent.

        Note: This method does NOT kill the monitoring thread.
        Use stop() or restart() for thread management.
        """
        with self._state_lock:
            self._state = MonitoringState()
            self._update_time = 0.0
            self._startup_time = _now()
        _logger.debug("State reset")

    def _set_state(self, state: StateValue) -> None:
        """Internal method to update the state with thread safety.

        Args:
            state: The state data to set, as a mapping/dictionary
        """
        with self._state_lock:
            self._state.state = state
        _logger.debug("State updated: %r", state)

    def publish(self, state: StateSource) -> Self:
        """Set the application state.

        Args:
            state: Either a callable that returns state data, or a mapping/dictionary
                   containing the state data directly

        Returns:
            Self: Returns self for method chaining

        Examples:
            # Direct state setting
            agent.publish({"status": "running", "count": 42})

            # Using a callback function
            def get_current_state():
                return {"status": "running", "count": get_count()}
            agent.publish(get_current_state)
        """
        _state: Mapping[str, Any] = {}
        if callable(state):
            _state = state()
            with self._state_lock:
                self._state_callback = state
            _logger.debug("State callback registered and executed")
        else:
            with self._state_lock:
                self._state_callback = None
            if isinstance(state, Mapping):
                _state = dict(state)
            else:
                _logger.warning("Unsupported state value: %r", state)
        self._set_state(_state)
        return self

    def _uptime(self, now: Optional[float] = None) -> int:
        return int((now or _now()) - self._startup_time)

    def _update_internal_state(self, now: Optional[float] = None) -> None:
        """Update the internal state with global monitoring information.

        Updates system-level monitoring data like uptime.
        """
        try:
            self._state.internal.uptime = self._uptime(now)
        except Exception as exc:
            _logger.error("Failed to update internal state: %s", exc)

    def _is_throttled(self, now: float) -> bool:
        with self._state_lock:
            if now - self._update_time < self._update_holdoff:
                return True
            self._update_time = now
            return False

    def _update_state(self) -> None:
        """Update the monitoring state if sufficient time has passed.

        This method implements rate-limiting to prevent excessive state updates.
        Only updates the state if UPDATE_HOLDOFF seconds have passed since
        the last update.
        """
        now = _now()
        if self._is_throttled(now):
            return
        try:
            callback = None
            with self._state_lock:
                self._update_internal_state(now)
                callback = self._state_callback
            if callback:
                new_state = callback()
                self._set_state(new_state)
        except ValueError as ve:
            _logger.error("Invalid state value during update: %s", ve)
        except RuntimeError as re:
            _logger.error("Runtime error during state update: %s", re)
        except Exception as exc:
            _logger.error("Unexpected error during state update: %s", exc)

    def _api_endpoint(self) -> MonitoringState:
        """Get the current monitoring status.

        Returns the complete monitoring state including both internal
        monitoring data and application state.

        Returns:
            Dict[str, Any]: Dictionary containing 'internal' and 'state' keys

        Note:
            This method is called by the FastAPI endpoint and implements
            error handling to ensure a response is always returned.
        """
        try:
            self._update_state()
            with self._state_lock:
                return self._state
        except Exception as exc:
            _logger.error("Failed to provide monitoring status: %s", exc)
            # Return minimal state even on error
            return MonitoringState(internal=InternalState(uptime=self._uptime()))

    def _worker(
        self,
        host: str,
        port: int,
        log_level: Optional[Union[int, str]] = None,
    ) -> None:
        """Main monitoring worker thread function.

        Starts the FastAPI application with uvicorn server and handles
        the monitoring endpoint.

        Args:
            host: Host address to bind to
            port: Port number to listen on
            log_level: Logging level for uvicorn
        """
        try:
            app = FastAPI()
            app.include_router(self.router)

            config = uvicorn.Config(
                app=app,
                host=host,
                port=port,
                log_level=log_level,
            )
            self._uvicorn_server = uvicorn.Server(config)

            _logger.info("Starting monitoring worker on %s:%d", host, port)

            # Update state once on startup
            self._update_state()

            self._uvicorn_server.run()
        except Exception as exc:
            _logger.error("Monitoring worker failed to start: %s", exc)
            raise

    def _worker_alive(self) -> bool:
        return bool(self._worker_thread and self._worker_thread.is_alive())

    def start(
        self,
        *,
        state: Optional[StateSource] = None,
        host: Optional[str] = None,
        port: Optional[int] = None,
        log_level: Optional[Union[int, str]] = None,
        blocking: bool = False,
        update_holdoff: Optional[float] = None,
    ) -> None:
        try:
            if self._worker_alive():
                raise RuntimeError("Monitoring worker already running")

            if update_holdoff is not None:
                self._update_holdoff = update_holdoff

            self.reset()
            self.publish(state or {})

            actual_host = host or DEFAULT_HOST
            actual_port = port or DEFAULT_PORT

            self._worker_thread = threading.Thread(
                target=self._worker,
                args=(actual_host, actual_port, log_level),
                daemon=True,
            )
            self._worker_thread.start()
            _logger.debug("Monitoring worker started successfully")

            if blocking:
                try:
                    self._worker_thread.join()
                except KeyboardInterrupt:
                    _logger.debug("Received keyboard interrupt, stopping monitoring worker")
                    self.stop()
                    raise
        except Exception as exc:
            _logger.error("Failed to start monitoring worker: %s", exc)
            raise

    def stop(self) -> None:
        try:
            if self._uvicorn_server:
                self._uvicorn_server.should_exit = True
                _logger.debug("Signaled uvicorn server to exit")

            if self._worker_thread:
                self._worker_thread.join(timeout=5)
                if self._worker_thread.is_alive():
                    _logger.warning("Monitoring worker did not terminate within timeout")
                self._worker_thread = None
                _logger.debug("Monitoring worker joined successfully")

            self._uvicorn_server = None
            _logger.debug("Monitoring worker stopped successfully")
        except RuntimeError as re:
            _logger.error("Runtime error during worker shutdown: %s", re)
        except Exception as exc:
            _logger.error("Unexpected error during worker shutdown: %s", exc)


# Singleton instance
_instance: Optional[StatusReporter] = None
_instance_lock = threading.Lock()


def _get_instance() -> StatusReporter:
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = StatusReporter()
    return _instance


def publish(state: StateSource) -> None:
    _get_instance().publish(state)


def start(
    *,
    state: Optional[StateSource] = None,
    host: Optional[str] = None,
    port: Optional[int] = None,
    log_level: Optional[Union[int, str]] = None,
    blocking: bool = False,
    update_holdoff: Optional[float] = None,
) -> None:
    _get_instance().start(
        state=state,
        port=port,
        blocking=blocking,
        host=host,
        log_level=log_level,
        update_holdoff=update_holdoff,
    )


def stop() -> None:
    _get_instance().stop()


def reset() -> None:
    """Reset the global agent state. For testing purposes only."""
    _get_instance().reset()
