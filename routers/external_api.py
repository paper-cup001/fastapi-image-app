# routers/n8n.py
# ウェブアプリではなく、n8nに対するエンドポイントを提供するためのコードです。 

from fastapi import APIRouter, UploadFile, File, Query, Body, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from pymongo import MongoClient
import gridfs
import io

from pyzbar.pyzbar import decode
from PIL import Image

from bson import ObjectId
from typing import Optional
from pydantic import BaseModel, Field

from db import db, collection, fs# db.pyから参照するための設定
router = APIRouter()

# MongoDB設定（n8nが外部サーバーからアクセスする想定）
#client = MongoClient("mongodb://192.168.100.132:27017")  # ← localhostから修正
#db = client["image_db"]
#collection = db["images"]
#fs = gridfs.GridFS(db)

@router.get("/search_unuploaded_items")
async def search_unuploaded_items(group_id: str = Query(...)):
    """
    指定されたgroup_idに一致し、かつdb_uploaded == false な商品を返す
    """

    # group_id一致 & 未アップロードの商品だけ抽出
    matching_items = collection.find({
        "group_id": group_id,
        "db_uploaded": False
    })

    results = []
    for item in matching_items:
        results.append({
            "_id": str(item["_id"]),
            "group_id": item["group_id"],
            "user_short_id": item["user_short_id"],
            "images": item.get("images", []),
            "db_uploaded": item.get("db_uploaded")
        })

    if not results:
        return JSONResponse(content={"message": "No unuploaded items found"}, status_code=200)

    return {"items": results}


@router.get("/images/{filename}")
async def get_image(filename: str):
    """
    GridFSに保存された画像ファイルを、ファイル名を指定して取得します。
    アクセス例: /n8n/images/sample_001.jpg
    """
    file = fs.find_one({"filename": filename})
    if not file:
        return JSONResponse(status_code=404, content={"error": "Image not found"})

    return StreamingResponse(io.BytesIO(file.read()), media_type="image/jpeg")


class MarkUploadedRequest(BaseModel):
    item_id: str = Field(..., alias="_id")

    class Config:
        allow_population_by_field_name = True


@router.patch("/mark_uploaded")
async def mark_item_as_uploaded(request: MarkUploadedRequest):
    """
    指定された_idに一致するアイテムのdb_uploadedをTrueに更新
    """
    try:
        obj_id = ObjectId(request.item_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid _id format")

    result = collection.update_one(
        {"_id": obj_id},
        {"$set": {"db_uploaded": True}}
    )

    if result.matched_count == 0:
        return JSONResponse(status_code=404, content={"error": "対象アイテムが見つかりません"})
    if result.modified_count == 0:
        return JSONResponse(status_code=200, content={"message": "すでにdb_uploadedはTrueです"})

    return {"message": "更新しました", "_id": request.item_id}



@router.post("/barcode")
async def read_barcode(file: UploadFile = File(...)):
    # バーコードを含む画像ファイルを受け取り、解析します。
    try:
        # 画像ファイルを読み込み
        image_data = await file.read()
        image = Image.open(io.BytesIO(image_data))

        # バーコード解析
        decoded_objects = decode(image)
        results = []

        for obj in decoded_objects:
            results.append({
                "type": obj.type,
                "data": obj.data.decode("utf-8"),
                "rect": obj.rect
            })

        if not results:
            return JSONResponse(content={"barcodes": [], "message": "No barcode found"}, status_code=200)

        return {"barcodes": results}

    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)
    
# title から metadataを更新するエンドポイント



class MetadataUpdateRequest(BaseModel):
    id: str = Field(..., alias="_id")  # ← alias指定でSwaggerにも表示される
    title: Optional[str] = None
    platform: Optional[str] = None
    description: Optional[str] = None
    jan_code: Optional[str] = None
    status: Optional[str] = None
    meta_added: Optional[bool] = None

    class Config:
        allow_population_by_field_name = True  # ← aliasでも内部でも使えるように


@router.patch("/update_metadata")
async def update_metadata(request: MetadataUpdateRequest):
    """
    ObjectId で指定されたドキュメントのメタデータを更新する。
    指定されたフィールドのみ更新。
    """
    try:
        obj_id = ObjectId(request.id)  # ← ここを修正
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid _id format")

    # 更新対象のフィールドだけ抽出
    update_fields = {
        key: value for key, value in request.dict().items()
        if key != "id" and value is not None
    }

    if not update_fields:
        raise HTTPException(status_code=400, detail="更新対象フィールドが指定されていません")

    result = collection.update_one({"_id": obj_id}, {"$set": update_fields})

    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="該当するデータが見つかりません")

    return {
        "message": "更新しました",
        "_id": request.id,
        "updated_fields": list(update_fields.keys())
    }