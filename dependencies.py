from fastapi import Depends, HTTPException, status, Request
from jose import JWTError, jwt
from pymongo.database import Database

from auth import SECRET_KEY, ALGORITHM
from schemas import TokenData, User
from crud.user_crud import get_user_by_email
from db import db # データベースオブジェクトをインポート

# 未ログイン時にリダイレクトを発生させるためのカスタム例外
class NotLoggedInException(Exception):
    pass

async def get_current_user(request: Request, db: Database = Depends(lambda: db)) -> User:
    """
    リクエストのクッキーからJWTを抽出し、現在のユーザーを返す。
    認証に失敗した場合は、NotLoggedInExceptionを発生させる。
    """
    try:
        token = request.cookies.get("access_token")
        if token is None:
            raise NotLoggedInException()

        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise NotLoggedInException()

    except (JWTError, NotLoggedInException):
        # トークンがない、デコードできない、ペイロードが不正、などの場合は
        # すべて未ログイン例外として処理する
        raise NotLoggedInException()

    user = get_user_by_email(db, email=email)
    if user is None:
        # トークンは有効だが、該当するユーザーがDBに存在しない場合
        raise NotLoggedInException()
    
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")

    return user


async def get_current_operator(current_user: User = Depends(get_current_user)) -> User:
    """
    現在のユーザーが運営者（operator）であるかを確認する。
    """
    if current_user.role != "operator":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The user does not have enough privileges",
        )
    return current_user


async def get_current_photographer(current_user: User = Depends(get_current_user)) -> User:
    """
    現在のユーザーが撮影者（photographer）または運営者（operator）であるかを確認する。
    """
    if current_user.role not in ["photographer", "operator"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The user does not have enough privileges for this resource",
        )
    return current_user


async def get_current_system_admin(current_user: User = Depends(get_current_user)) -> User:
    """
    現在のユーザーがシステム管理者（system_admin）であるかを確認する。
    """
    if current_user.role != "system_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The user does not have enough privileges for this resource",
        )
    return current_user
