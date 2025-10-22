# main.py

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import os

from dependencies import NotLoggedInException # ★ カスタム例外をインポート

app = FastAPI()  # ← この行がないとエラーになる（エントリーポイント）

# ★ 未ログイン例外のハンドラを登録
@app.exception_handler(NotLoggedInException)
async def not_logged_in_exception_handler(request: Request, exc: NotLoggedInException):
    return RedirectResponse(url="/login")


# テストモードの設定
test_mode = False  # True にするとテストモードになる。その場合、アップロードされた画像は即座に廃棄され、ダミー画像が返されます。
os.environ["TEST_MODE"] = "true" if test_mode else "false"

# ルーターのインポート
from routers import photographer  # ← routers/photographer.py を読み込む
from routers import admin         # ← routers/admin.py を読み込む
from routers import external_api  # ← routers/external_api.py を読み込む
from routers import auth, pages   # ★ 新しいルーターをインポート

# サブルーター登録
app.include_router(photographer.router, prefix="/photographer")
app.include_router(admin.router, prefix="/admin")
app.include_router(external_api.router, prefix="/external_api")
app.include_router(auth.router) # ★ ログインAPIルーターを登録
app.include_router(pages.router) # ★ ログインページ表示ルーターを登録

# ここでCORSミドルウェアを追加
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 本番環境では制限推奨
    allow_methods=["*"],
    allow_headers=["*"],
)

# テンプレートの読み込み先
templates = Jinja2Templates(directory="templates")

# ポータル画面ルート → ログインページへリダイレクト
@app.get("/", response_class=RedirectResponse)
def read_root():
    return RedirectResponse(url="/login")

@app.get("/photographer/upload.html", response_class=HTMLResponse)
def upload_test(request: Request):
    return templates.TemplateResponse("photographer/upload.html", {"request": request})

# temp_images を静的配信。これがないと仮保存画像一覧で画像が表示されない。
app.mount("/temp_images", StaticFiles(directory="temp_images"), name="temp_images")

# ...existing code...
app.mount("/static", StaticFiles(directory="static"), name="static")
# ...existing code...



# これはopencv.jsが利用できない端末のためのupload_old.html
@app.get("/photographer/upload_old.html", response_class=HTMLResponse)
def upload_test(request: Request):
    return templates.TemplateResponse("photographer/upload_old.html", {"request": request})

