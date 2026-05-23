"""FastAPI application — SEC Filings Analytics Platform."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from sec_filings.api.routes import holdings, insiders, screens, search

app = FastAPI(
    title="SEC Filings Analytics Platform",
    description="REST API for SEC EDGAR insider transactions, institutional holdings, and risk-factor analysis.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(insiders.router, prefix="/insiders", tags=["Insiders"])
app.include_router(holdings.router, prefix="/holdings", tags=["Holdings"])
app.include_router(screens.router, prefix="/screen", tags=["Screens"])
app.include_router(search.router, prefix="/search", tags=["Search"])


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}
