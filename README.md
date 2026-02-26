# Monsta - Status Reporting REST API for Python Applications

**Monsta** (short for "Monitoring State") is a lightweight library for Python applications that provides a REST API endpoint for exposing application state and metrics. It's designed for seamless integration with FastAPI.

## Features

- **Simple Integration**: Add monitoring to your application with just a few lines of code
- **Async Support**: Native async/await support for FastAPI
- **Thread-Safe**: Built-in thread safety for concurrent access
- **Flexible State Management**: Support for both direct state values and callback functions
- **Built-in Metrics**: Automatic uptime tracking (and possibly other internal metrics)
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

## API Reference

### StatusReporter

The main synchronous status reporter class.

#### `StatusReporter(endpoint: Optional[str] = None)`

- `endpoint`: Custom endpoint path for the status API (default: `/mon/v1/state`)

#### `publish(state: StateSource) -> Self`

Set the application state.

- `state`: Either a callable that returns state data, or a mapping/dictionary containing the state data directly

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

#### `start(*, state: Optional[StateSource] = None, host: Optional[str] = None, port: Optional[int] = None, log_level: Optional[Union[int, str]] = None, blocking: bool = False) -> None`

Start the status reporter.

- `state`: Initial state or callable to get initial state
- `host`: Host address to bind to (default: `"0.0.0.0"`)
- `port`: Port number to listen on (default: `4242`)
- `log_level`: Logging level for uvicorn
- `blocking`: If True, blocks until server stops (default: `False`)

#### `stop() -> None`

Stop the status reporter and clean up resources.

#### `reset() -> None`

Reset the status reporter to its initial state.

### AsyncStatusReporter

Async version of StatusReporter for use with FastAPI and other async frameworks.

#### `AsyncStatusReporter(endpoint: Optional[str] = None)`

- `endpoint`: Custom endpoint path for the status API

#### `async publish(state: AsyncStateType) -> None`

Set the application state asynchronously.

- `state`: Either a callable that returns state data (can be async), or a mapping/dictionary containing the state data directly

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
- `update_interval`: Interval in seconds for automatic state updates (default: `5`)

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
mon = MonitoringAgent(endpoint="/custom/monitoring/path")

# Custom host and port
mon.start(host="127.0.0.1", port=8080)

# Custom update interval (async only)
await async_mon.start(update_interval=10)  # Update every 10 seconds
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

## Development

```bash
# Install development dependencies using uv
uv sync --dev

# Run tests
uv run pytest
```

## Project Structure

```
src/monsta/
├── __init__.py          # Main package exports
├── mon.py              # Synchronous StatusReporter implementation
├── aiomon.py           # Async StatusReporter implementation
└── py.typed            # Type annotations

examples/
├── embedded.py         # Basic FastAPI integration example
├── embedded_async.py   # Async FastAPI integration example  
├── singleton.py        # Singleton usage example
└── standalone.py       # Standalone server example

tests/
├── test_sync.py       # Synchronous StatusReporter tests
└── test_async.py      # AsyncStatusReporter tests
```

## License

[BSD 3-Clause License](./LICENSE)

## Support

For issues, questions, or contributions, please open an issue on the GitHub repository.
