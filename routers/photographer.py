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

from services.image_processing import process_image, load_and_orient_image_pil
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
    source_page: str = Form(None),
    current_photographer: User = Depends(get_current_photographer)
):
    try:
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

        buffer = io.BytesIO()
        img_pil.save(buffer, format="PNG")
        buffer.seek(0)

        now = datetime.now(ZoneInfo('Asia/Tokyo'))
        filename = f"{group_id}_{photographer_id}_{now.strftime('%Y%m%d%H%M%S%f')}.png"

        fs.put(
            buffer.getvalue(),
            filename=filename,
            group_id=group_id,
            photographer_id=photographer_id,
            temporary=True,
            uploadDate=datetime.utcnow() # Deletion sorting key
        )

        buffer.seek(0)
        thumbnail_b64 = base64.b64encode(buffer.getvalue()).decode()

        return {
            "thumbnail": thumbnail_b64,
            "filename": filename,
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
    filenames = data.get("filenames", [])
    quality = data.get("quality", "")
    comment = data.get("comment", [])
    photographer_id = current_photographer.id

    if not group_id or not filenames:
        return JSONResponse(status_code=400, content={"error": "Invalid params"})

    try:
        images = []
        for fn in filenames:
            # Ensure the file exists and belongs to this user before finalizing
            file = fs.find_one({"filename": fn, "photographer_id": photographer_id, "temporary": True})
            if file:
                db.fs.files.update_one({"_id": file._id}, {"$set": {"temporary": False}})
                images.append({"filename": fn, "file_id": str(file._id)})

        if not images:
             return JSONResponse(status_code=404, content={"error": "登録対象の画像が見つかりませんでした。"})

        collection.insert_one({
            "group_id": group_id,
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