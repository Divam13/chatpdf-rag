"""
Auth routes: register, login, get current user.
"""

from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, status, Depends
from bson import ObjectId

from database import users_col
from models import RegisterRequest, LoginRequest, TokenResponse, UserOut
from auth import hash_password, verify_password, create_access_token, get_current_user

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(body: RegisterRequest):
    existing = await users_col().find_one({"email": body.email.lower()})
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")

    user_doc = {
        "email": body.email.lower(),
        "name": body.name,
        "password_hash": hash_password(body.password),
        "created_at": datetime.now(timezone.utc),
    }
    result = await users_col().insert_one(user_doc)
    user_id = str(result.inserted_id)

    token = create_access_token(user_id, body.email.lower())

    return TokenResponse(
        access_token=token,
        user={
            "id": user_id,
            "email": body.email.lower(),
            "name": body.name,
        },
    )


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest):
    user = await users_col().find_one({"email": body.email.lower()})
    if not user or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    user_id = str(user["_id"])
    token = create_access_token(user_id, user["email"])

    return TokenResponse(
        access_token=token,
        user={
            "id": user_id,
            "email": user["email"],
            "name": user["name"],
        },
    )


@router.get("/me", response_model=UserOut)
async def me(current_user: dict = Depends(get_current_user)):
    return UserOut(
        id=current_user["_id"],
        email=current_user["email"],
        name=current_user["name"],
        created_at=current_user["created_at"],
    )
