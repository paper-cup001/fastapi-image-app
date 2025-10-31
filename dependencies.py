from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from pymongo.database import Database

from auth import SECRET_KEY, ALGORITHM
from schemas import TokenData, User
from crud.user_crud import get_user_by_email
from db import db # データベースオブジェクトをインポート

# API用の認証スキーム。トークンURLは後で作成するエンドポイントを指す
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/login/token", auto_error=False)

# 未ログイン時にリダイレクトを発生させるためのカスタム例外
class NotLoggedInException(Exception):
    pass

async def get_current_user(
    request: Request, 
    token: str = Depends(oauth2_scheme), 
    db: Database = Depends(lambda: db)
) -> User:
    """
    リクエストからJWTを抽出し、現在のユーザーを返す。
    認証は2つの方法を試みる:
    1. AuthorizationヘッダーのBearerトークン（APIクライアント用）
    2. 'access_token'クッキー（ブラウザ用）
    認証に失敗した場合は、適切な例外を発生させる。
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    # 1. Bearerトークンを試す
    if token is None:
        # 2. Bearerトークンがなければ、クッキーを試す
        token = request.cookies.get("access_token")
        # クッキーもない場合は、ブラウザ用のリダイレクト例外を発生
        if token is None:
            raise NotLoggedInException()

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            # トークンは存在するがペイロードが不正な場合
            # APIからのアクセスの場合はcredentials_exception、ブラウザからの場合はNotLoggedInException
            is_api_call = "authorization" in request.headers
            raise credentials_exception if is_api_call else NotLoggedInException()

    except JWTError:
        # トークンのデコードに失敗した場合
        is_api_call = "authorization" in request.headers
        raise credentials_exception if is_api_call else NotLoggedInException()

    user = get_user_by_email(db, email=email)
    if user is None:
        # トークンは有効だが、該当するユーザーがDBに存在しない場合
        is_api_call = "authorization" in request.headers
        raise credentials_exception if is_api_call else NotLoggedInException()
    
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
