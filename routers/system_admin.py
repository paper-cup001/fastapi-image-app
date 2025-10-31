from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from dependencies import get_current_system_admin
from schemas import User

router = APIRouter()
templates = Jinja2Templates(directory="templates")

@router.get("/dashboard", response_class=HTMLResponse)
async def show_system_admin_dashboard(request: Request, current_user: User = Depends(get_current_system_admin)):
    """
    システム管理者用のダッシュボードページを表示する。
    このエンドポイントは、システム管理者ロールを持つユーザーのみがアクセスできる。
    """
    return templates.TemplateResponse("system_admin/dashboard.html", {"request": request, "user": current_user})

@router.get("/users/me", response_model=User)
async def read_users_me(current_user: User = Depends(get_current_system_admin)):
    """
    現在ログインしているシステム管理者の情報を返す。
    """
    return current_user
