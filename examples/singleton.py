import monsta


def my_app_state() -> dict[str, int]:
    return {"answer": 42}


# Run service, check http://localhost:4242/mon/v1/state
monsta.start(blocking=True, state=my_app_state)
