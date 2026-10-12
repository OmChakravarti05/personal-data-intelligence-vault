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