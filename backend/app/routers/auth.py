from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..metrics import LOGINS
from ..models import User
from ..schemas import RegisterIn, RoleIn, TokenOut, UserOut
from ..security import create_access_token, get_current_user, hash_password, require_roles, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])
users_router = APIRouter(prefix="/api/users", tags=["users"])


@router.post("/register", response_model=TokenOut, status_code=201)
def register(body: RegisterIn, db: Session = Depends(get_db)):
    email = body.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "Email already registered")
    first = (db.scalar(select(func.count()).select_from(User)) or 0) == 0
    user = User(email=email, name=body.name, password_hash=hash_password(body.password), role="admin" if first else "analyst")
    db.add(user)
    db.commit()
    db.refresh(user)
    return TokenOut(access_token=create_access_token(user), user=UserOut.model_validate(user))


@router.post("/login", response_model=TokenOut)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == form.username.lower()))
    if not user or not verify_password(form.password, user.password_hash):
        LOGINS.labels("failure").inc()
        raise HTTPException(401, "Incorrect email or password")
    LOGINS.labels("success").inc()
    return TokenOut(access_token=create_access_token(user), user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@users_router.get("", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.scalars(select(User).order_by(User.id)).all()


@users_router.patch("/{user_id}/role", response_model=UserOut)
def set_role(user_id: int, body: RoleIn, db: Session = Depends(get_db), _: User = Depends(require_roles("admin"))):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    user.role = body.role
    db.commit()
    return user
