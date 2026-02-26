from datetime import datetime

import uvicorn
from fastapi import FastAPI

from monsta import StatusReporter

app = FastAPI()

mon = StatusReporter(endpoint="/api/v1/state")
app.include_router(mon.router)

mon.publish(lambda: {"now": datetime.now().isoformat()})

# Run service
uvicorn.run(app, host="127.0.0.1", port=4242, reload=False)
