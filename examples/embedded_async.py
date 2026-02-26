"""
Example showing how to use the monitoring agent with async FastAPI.

This demonstrates the new async capabilities that allow seamless integration
with FastAPI applications without needing external shims or workarounds.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from monsta import AsyncStatusReporter


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize and clean up status reporting."""
    # Create the status reporter with custom endpoint
    app.state.mon = AsyncStatusReporter(endpoint="/api/v1/state")

    # Include the monitoring router in the FastAPI app
    app.include_router(app.state.mon.router)

    # Initialize request counter in app.state (thread-safe by FastAPI)
    app.state.request_count = 0

    # Start the monitoring agent in async mode
    await app.state.mon.start(
        state={"status": "starting", "requests": 0},
        update_interval=15,  # Update every 15 seconds
    )

    yield

    # Clean up monitoring when the app shuts down
    await app.state.mon.stop()


app = FastAPI(lifespan=lifespan)


@app.get("/")
async def root():
    """Main endpoint that updates monitoring state."""
    # Increment counter using FastAPI's thread-safe app.state
    app.state.request_count += 1

    # Update monitoring state asynchronously
    await app.state.mon.publish(
        {
            "status": "running",
            "requests": app.state.request_count,
            "message": "Hello from FastAPI with async monitoring!",
        }
    )

    return {
        "message": "Hello World",
        "requests": app.state.request_count,
        "monitoring": "Check /api/v1/state for monitoring data",
    }


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=4242)
