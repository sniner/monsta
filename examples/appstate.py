"""
Example showing how to use AppState for structured monitoring.

AppState lets you declare metrics as class attributes using descriptor fields
(SlidingWindow, EWMA, RunningStats) and plain instance attributes side by side.
Because AppState.__call__() returns to_dict(), it integrates transparently with
mon.publish() / AsyncStatusReporter.publish() as a state callback.

Run:
    uv run python examples/appstate.py
Check:
    curl http://localhost:4242/mon/v1/state
"""

import threading
import time

import uvicorn
from fastapi import FastAPI

from monsta import EWMA, AppState, LeakyBucket, RunningStats, SlidingWindow, StatusReporter

# ---------------------------------------------------------------------------
# Define the application state
# ---------------------------------------------------------------------------


class MyAppState(AppState):
    # Requests per minute (sliding-window counter)
    request_rate = SlidingWindow(window=60.0)

    # Exponentially-weighted moving average of CPU usage (0–100 %)
    cpu_usage = EWMA(alpha=0.1)

    # Running mean / stddev of response latency in milliseconds
    latency = RunningStats()

    # Token-bucket rate limiter (class attribute – LeakyBucket is a proper descriptor)
    rate_limiter = LeakyBucket(capacity=100, leak_rate=10)

    # Simple string value – converted to ScalarField automatically
    status: str = "starting"


# ---------------------------------------------------------------------------
# FastAPI app + monitoring setup
# ---------------------------------------------------------------------------

app = FastAPI()
state = MyAppState()

mon = StatusReporter(update_holdoff=0.1)
app.include_router(mon.router)

# Pass the AppState instance directly – it's callable, so StatusReporter
# treats it as a state callback and calls state() on every update cycle.
mon.publish(state)


# ---------------------------------------------------------------------------
# Request handler
# ---------------------------------------------------------------------------


@app.get("/")
def root():
    t0 = time.monotonic()

    # Gate the request through the rate limiter
    if not state.rate_limiter.request():
        return {"error": "rate limit exceeded"}

    # Simulate work
    time.sleep(0.005)

    elapsed_ms = (time.monotonic() - t0) * 1000

    # Update metrics – the descriptor __set__ routes values to the right impl
    state.request_rate = 1  # count one hit in the sliding window
    state.cpu_usage = 20.0  # fake CPU reading
    state.latency = elapsed_ms  # add a latency sample
    state.status = "running"

    return {"message": "Hello World", "latency_ms": round(elapsed_ms, 2)}


# ---------------------------------------------------------------------------
# Background thread that simulates periodic CPU reads
# ---------------------------------------------------------------------------


def _cpu_poller():
    import random

    while True:
        state.cpu_usage = random.uniform(10, 80)
        time.sleep(2)


threading.Thread(target=_cpu_poller, daemon=True).start()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=4242, reload=False)
