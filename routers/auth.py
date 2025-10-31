from fastapi import APIRouter, Depends, HTTPException, status, Response, Form
from fastapi.responses import RedirectResponse
from pymongo.database import Database
from datetime import timedelta

from auth import verify_password, create_access_token, ACCESS_TOKEN_EXPIRE_MINUTES
from crud.user_crud import get_user_by_email
from db import db
from schemas import User

router = APIRouter()

@router.post("/token")
async def login_for_access_token(response: Response, username: str = Form(...), password: str = Form(...), db: Database = Depends(lambda: db)):
    """
    ユーザー名（メールアドレス）とパスワードで認証し、役割に応じたページにリダイレクトする。
    認証成功時、アクセストークンはHTTPOnlyのクッキーにセットされる。
    """
    user = get_user_by_email(db, email=username)
    if not user or not verify_password(password, user.hashed_password):
        # 認証失敗時は、エラーメッセージをクエリパラメータに含めてログインページにリダイレクト
        return RedirectResponse(url="/login?error=Incorrect+email+or+password", status_code=status.HTTP_303_SEE_OTHER)

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.email},
        expires_delta=access_token_expires
    )

    # 役割に応じたリダイレクト先を決定
    if user.role == "system_admin":
        redirect_url = "/system_admin/dashboard"
    elif user.role == "operator":
        redirect_url = "/admin/dashboard"
    elif user.role == "photographer":
        redirect_url = "/photographer/scan_qr"
    else:
        # 不明な役割の場合はエラー
        return RedirectResponse(url="/login?error=Unknown+user+role", status_code=status.HTTP_303_SEE_OTHER)

    # レスポンス（リダイレクト）を先に作成
    redirect_response = RedirectResponse(url=redirect_url, status_code=status.HTTP_303_SEE_OTHER)

    # リダイレクトレスポンスにクッキーを設定
    redirect_response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        max_age=int(access_token_expires.total_seconds()),
        samesite="lax", # または "strict"
        secure=False # 本番環境ではTrueにすべき
    )

    return redirect_response


@router.post("/logout")
async def logout():
    """
    ログアウト処理。クライアントのアクセストークンcookieを削除し、ログインページにリダイレクトする。
    """
    response = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie("access_token")
    return response
