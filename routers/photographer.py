import os
import logging
import io
import base64
from datetime import datetime
from typing import List

from fastapi import APIRouter, File, UploadFile, Form, Body, Request, Depends, HTTPException
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from PIL import Image

from services.image_processing import process_image, load_and_orient_image_pil, generate_thumbnail
from services.dummy_image import replace_white_with_color
from db import db, collection, fs
from zoneinfo import ZoneInfo

from dependencies import get_current_photographer
from schemas import User

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/upload", response_class=HTMLResponse)
async def photographer_upload(request: Request, current_photographer: User = Depends(get_current_photographer)):
    return templates.TemplateResponse("photographer/upload.html", {"request": request, "user": current_photographer})


from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse

@router.get("/upload_legacy.html", response_class=HTMLResponse)
async def photographer_upload_legacy(request: Request, current_photographer: User = Depends(get_current_photographer)):
    return templates.TemplateResponse("photographer/upload_legacy.html", {"request": request, "user": current_photographer})


@router.get("/upload_old.html", response_class=HTMLResponse)
async def photographer_upload_old_redirect(request: Request):
    return RedirectResponse(url="/photographer/upload_legacy.html")


@router.post("/temp_upload")
async def temp_upload(
    file: UploadFile = File(...),
    group_id: str = Form(...),
    operator_id: str = Form(None), # operator_idをオプショナルで受け取る
    source_page: str = Form(None),
    current_photographer: User = Depends(get_current_photographer)
):
    try:
        # 運営者IDを決定するロジック
        final_operator_id = operator_id
        if not final_operator_id:
            if current_photographer.role == 'operator':
                final_operator_id = current_photographer.id
            else:
                raise HTTPException(status_code=400, detail="Operator ID is required for photographers")

        test_mode = os.getenv("TEST_MODE", "False").lower() == "true"
        photographer_id = current_photographer.id

        if test_mode:
            await file.read()
            dummy_image_path = "static/dummy_image.png"
            img_pil = load_and_orient_image_pil(replace_white_with_color(dummy_image_path, photographer_id))
        else:
            contents = await file.read()
            if source_page == "upload_old":
                processed_image_bytes, _ = process_image(contents, 0, 0, "auto", "127.0.0.1")
                if processed_image_bytes is None: processed_image_bytes = contents
            else:
                processed_image_bytes = contents
        
            img_pil = load_and_orient_image_pil(processed_image_bytes)

        # フルサイズ画像をGridFSに保存 (JPEG形式、品質90)
        full_image_buffer = io.BytesIO()
        if img_pil.mode == 'RGBA':
            background = Image.new('RGB', img_pil.size, (255, 255, 255))
            background.paste(img_pil, mask=img_pil.split()[3])
            img_pil = background
        elif img_pil.mode != 'RGB':
            img_pil = img_pil.convert('RGB')
        img_pil.save(full_image_buffer, format="JPEG", quality=90)
        full_image_buffer.seek(0)

        now = datetime.now(ZoneInfo('Asia/Tokyo'))
        # 新しいファイル名形式
        full_filename = f"{final_operator_id}_{group_id}_{photographer_id}_{now.strftime('%Y%m%d%H%M%S%f')}_full.jpeg"

        fs.put(
            full_image_buffer.getvalue(),
            filename=full_filename,
            group_id=group_id,
            operator_id=final_operator_id, # メタデータにも追加
            photographer_id=photographer_id,
            temporary=True,
            uploadDate=datetime.utcnow()
        )

        # サムネイル画像を生成しGridFSに保存 (JPEG形式、品質85)
        thumbnail_pil, was_scaled_down = generate_thumbnail(img_pil, max_size=600)
        thumbnail_buffer = io.BytesIO()
        if thumbnail_pil.mode == 'RGBA':
            background = Image.new('RGB', thumbnail_pil.size, (255, 255, 255))
            background.paste(thumbnail_pil, mask=thumbnail_pil.split()[3])
            thumbnail_pil = background
        elif thumbnail_pil.mode != 'RGB':
            thumbnail_pil = thumbnail_pil.convert('RGB')
        thumbnail_pil.save(thumbnail_buffer, format="JPEG", quality=85)
        thumbnail_buffer.seek(0)

        # 新しいファイル名形式
        thumbnail_filename = f"{final_operator_id}_{group_id}_{photographer_id}_{now.strftime('%Y%m%d%H%M%S%f')}_thumb.jpeg"

        fs.put(
            thumbnail_buffer.getvalue(),
            filename=thumbnail_filename,
            group_id=group_id,
            operator_id=final_operator_id, # メタデータにも追加
            photographer_id=photographer_id,
            temporary=True,
            uploadDate=datetime.utcnow(),
            is_thumbnail=True
        )

        thumbnail_buffer.seek(0)
        thumbnail_b64 = base64.b64encode(thumbnail_buffer.getvalue()).decode()

        return {
            "thumbnail": thumbnail_b64,
            "filename": full_filename,
            "thumbnail_filename": thumbnail_filename,
            "is_thumbnail_scaled_down": was_scaled_down
        }

    except Exception as e:
        logging.error(f"Error in temp_upload: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.post("/temp_delete")
async def temp_delete(data: dict = Body(...), current_photographer: User = Depends(get_current_photographer)):
    group_id = data.get("group_id")
    photographer_id = current_photographer.id

    # Find the most recently uploaded temporary file for this user and group
    latest_file = fs.find_one({
        "group_id": group_id,
        "photographer_id": photographer_id,
        "temporary": True
    }, sort=[("uploadDate", -1)])

    if not latest_file:
        return JSONResponse(status_code=404, content={"error": "削除対象の画像が見つかりません"})

    # Delete from GridFS
    fs.delete(latest_file._id)

    return {"deleted": latest_file.filename}

@router.post("/finalize_upload")
async def finalize_upload(data: dict = Body(...), current_photographer: User = Depends(get_current_photographer)):
    group_id = data.get("group_id")
    operator_id = data.get("operator_id") # operator_id を取得 (オプショナル)
    filenames_data = data.get("filenames_data", [])
    quality = data.get("quality", "")
    comment = data.get("comment", [])
    photographer_id = current_photographer.id

    # operator_idが指定されていない場合のロジック
    if not operator_id:
        if current_photographer.role == 'operator':
            # ログインユーザーが運営者なら、自身のIDをoperator_idとして使用
            operator_id = current_photographer.id
        else:
            # 撮影者でoperator_idがない場合はエラー
            return JSONResponse(status_code=400, content={"error": "operator_id is required for photographers"})

    if not group_id or not filenames_data:
        return JSONResponse(status_code=400, content={"error": "Invalid params"})

    try:
        images = []
        for item_data in filenames_data:
            full_filename = item_data.get("filename")
            thumbnail_filename = item_data.get("thumbnail_filename")

            file = fs.find_one({"filename": full_filename, "photographer_id": photographer_id, "temporary": True})
            if file:
                db.fs.files.update_one({"_id": file._id}, {"$set": {"temporary": False}})
                images.append({"filename": full_filename, "thumbnail_filename": thumbnail_filename, "file_id": str(file._id)})
            
            thumb_file = fs.find_one({"filename": thumbnail_filename, "photographer_id": photographer_id, "temporary": True})
            if thumb_file:
                db.fs.files.update_one({"_id": thumb_file._id}, {"$set": {"temporary": False}})

        if not images:
             return JSONResponse(status_code=404, content={"error": "登録対象の画像が見つかりませんでした。"})

        collection.insert_one({
            "group_id": group_id,
            "operator_id": operator_id, # ドキュメントに operator_id を追加
            "photographer_id": photographer_id,
            "images": images,
            "title": "", "platform": "", "description": "", "jan_code": "",
            "created_at": datetime.now(ZoneInfo('Asia/Tokyo')).strftime("%Y-%m-%d %H:%M:%S.%f")[:-4],
            "quality": quality,
            "comment": comment,
            "meta_added": False,
            "db_uploaded": False
        })

        return {"success": True}
    except Exception as e:
        logging.error(f"Error in finalize_upload: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"error": str(e)})

        return {"success": True}
    except Exception as e:
        logging.error(f"Error in finalize_upload: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.get("/temp_list")
async def get_temp_list(group_id: str, current_photographer: User = Depends(get_current_photographer)):
    photographer_id = current_photographer.id
    logging.info("--- temp_list called ---")
    logging.info(f"Searching for group_id: {group_id}")
    logging.info(f"Searching for photographer_id: {photographer_id}")

    query = {
        "group_id": group_id,
        "photographer_id": photographer_id,
        "temporary": True
    }

    # Query GridFS and create a list of filenames
    files_cursor = fs.find(query)
    files = [file.filename for file in files_cursor]
    
    logging.info(f"Found {len(files)} files in GridFS with query: {query}")
    logging.info(f"Returning file list: {files}")
    logging.info("--- temp_list finished ---")
    
    return {"files": files}

@router.get("/users/me", response_model=User)
async def read_users_me(current_user: User = Depends(get_current_photographer)):
    """
    現在ログインしているユーザーの情報を返す。
    """
    return current_user