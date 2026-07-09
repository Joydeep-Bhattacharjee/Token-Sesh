"""FastAPI app entrypoint."""

from fastapi import FastAPI

from app.database import Base, engine
from app.errors import register_error_handlers
from app.routers import admin, auth, bookings, health, rooms

Base.metadata.create_all(bind=engine)

app = FastAPI(title="CoWork")
register_error_handlers(app)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(rooms.router)
app.include_router(bookings.router)
app.include_router(admin.router)
