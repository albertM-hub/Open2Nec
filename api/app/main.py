from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routes import files, optimize, pattern, presets, simulate, validate

app = FastAPI(title="Open2Nec API", version="0.1.0")

# Le front Vite tourne sur 5173 en développement
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(simulate.router)
app.include_router(pattern.router)
app.include_router(presets.router)
app.include_router(files.router)
app.include_router(validate.router)
app.include_router(optimize.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
