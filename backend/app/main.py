from fastapi import FastAPI

from app.api import auth, documents

app = FastAPI(title="Personal Data Intelligence Vault", version="0.1.0")
app.include_router(auth.router)
app.include_router(documents.router)


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok"}