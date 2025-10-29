from fastapi import APIRouter, Depends, HTTPException, status, Response
from fastapi.security import OAuth2PasswordRequestForm
from pymongo.database import Database
from datetime import timedelta

from auth import verify_password, create_access_token, ACCESS_TOKEN_EXPIRE_MINUTES
from crud.user_crud import get_user_by_email
from db import db
from schemas import Token, TokenWithRole

router = APIRouter()

@router.post("/token", response_model=TokenWithRole)
async def login_for_access_token(response: Response, form_data: OAuth2PasswordRequestForm = Depends(), db: Database = Depends(lambda: db)):
    """
    ユーザー名（メールアドレス）とパスワードで認証し、アクセストークンを生成して返す。
    トークンはHTTPOnlyのクッキーにもセットされる。
    """
    user = get_user_by_email(db, email=form_data.username)
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.email},
        expires_delta=access_token_expires
    )

    # トークンをHTTPOnlyクッキーに設定
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        max_age=int(access_token_expires.total_seconds()),
        samesite="lax", # または "strict"
        secure=False # 本番環境ではTrueにすべき
    )

    return {"access_token": access_token, "token_type": "bearer", "role": user.role}
