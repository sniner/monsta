from monsta import StatusReporter


def my_app_state() -> dict[str, int]:
    return {"answer": 42}


# Run service, check http://localhost:4242/mon/v1/state
mon = StatusReporter()
mon.start(blocking=True, state=my_app_state)
