from fastapi import APIRouter

def build_router(engine):
    r = APIRouter()

    @r.get("/healthz")
    async def health():
        return {"ok": True}

    return r
