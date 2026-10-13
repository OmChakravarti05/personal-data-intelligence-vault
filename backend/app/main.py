from fastapi import FastAPI

from app.api import auth, documents, pii, search

app = FastAPI(title="Personal Data Intelligence Vault", version="0.1.0")
app.include_router(auth.router)
app.include_router(documents.router)
app.include_router(pii.router)
app.include_router(search.router)


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok"}



from app.api import chat
app.include_router(chat.router)

from app.api import stats
app.include_router(stats.router)

from app.api import audit_log
app.include_router(audit_log.router)

from app.api import shares
app.include_router(shares.router)

import app.api.system as system
app.include_router(system.router)
