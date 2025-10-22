import os
import shutil
import qrcode
import io
import base64
import json
import socket # Added for IP address retrieval

from fastapi import APIRouter, Form, Request, status, Depends
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from pymongo import MongoClient
import gridfs  # ← 追加

from bson import ObjectId

from routers.photographer import TEMP_IMAGES  # TEMP_IMAGESはそのまま
from db import db, collection, fs # db.pyから参照するための設定
from dependencies import get_current_operator
from schemas import User

router = APIRouter()
templates = Jinja2Templates(directory="templates")

TEMP_DIR = "temp_images"

# FastAPIの接続先のIPアドレスを取得する関数
def get_local_ip():
    """
    これは、QRコード生成時に使用されるURLのホスト部分に必要

    例えば、PCにWi-Fiと有線LANの両方が接続されている場合や、仮想ネットワークアダプターが存在する場合など、複数のIPア
    ドレスを持っていることがあります。その中で、他のデバイス（今回のiPhoneなど）からアクセスできるIPアドレスはどれか
    、というのを確実に知るために、一度外部（GoogleのDNSサーバーなど）に接続を試みるという間接的な方法が取られます。
    """
    try:
        # Create a socket to connect to an external host (doesn't actually connect)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))  # Google's public DNS server
        ip_address = s.getsockname()[0]
        s.close()
        return ip_address
    except Exception:
        return "localhost" # Fallback to localhost if IP cannot be determined

# QRコード作成
@router.get("/dashboard", response_class=HTMLResponse)
async def show_qr_form(request: Request, current_operator: User = Depends(get_current_operator)):
    return templates.TemplateResponse("admin/dashboard.html", {"request": request, "user": current_operator})

@router.get("/generate_qr", response_class=HTMLResponse)
async def show_generate_qr_form(request: Request, current_operator: User = Depends(get_current_operator)):
    return templates.TemplateResponse("admin/generate_qr.html", {"request": request, "user": current_operator})

@router.post("/generate_qr", response_class=HTMLResponse)
async def generate_qr(request: Request, group_id: str = Form(...), old_phone: bool = Form(False), current_operator: User = Depends(get_current_operator)):
    local_ip = get_local_ip()
    
    if old_phone:
        endpoint = "upload_old.html"
    else:
        endpoint = "upload.html"
        
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

# 強制初期化
@router.get("/force_reset", response_class=HTMLResponse)
async def show_force_reset_form(request: Request, current_operator: User = Depends(get_current_operator)):
    # TEMP_IMAGESの全リセット
    from routers.photographer import TEMP_IMAGES
    for group_id in list(TEMP_IMAGES.keys()):
        TEMP_IMAGES[group_id] = []
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
    
    # TEMP_IMAGESもクリア
    from routers.photographer import TEMP_IMAGES
    TEMP_IMAGES.clear()

    return templates.TemplateResponse("admin/force_reset.html", {
        "request": request,
        "message": f"{deleted_count} 件の一時画像を削除し、仮登録リストを初期化しました",
        "user": current_operator
    })



# グループID毎の統計情報
@router.get("/statistics", response_class=HTMLResponse)
async def show_statistics(request: Request, current_operator: User = Depends(get_current_operator)):
    pipeline = [
        {
            "$group": {
                "_id": "$group_id",
                "uploaded_count": {
                    "$sum": {
                        "$cond": [{"$eq": ["$db_uploaded", True]}, 1, 0]
                    }
                },
                "not_uploaded_count": {
                    "$sum": {
                        "$cond": [{"$eq": ["$db_uploaded", False]}, 1, 0]
                    }
                },
                "total_count": {"$sum": 1}
            }
        },
        {
            "$project": {
                "group_id": "$_id",
                "uploaded_count": 1,
                "not_uploaded_count": 1,
                "total_count": 1,
                "upload_percentage": {
                    "$cond": [
                        {"$eq": ["$total_count", 0]},
                        0,
                        {
                            "$multiply": [
                                {"$divide": ["$uploaded_count", "$total_count"]},
                                100
                            ]
                        }
                    ]
                }
            }
        },
        {
            "$sort": {"group_id": 1}
        }
    ]
    
    statistics = list(collection.aggregate(pipeline))
    
    return templates.TemplateResponse("admin/statistics.html", {
        "request": request,
        "statistics": statistics,
        "user": current_operator
    })


# 登録画像の検索
@router.get("/search", response_class=HTMLResponse)
async def search_registered(request: Request, group_id: str = "", date: str = "", db_uploaded: str = "", current_operator: User = Depends(get_current_operator)):
    query = {}
    if group_id:
        query["group_id"] = group_id
    if date:
        query["created_at"] = {"$regex": f"^{date}"}
    if db_uploaded in ("true", "false"):
        query["db_uploaded"] = db_uploaded == "true"

    results = list(collection.find(query))

    for doc in results:
        if doc.get("images"):
            filename = doc["images"][0].get("filename")
            if filename:
                # GridFSから画像取得しbase64化
                file = fs.find_one({"filename": filename})
                if file:
                    import base64
                    thumbnail_base64 = base64.b64encode(file.read()).decode()
                    doc["thumbnail_base64"] = thumbnail_base64
                else:
                    doc["thumbnail_base64"] = None
            else:
                doc["thumbnail_base64"] = None
        else:
            doc["thumbnail_base64"] = None

    return templates.TemplateResponse("admin/search.html", {
        "request": request,
        "results": results,
        "group_id": group_id,
        "date": date,
        "db_uploaded": db_uploaded,
        "user": current_operator
    })

# 登録画像の詳細表示
@router.get("/detail/{item_id}", response_class=HTMLResponse)
async def show_detail(request: Request, item_id: str, group_id: str = "", date: str = "", current_operator: User = Depends(get_current_operator)):
    doc = collection.find_one({"_id": ObjectId(item_id)})
    if not doc:
        return templates.TemplateResponse("admin/not_found.html", {"request": request})

    # 画像Base64を追加
    for img in doc.get("images", []):
        fn = img.get("filename")
        if fn:
            file = fs.find_one({"filename": fn})
            if file:
                import base64
                img["thumbnail_base64"] = base64.b64encode(file.read()).decode()
            else:
                img["thumbnail_base64"] = None
        else:
            img["thumbnail_base64"] = None

    return templates.TemplateResponse("admin/detail.html", {
        "request": request,
        "item": doc,
        "group_id": group_id,
        "date": date,
        "user": current_operator
    })

# 登録削除
@router.post("/delete/{item_id}")
async def delete_item(request: Request, item_id: str, group_id: str = "", date: str = "", current_operator: User = Depends(get_current_operator)):
    # 最初にGridFSから画像ファイルを削除
    item = collection.find_one({"_id": ObjectId(item_id)})
    if item and "images" in item:
        for image_info in item["images"]:
            filename = image_info.get("filename")
            if filename:
                file = fs.find_one({"filename": filename})
                if file:
                    fs.delete(file._id)
    
    # 次にMongoDBのドキュメントを削除
    result = collection.delete_one({"_id": ObjectId(item_id)})
    
    url = f"/admin/search?group_id={group_id}&date={date}&deleted=1"
    return RedirectResponse(url=url, status_code=status.HTTP_303_SEE_OTHER)


# グループ単位での一括削除
@router.post("/delete_group/{group_id}")
async def delete_group(request: Request, group_id: str, current_operator: User = Depends(get_current_operator)):
    # 最初にGridFSから関連する画像ファイルをすべて削除
    items_to_delete = collection.find({"group_id": group_id})
    deleted_files_count = 0
    for item in items_to_delete:
        if "images" in item:
            for image_info in item["images"]:
                filename = image_info.get("filename")
                if filename:
                    file = fs.find_one({"filename": filename})
                    if file:
                        fs.delete(file._id)
                        deleted_files_count += 1

    # 次にMongoDBから関連するドキュメントをすべて削除
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
