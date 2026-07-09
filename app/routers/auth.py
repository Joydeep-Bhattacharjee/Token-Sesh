"""Auth routes: register, login, refresh, logout."""

import threading

from fastapi import APIRouter, Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import auth
from app.database import get_db
from app.errors import AppError
from app.models import Organization, User
from app.schemas import LoginRequest, RefreshRequest, RegisterRequest

router = APIRouter(prefix="/auth")

_register_lock = threading.Lock()
_bearer = HTTPBearer(auto_error=False)


@router.post("/register")
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    with _register_lock:
        org = db.query(Organization).filter(Organization.name == payload.org_name).first()
        if org is None:
            org = Organization(name=payload.org_name)
            db.add(org)
            db.flush()
            role = "admin"
        else:
            role = "member"

        existing = (
            db.query(User)
            .filter(User.org_id == org.id, User.username == payload.username)
            .first()
        )
        if existing is not None:
            db.rollback()
            raise AppError(409, "USERNAME_TAKEN", "Username already taken in this organization")

        user = User(
            org_id=org.id,
            username=payload.username,
            hashed_password=auth.hash_password(payload.password),
            role=role,
        )
        db.add(user)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise AppError(409, "USERNAME_TAKEN", "Username already taken in this organization")

    return {
        "user_id": user.id,
        "org_id": org.id,
        "username": user.username,
        "role": user.role,
    }


@router.post("/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    org = db.query(Organization).filter(Organization.name == payload.org_name).first()
    user = None
    if org is not None:
        user = (
            db.query(User)
            .filter(User.org_id == org.id, User.username == payload.username)
            .first()
        )
    if user is None or not auth.verify_password(payload.password, user.hashed_password):
        raise AppError(401, "INVALID_CREDENTIALS", "Invalid credentials")
    return {
        "access_token": auth.create_access_token(user),
        "refresh_token": auth.create_refresh_token(user),
        "token_type": "bearer",
    }


@router.post("/refresh")
def refresh(payload: RefreshRequest, db: Session = Depends(get_db)):
    claims = auth.decode_token(payload.refresh_token)
    if claims.get("type") != "refresh":
        raise AppError(401, "INVALID_TOKEN", "Not a refresh token")
    jti = claims.get("jti", "")
    if not jti or not auth.consume_refresh_jti(jti, float(claims.get("exp", 0))):
        raise AppError(401, "INVALID_TOKEN", "Refresh token already used or invalid")
    try:
        user_id = int(claims.get("sub", ""))
    except (TypeError, ValueError):
        raise AppError(401, "INVALID_TOKEN", "Invalid subject claim")
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise AppError(401, "INVALID_TOKEN", "Unknown user")
    return {
        "access_token": auth.create_access_token(user),
        "refresh_token": auth.create_refresh_token(user),
        "token_type": "bearer",
    }


@router.post("/logout")
def logout(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
):
    if credentials is None or not credentials.credentials:
        raise AppError(401, "INVALID_TOKEN", "Missing bearer token")
    claims = auth.decode_token(credentials.credentials)
    if claims.get("type") != "access":
        raise AppError(401, "INVALID_TOKEN", "Not an access token")
    jti = claims.get("jti", "")
    if not jti or auth.is_access_jti_revoked(jti):
        raise AppError(401, "INVALID_TOKEN", "Token has been invalidated")
    auth.revoke_access_jti(jti, float(claims.get("exp", 0)))
    return {"detail": "Logged out"}
