import os
import shutil
import qrcode
import io
import base64
import json
import socket
from typing import List

from fastapi import APIRouter, Form, Request, status, Depends, HTTPException, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pymongo import MongoClient
import gridfs
from bson import ObjectId

from db import db, collection, fs
from dependencies import get_current_operator
from schemas import User, UserCreate
from crud import user_crud

router = APIRouter()
templates = Jinja2Templates(directory="templates")

TEMP_DIR = "temp_images"

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip_address = s.getsockname()[0]
        s.close()
        return ip_address
    except Exception:
        return "localhost"

@router.get("/dashboard", response_class=HTMLResponse)
async def show_qr_form(request: Request, current_operator: User = Depends(get_current_operator)):
    return templates.TemplateResponse("admin/dashboard.html", {"request": request, "user": current_operator})

@router.get("/manage-photographers", response_class=HTMLResponse)
async def show_manage_photographers_page(request: Request, current_operator: User = Depends(get_current_operator)):
    return templates.TemplateResponse("admin/manage_photographers.html", {"request": request, "user": current_operator})


@router.get("/generate_qr", response_class=HTMLResponse)
async def show_generate_qr_form(request: Request, current_operator: User = Depends(get_current_operator)):
    return templates.TemplateResponse("admin/generate_qr.html", {"request": request, "user": current_operator})

@router.post("/generate_qr", response_class=HTMLResponse)
async def generate_qr(request: Request, group_id: str = Form(...), old_phone: bool = Form(False), current_operator: User = Depends(get_current_operator)):
    local_ip = get_local_ip()
    endpoint = "upload_old.html" if old_phone else "upload.html"
    url = f"http://{local_ip}:8000/photographer/{endpoint}?group_id={group_id}"
    
    qr = qrcode.make(url)
    buf = io.BytesIO()
    qr.save(buf, format="PNG")
    qr_base64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    
    return templates.TemplateResponse("admin/generate_qr.html", {
        "request": request,
        "qr_code": qr_base64,
        "group_id": group_id,
        "url": url,
        "old_phone_checked": old_phone,
        "user": current_operator
    })

@router.get("/force_reset", response_class=HTMLResponse)
async def show_force_reset_form(request: Request, current_operator: User = Depends(get_current_operator)):
    return templates.TemplateResponse("admin/force_reset.html", {
        "request": request,
        "message": "仮登録リストを初期化しました（GridFSの画像は削除されません）",
        "user": current_operator
    })

@router.post("/force_reset", response_class=HTMLResponse)
async def force_reset_images(request: Request, current_operator: User = Depends(get_current_operator)):
    deleted_count = 0
    for file in db.fs.files.find({"temporary": True}):
        fs.delete(file["_id"])
        deleted_count += 1
    
    return templates.TemplateResponse("admin/force_reset.html", {
        "request": request,
        "message": f"{deleted_count} 件の一時画像を削除し、仮登録リストを初期化しました",
        "user": current_operator
    })

@router.get("/statistics", response_class=HTMLResponse)
async def show_statistics(request: Request, current_operator: User = Depends(get_current_operator)):
    pipeline = [
        {"$group": {
            "_id": "$group_id",
            "uploaded_count": {"$sum": {"$cond": [{"$eq": ["$db_uploaded", True]}, 1, 0]}},
            "not_uploaded_count": {"$sum": {"$cond": [{"$eq": ["$db_uploaded", False]}, 1, 0]}},
            "total_count": {"$sum": 1}
        }},
        {"$project": {
            "group_id": "$_id",
            "uploaded_count": 1,
            "not_uploaded_count": 1,
            "total_count": 1,
            "upload_percentage": {"$cond": [
                {"$eq": ["$total_count", 0]}, 0,
                {"$multiply": [{"$divide": ["$uploaded_count", "$total_count"]}, 100]}
            ]}
        }},
        {"$sort": {"group_id": 1}}
    ]
    statistics = list(collection.aggregate(pipeline))
    return templates.TemplateResponse("admin/statistics.html", {
        "request": request,
        "statistics": statistics,
        "user": current_operator
    })

@router.get("/search", response_class=HTMLResponse)
async def show_search_page(request: Request, current_operator: User = Depends(get_current_operator)):
    return templates.TemplateResponse("admin/search.html", {"request": request, "user": current_operator})

@router.get("/detail/{item_id}", response_class=HTMLResponse)
async def show_detail(request: Request, item_id: str, group_id: str = "", date: str = "", current_operator: User = Depends(get_current_operator)):
    doc = collection.find_one({"_id": ObjectId(item_id)})
    if not doc:
        return templates.TemplateResponse("admin/not_found.html", {"request": request})

    for img in doc.get("images", []):
        if fn := img.get("filename"):
            file = fs.find_one({"filename": fn})
            img["thumbnail_base64"] = base64.b64encode(file.read()).decode() if file else None
        else:
            img["thumbnail_base64"] = None

    return templates.TemplateResponse("admin/detail.html", {
        "request": request, "item": doc, "group_id": group_id, "date": date, "user": current_operator
    })

@router.post("/delete/{item_id}")
async def delete_item(request: Request, item_id: str, group_id: str = "", date: str = "", current_operator: User = Depends(get_current_operator)):
    item = collection.find_one({"_id": ObjectId(item_id)})
    if item and "images" in item:
        for image_info in item["images"]:
            if filename := image_info.get("filename"):
                if file := fs.find_one({"filename": filename}):
                    fs.delete(file._id)
    
    collection.delete_one({"_id": ObjectId(item_id)})
    url = f"/admin/search?group_id={group_id}&date={date}&deleted=1"
    return RedirectResponse(url=url, status_code=status.HTTP_303_SEE_OTHER)

# --- Search API Endpoints ---

@router.get("/api/groups")
async def get_groups(current_operator: User = Depends(get_current_operator)):
    """グループ一覧と各アイテム数をJSONで返す"""
    pipeline = [
        {
            "$group": {
                "_id": "$group_id",
                "item_count": {"$sum": 1},
                "last_updated": {"$max": "$created_at"},
                "first_created": {"$min": "$created_at"} # 最初の登録日を追加
            }
        },
        {
            "$sort": {"last_updated": -1}
        }
    ]
    groups = list(collection.aggregate(pipeline))
    return JSONResponse(content={"groups": groups})

@router.get("/api/items", response_class=HTMLResponse)
async def get_items_for_group(request: Request, group_id: str, current_operator: User = Depends(get_current_operator)):
    """指定されたgroup_idに所属するアイテム一覧をHTMLで返す"""
    query = {"group_id": group_id}
    results = list(collection.find(query).sort("created_at", -1))
    
    for doc in results:
        if doc.get("images") and doc["images"][0].get("filename"):
            file = fs.find_one({"filename": doc["images"][0]["filename"]})
            doc["thumbnail_base64"] = base64.b64encode(file.read()).decode() if file else None
        else:
            doc["thumbnail_base64"] = None

    return templates.TemplateResponse("admin/_search_results.html", {
        "request": request, 
        "results": results
    })

# --- End Search API Endpoints ---


# --- Photographer Management APIs ---

@router.get("/api/photographers", response_model=List[User])
async def get_all_photographers(current_operator: User = Depends(get_current_operator)):
    return user_crud.get_photographers(db)

@router.post("/api/photographers", response_model=User, status_code=status.HTTP_201_CREATED)
async def create_new_photographer(user: UserCreate, current_operator: User = Depends(get_current_operator)):
    db_user = user_crud.get_user_by_email(db, email=user.email)
    if db_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    if user.role != 'photographer':
        raise HTTPException(status_code=400, detail="Role must be 'photographer'")
    return user_crud.create_user(db=db, user=user)

@router.delete("/api/photographers/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_photographer_by_id(user_id: str, current_operator: User = Depends(get_current_operator)):
    user_to_delete = user_crud.get_user(db, user_id=user_id)
    if not user_to_delete or user_to_delete.role != 'photographer':
        raise HTTPException(status_code=404, detail="Photographer not found")
    
    if not user_crud.delete_user_by_id(db, user_id=user_id):
        raise HTTPException(status_code=500, detail="Failed to delete photographer")
    return Response(status_code=status.HTTP_204_NO_CONTENT)

# --- End Photographer Management APIs ---

@router.post("/delete_group/{group_id}")
async def delete_group(request: Request, group_id: str, current_operator: User = Depends(get_current_operator)):
    items_to_delete = list(collection.find({"group_id": group_id}))
    deleted_files_count = 0
    for item in items_to_delete:
        if "images" in item:
            for image_info in item["images"]:
                if filename := image_info.get("filename"):
                    if file := fs.find_one({"filename": filename}):
                        fs.delete(file._id)
                        deleted_files_count += 1

    result = collection.delete_many({"group_id": group_id})
    deleted_docs_count = result.deleted_count

    return JSONResponse(content={
        "message": f"グループ '{group_id}' の {deleted_docs_count} 件のドキュメントと {deleted_files_count} 個の画像を削除しました。"
    })

@router.get("/temp_files")
async def get_temp_files(current_operator: User = Depends(get_current_operator)):
    files = []
    for file in db.fs.files.find({"temporary": True}):
        files.append({"filename": file["filename"]})
    return {"files": files}

@router.get("/users/me", response_model=User)
async def read_users_me(current_user: User = Depends(get_current_operator)):
    """
    現在ログインしているユーザーの情報を返す。
    """
    return current_user
