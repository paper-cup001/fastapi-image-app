from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()

# templatesディレクトリへのパスを設定
templates = Jinja2Templates(directory="templates")

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """
    ログインページを返す。
    """
    return templates.TemplateResponse("login.html", {"request": request})


@router.get("/photographer/scan_qr", response_class=HTMLResponse)
async def photographer_scan_qr_page(request: Request):
    """
    撮影者がログイン後に表示するQRコードスキャン待機ページを返す。
    """
    return templates.TemplateResponse("photographer/scan_qr.html", {"request": request})
