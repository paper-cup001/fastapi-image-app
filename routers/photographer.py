# photographer.py
# gourp_idをURLに付加するには、https://your-domain.com/upload?group_id=buyer_123
# などの形式でリクエストを送信してください。
# 画像のトリミングや保存処理は別のモジュール(image_processing.py)に分離しています。
# このコードは、画像のアップロード、トリミング、サムネイル生成、MongoDBへの保存を行います。
# MongoDBの接続情報や画像の一時保存ディレクトリは適宜変更してください。
# 注意: このコードはFastAPIとMongoDBを使用しています。 
import os
import logging
import io
import json
import base64
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, File, UploadFile, Form, Body, Request
from fastapi.responses import JSONResponse, HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from pymongo import MongoClient
import gridfs
from PIL import Image

from services.image_processing import process_image  # トリミングなどの処理
from services.dummy_image import replace_white_with_color  # ダミー画像処理

from db import db, collection, fs # MongoDBの設定をdb.pyからインポート
from zoneinfo import ZoneInfo  # すでにインポート済み

router = APIRouter()
templates = Jinja2Templates(directory="templates")


# 一時的にファイル名を保持（group_id単位）
TEMP_IMAGES = {}

@router.get("/upload", response_class=HTMLResponse)
async def photographer_upload(request: Request):
    return templates.TemplateResponse("photographer/upload.html", {"request": request})


@router.post("/temp_upload")
async def temp_upload(
    file: UploadFile = File(...),
    group_id: str = Form(...),
    user_short_id: str = Form(None),
    source_page: str = Form(None) # source_page を追加
):
    try:
        logging.info(f"Received upload from source_page: {source_page}")
        test_mode = os.getenv("TEST_MODE", "False").lower() == "true"

        # テストモードの場合は、アップロードされた画像は即座に廃棄され、ダミー画像が返されます。
        if test_mode:
            # アップロード画像は即廃棄
            await file.read()  # 読み捨て            
            dummy_image_path = "static/dummy_image.png"
            # ここでダミー画像を読み込む
            processed_image = replace_white_with_color(dummy_image_path , user_short_id)

            img_pil = Image.open(io.BytesIO(processed_image))
            buffer = io.BytesIO()
            img_pil.save(buffer, format="JPEG")
            buffer.seek(0)

        # テストモードでない場合
        else:
            contents = await file.read()
            # source_page が 'upload_old' の場合のみ image_processing を呼び出す
            if source_page == "upload_old":
                processed_image, error_message = process_image(contents, 0, 0, "auto", "127.0.0.1")
                if processed_image is None:
                    processed_image = contents
            else: # upload.html など、クライアント側で処理済みの場合はそのまま
                processed_image = contents
        
        img_pil = Image.open(io.BytesIO(processed_image))
        buffer = io.BytesIO()
        img_pil.save(buffer, format="JPEG")
        buffer.seek(0)

        now = datetime.now(ZoneInfo('Asia/Tokyo'))
        filename = f"{group_id}_{user_short_id}_{now.strftime('%Y%m%d%H%M%S')}_{now.strftime('%f')[:2]}.jpg"

        # ダミー画像であっても保存処理を行い、品質やコメントを保存できます。
        fs_id = fs.put(
            buffer,
            filename=filename,
            group_id=group_id,
            user_short_id=user_short_id,
            temporary=True
        )
        if group_id not in TEMP_IMAGES:
            TEMP_IMAGES[group_id] = []
        TEMP_IMAGES[group_id].append(filename)

        buffer.seek(0)
        thumbnail_b64 = base64.b64encode(buffer.getvalue()).decode()

        return {
            "thumbnail": thumbnail_b64,
            "filename": filename,
            "user_short_id": user_short_id,
            "test_mode": test_mode
        }

    except Exception as e:
        import traceback
        traceback.print_exc()  # スタックトレースを標準出力に出す（uvicorn上に表示される）
        return JSONResponse(status_code=500, content={"error": str(e)})



@router.post("/temp_delete")
async def temp_delete(data: dict = Body(...)):
    group_id = data.get("group_id")
    user_short_id = data.get("user_short_id")

    if not group_id or not user_short_id or group_id not in TEMP_IMAGES:
        return JSONResponse(status_code=400, content={"error": "削除対象の画像がありません"})

    filename_to_delete = None
    for filename in reversed(TEMP_IMAGES.get(group_id, [])):
        if f"_{user_short_id}_" in filename:
            filename_to_delete = filename
            break

    if not filename_to_delete:
        return JSONResponse(status_code=400, content={"error": "あなたの画像が見つかりません"})

    TEMP_IMAGES[group_id].remove(filename_to_delete)

    file = fs.find_one({"filename": filename_to_delete})
    if file:
        fs.delete(file._id)

    return {"deleted": filename_to_delete}



@router.post("/finalize_upload")
async def finalize_upload(data: dict = Body(...)):
    group_id = data.get("group_id")
    filenames = data.get("filenames", [])
    user_short_id = data.get("user_short_id")
    quality = data.get("quality", "")
    comment = data.get("comment", [])  # ← 配列で受け取る

    if not group_id:
        return JSONResponse(status_code=400, content={"error": "Invalid params"})

    temp_files = TEMP_IMAGES.get(group_id, [])
    missing_files = [fn for fn in filenames if fn not in temp_files]
    if not filenames or len(missing_files) == len(filenames):
        TEMP_IMAGES[group_id] = []
        return {"success": False, "message": "画像がありません（管理者による削除の可能性）"}

    if missing_files:
        return JSONResponse(status_code=400, content={"error": "一部の画像が削除されました。再撮影してください。"})

    try:
        images = []
        for fn in filenames:
            file = fs.find_one({"filename": fn})
            if file:
                db.fs.files.update_one(
                    {"_id": file._id},
                    {"$set": {"temporary": False}}
                )
                images.append({
                    "filename": fn,
                    "file_id": str(file._id)
                })

        collection.insert_one({
            "group_id": group_id,
            "user_short_id": user_short_id,
            "images": images,
            "title": "",
            "platform": "",
            "description": "",
            "jan_code": "",
            "created_at": datetime.now(ZoneInfo("Asia/Tokyo")).strftime("%Y-%m-%d %H:%M:%S.%f")[:-4],
            "quality": quality,
            "comment": comment,   # ← 配列で保存
            "meta_added": False,
            "db_uploaded": False
        })

        if group_id in TEMP_IMAGES:
            TEMP_IMAGES[group_id] = [f for f in TEMP_IMAGES[group_id] if f not in filenames]
        return {"success": True}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


"""
# 外部からの画像取得用エンドポイント
# 画像の取得はGridFSから行います。filenameは一意である必要があります。
# 画像の取得は、例えば`/images/your_image_filename.jpg`の形式で行います。
もしこの先、複数画像を処理したり、FileMaker連携やn8nのBase64変換・添付処理などを行う場合、次のような機能拡張も視野に入れておくと良いです：
    複数画像に対応する n8nループ処理（images[].filename の配列展開）
    FastAPI 側で file_id 経由の取得エンドポイントも追加しておくと便利（UUIDを隠せる）
    MIMEタイプに応じた動的レスポンス（.png, .jpeg, .webp など）

このコードはextarnel.py を作成したので廃止されます。


@router.get("/images/{filename}")
async def get_image(filename: str):
    file = fs.find_one({"filename": filename})
    if not file:
        return JSONResponse(status_code=404, content={"error": "Image not found"})

    return StreamingResponse(io.BytesIO(file.read()), media_type="image/jpeg")
"""

@router.post("/delete_all_temp_files")
async def delete_all_temp_files():
    try:
        global TEMP_IMAGES
        for group_id in list(TEMP_IMAGES.keys()):
            TEMP_IMAGES[group_id] = []
        return {"success": True}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.get("/temp_list")
async def get_temp_list(group_id: str):
    files = TEMP_IMAGES.get(group_id, [])
    return {"files": files}
