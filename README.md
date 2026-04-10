# Monsta - Status Reporting REST API for Python Applications

**Monsta** (from "to MONitor application STAte") is a lightweight library for
Python applications that provides a REST API endpoint for exposing application
state and metrics. It's designed for seamless integration with FastAPI.

## Features

- **Simple Integration**: Add monitoring to your application with just a few
  lines of code
- **Async Support**: Native async/await support for FastAPI
- **Thread-Safe**: Built-in thread safety for concurrent access
- **Flexible State Management**: Support for both direct state values and
  callback functions
- **Structured State**: Declarative `AppState` class with built-in metric fields
- **Atomic Updates**: `with state:` context manager for consistent multi-field
  updates
- **Built-in Metrics**: Automatic uptime tracking
- **Customizable**: Configure endpoint paths, ports, and update intervals

## Installation

```bash
pip install monsta
```

## Quick Start

### Basic Usage

```python
from monsta import StatusReporter

# Create status reporter
mon = StatusReporter()

# Set application state
mon.publish({"status": "running", "version": "1.0.0"})

# Start status reporting server (blocking)
mon.start(blocking=True)
```

### FastAPI Integration

```python
from fastapi import FastAPI
from monsta import StatusReporter

app = FastAPI()

# Create and integrate status reporter
mon = StatusReporter(endpoint="/api/v1/monitoring")
app.include_router(mon.router)

# Update state during application lifecycle
mon.publish({"status": "running", "requests": 0})

# Start FastAPI app
# Status reporting will be available at /api/v1/monitoring
```

### Async FastAPI Integration

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from monsta import AsyncStatusReporter

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize status reporting
    app.state.mon = AsyncStatusReporter(endpoint="/api/v1/state")
    app.include_router(app.state.mon.router)
    
    # Start async status reporting
    await app.state.mon.start(state={"status": "starting"})
    
    yield
    
    # Clean up
    await app.state.mon.stop()

app = FastAPI(lifespan=lifespan)

@app.get("/")
async def root():
    # Update status asynchronously
    await app.state.mon.publish({"status": "running", "requests": 1})
    return {"message": "Hello World"}
```

## Structured Monitoring State

For applications that need richer, continuously-updated metrics, Monsta provides
`AppState` – a base class that lets you declare metric fields directly on the
class using Python descriptors. No manual bookkeeping required.

### Defining State

```python
from monsta import (
    AppState, SlidingWindow, PeriodicSum, EWMA,
    RunningStats, SampledWindow, LeakyBucket,
)

class MyState(AppState):
    request_rate = SlidingWindow(window=60)     # requests in the last 60 seconds
    jobs_today   = PeriodicSum()                # counter that resets at midnight
    cpu_usage    = EWMA(alpha=0.1, preset=0.0) # smoothed CPU usage, starts at 0
    latency      = RunningStats()               # mean, stddev, min, max
    active_rps   = SampledWindow(window=5.0)   # decays to 0 if not updated for 5 s
    rate_limiter = LeakyBucket(capacity=100, leak_rate=10)

    api_calls: int = 0
    status: str = "starting"
```

### Using State

```python
state = MyState()

mon = StatusReporter()
mon.publish(state)

state.request_rate += 1     # count one request
state.jobs_today   += 1     # one more job done today
state.cpu_usage    = 73.5    # current CPU %
state.latency      = 42      # latency in ms
state.active_rps   = 120     # holds 120 for 5 s, then decays to 0

state.api_calls += 1
state.status = "degraded"

if not state.rate_limiter.request():
    raise Exception("Rate limit exceeded")
```

`GET /mon/v1/state` will then return:

```json
{
  "internal": {"uptime": 42},
  "state": {
    "request_rate": 15.3,
    "jobs_today": 248.0,
    "cpu_usage": 32.5,
    "latency": {"n": 100, "mean": 45.2, "stddev": 8.1, "min": 10.0, "max": 120.0},
    "active_rps": 120.0,
    "api_calls": 1,
    "status": "degraded",
    "rate_limiter": {"level": 45.0, "capacity": 100, "full": false}
  }
}
```

### Atomic Updates

Use `AppState` as a context manager to guarantee that no partial state is read
while you are updating multiple fields:

```python
with state:
    state.api_calls += 1
    state.status = "degraded"
    state.cpu_usage = 95.0
```

### Field Reference

| Field | Constructor | Assignment | Serialized as |
|---|---|---|---|
| `SlidingWindow` | `SlidingWindow(window=60.0)` | `+= n` to record hits, `=` to overwrite | `float` – rate over the window |
| `PeriodicSum` | `PeriodicSum(reset_at=time(0,0), tz=None)` | `+= n` to record hits, `=` to overwrite | `float` – count since last reset |
| `EWMA` | `EWMA(alpha=0.1, preset=None)` | Feeds a new sample | `float \| None` – current estimate |
| `RunningStats` | `RunningStats()` | Adds a data point | `{"n", "mean", "stddev", "min", "max"}` |
| `SampledWindow` | `SampledWindow(window=60.0, zero=0.0)` | Stores value + timestamp | `float` – value or `zero` after window |
| `LeakyBucket` | `LeakyBucket(capacity, leak_rate)` | n/a – use `.request()` | `{"level", "capacity", "full"}` |

**`SlidingWindow(window)`** – rate counter. Returns how many hits accumulated in
the last `window` seconds, with smooth interpolation at window boundaries. Use
`state.x += n` to record events; `state.x = 0` resets the current bucket. Note
that `+=` is not atomic across threads — for multi-writer counters, serialize
the increment yourself.

**`PeriodicSum(reset_at=time(0,0), tz=None)`** – calendar-aligned counter that
accumulates events and snaps back to zero at a configurable wall-clock time
each day (default local midnight). Useful for "events today", "requests since
midnight". Pass a `ZoneInfo` to pin the reset to a specific timezone. Same
threading caveat as `SlidingWindow`.

**`EWMA(alpha, *, preset=None)`** – exponentially weighted moving average.
`alpha` ∈ `(0, 1]` controls smoothing: values near `0` are very smooth, `1`
means no smoothing. Returns `None` until the first sample arrives, unless
`preset` seeds an initial value.

**`RunningStats()`** – tracks mean, standard deviation, min, and max over all
samples seen. Constant memory regardless of sample count. `min` and `max` are
`0.0` before the first sample.

**`SampledWindow(window, zero=0.0)`** – holds the last assigned value for
`window` seconds, then returns `zero`. Useful for rates or signals that should
decay to zero when no update arrives (e.g. requests-per-second sampled from a
counter).

**`LeakyBucket(capacity, leak_rate)`** – token-bucket rate limiter. The bucket
drains at `leak_rate` tokens/second. Declare as a class attribute like any other
field. Accessing the attribute returns the bucket object; call
`.request(amount=1.0)` to consume tokens – returns `True` if allowed, `False` if
the bucket would overflow. Assignment raises `AttributeError`.

### Inheritance

Child classes inherit all parent fields. A child field with the same name
shadows the parent's field. Each `AppState` instance maintains its own
independent field state.

```python
class BaseState(AppState):
    cpu = EWMA(alpha=0.1)

class ExtendedState(BaseState):
    cpu     = RunningStats()   # overrides BaseState.cpu for this class
    memory  = EWMA(alpha=0.2)
```

---

## API Reference

### StatusReporter

The main synchronous status reporter class.

#### `StatusReporter(endpoint: Optional[str] = None, update_holdoff: float = 5)`

- `endpoint`: Custom endpoint path (default: `/mon/v1/state`)
- `update_holdoff`: Minimum seconds between state refreshes (default: `5`)

#### `publish(state: StateSource) -> Self`

Set the application state.

- `state`: Either a callable that returns state data, or a mapping/dictionary
  containing the state data directly

Returns `self` for method chaining.

**Examples:**
```python
# Direct state setting
reporter.publish({"status": "running", "count": 42})

# Using a callback function
def get_current_state():
    return {"status": "running", "count": get_count()}

reporter.publish(get_current_state)
```

#### `start(*, state=None, host=None, port=None, log_level=None, blocking=False, update_holdoff=None) -> None`

Start the status reporter.

- `state`: Initial state or callable returning state
- `host`: Bind address (default: `"0.0.0.0"`)
- `port`: Port (default: `4242`)
- `log_level`: Logging level passed to uvicorn
- `blocking`: If `True`, blocks until the server stops
- `update_holdoff`: Overrides the constructor value for this run

#### `stop() -> None`

Stop the status reporter and clean up resources.

#### `reset() -> None`

Reset state and timers. Does not stop a running server.

### AsyncStatusReporter

Async version of StatusReporter for use with FastAPI and other async frameworks.

#### `AsyncStatusReporter(endpoint: Optional[str] = None)`

- `endpoint`: Custom endpoint path for the status API

#### `async publish(state: AsyncStateType) -> None`

Set the application state asynchronously.

- `state`: Either a callable that returns state data (can be async), or a
  mapping/dictionary containing the state data directly

**Examples:**
```python
# Direct state setting
await reporter.publish({"status": "running", "count": 42})

# Using an async callback function
async def get_current_state():
    return {"status": "running", "count": await get_count()}
await reporter.publish(get_current_state)

# Using a sync callback function
def get_current_state():
    return {"status": "running", "count": get_count()}
await reporter.publish(get_current_state)
```

#### `async start(*, state: Optional[AsyncStateType] = None, host: Optional[str] = None, port: Optional[int] = None, update_interval: int = 5) -> None`

Start the async status reporter.

- `state`: Initial state or callable to get initial state
- `host`: Host address to bind to (default: `"0.0.0.0"`)
- `port`: Port number to listen on (default: `4242`)
- `update_interval`: Interval in seconds for automatic state updates (default:
  `5`)

#### `async stop() -> None`

Stop the async status reporter.

#### `reset() -> None`

Reset the status reporter to its initial state.

## Singleton Functions

For simple use cases, you can use the singleton functions:

```python
import monsta

# Start monitoring with singleton
monsta.start(state={"status": "running"}, blocking=False)

# Update state
monsta.publish({"status": "running", "requests": 42})

# Stop monitoring
monsta.stop()
```

## Configuration

### Environment Variables

Monsta respects standard uvicorn environment variables for configuration.

### Customization

You can customize the monitoring behavior:

```python
# Custom endpoint
mon = StatusReporter(endpoint="/custom/monitoring/path")

# Custom host and port
mon.start(host="127.0.0.1", port=8080)

# Custom update holdoff (rate-limit for automatic state refreshes)
mon.start(update_holdoff=10.0)  # refresh at most every 10 seconds

# Custom update interval (async only)
await async_mon.start(update_interval=10)  # update every 10 seconds
```

## Monitoring Endpoint

The monitoring endpoint returns a JSON response with the following structure:

```json
{
  "internal": {
    "uptime": 12345
  },
  "state": {
    "status": "running",
    "requests": 42,
    "custom_metrics": {}
  }
}
```

- `internal.uptime`: Automatic uptime tracking in seconds
- `state`: Your application-specific state data

## Examples

See the `examples/` directory for complete working examples:

- `embedded.py`: Basic FastAPI integration
- `embedded_async.py`: Async FastAPI integration
- `singleton.py`: Singleton usage example
- `standalone.py`: Standalone monitoring server
- `appstate.py`: Structured state with `AppState`, `SlidingWindow`, `EWMA`,
  `RunningStats`, `SampledWindow`, and `LeakyBucket`

## License

[BSD 3-Clause License](./LICENSE)

## Support

For issues, questions, or contributions, please open an issue on the GitHub
repository.
