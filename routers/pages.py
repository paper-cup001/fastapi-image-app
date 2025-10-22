from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()

# templatesディレクトリへのパスを設定
templates = Jinja2Templates(directory="templates")

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """
    運営者ログインページを返す。
    """
    return templates.TemplateResponse("login.html", {"request": request})
