from fastapi import APIRouter, Request, Depends, HTTPException, status, Response, Body
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pymongo.database import Database
from typing import List
import io
import zipfile
from pymongo.database import Database
from typing import List

from dependencies import get_current_system_admin
from db import db, fs # fs (GridFS) をインポート
from schemas import User, UserCreate, UserInDB
from crud import user_crud

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

# --- ここから孤立データ管理用のAPIエンドポイント ---

# --- 孤立した撮影者の管理 ---

@router.get("/api/orphaned-photographers", response_model=List[User])
async def get_orphaned_photographers(
    db: Database = Depends(lambda: db),
    current_user: User = Depends(get_current_system_admin)
):
    """どの運営者にも紐付いていない撮影者アカウントを取得する。"""
    return user_crud.get_orphaned_photographers(db)

@router.put("/api/photographers/{photographer_id}/assign-operator", status_code=status.HTTP_204_NO_CONTENT)
async def assign_operator_to_photographer(
    photographer_id: str,
    data: dict = Body(...),
    db: Database = Depends(lambda: db),
    current_user: User = Depends(get_current_system_admin)
):
    """指定された撮影者に運営者を割り当てる。"""
    operator_id = data.get("operator_id")
    if not operator_id:
        raise HTTPException(status_code=400, detail="Operator ID is required")
    
    success = user_crud.assign_operator_to_user(db, user_id=photographer_id, operator_id=operator_id)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to assign operator")
    return Response(status_code=status.HTTP_204_NO_CONTENT)

@router.delete("/api/orphaned-photographers/{photographer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_orphaned_photographer(
    photographer_id: str,
    db: Database = Depends(lambda: db),
    current_user: User = Depends(get_current_system_admin)
):
    """孤立した撮影者を削除する。"""
    # 念のため、本当に孤立しているか確認
    user = user_crud.get_user(db, photographer_id)
    if not user or user.role != 'photographer' or user.created_by_operator_id is not None:
        raise HTTPException(status_code=400, detail="User is not an orphaned photographer")

    success = user_crud.delete_user_by_id(db, user_id=photographer_id)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to delete user")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- 孤立した画像グループの管理 ---

@router.get("/api/orphaned-image-groups")
async def get_orphaned_image_groups(
    db: Database = Depends(lambda: db),
    current_user: User = Depends(get_current_system_admin)
):
    """operator_id が設定されていない、または無効な画像グループの一覧を取得する。"""
    # 1. 現在存在するすべての運営者のIDリストを取得
    operators = list(db.users.find({"role": "operator"}, {"_id": 1}))
    valid_operator_ids = [str(op["_id"]) for op in operators]

    # 2. 孤立した画像を検索するパイプラインを定義
    pipeline = [
        {
            "$match": {
                "$or": [
                    { "operator_id": { "$exists": False } },
                    { "operator_id": { "$nin": valid_operator_ids } }
                ]
            }
        },
        {
            "$group": {
                "_id": "$group_id",
                "item_count": {"$sum": 1}
            }
        },
        {
            "$project": {
                "group_id": "$_id",
                "item_count": 1
            }
        },
        {
            "$sort": { "group_id": 1 } # グループIDでソート
        }
    ]
    groups = list(db.images.aggregate(pipeline))
    return groups



@router.delete("/api/image-groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_orphaned_image_group(
    group_id: str,
    db: Database = Depends(lambda: db),
    current_user: User = Depends(get_current_system_admin)
):
    """孤立した画像グループを関連ファイルごと削除する。"""
    # 現在の有効な運営者IDリストを取得
    operators = list(db.users.find({"role": "operator"}, {"_id": 1}))
    valid_operator_ids = [str(op["_id"]) for op in operators]
    
    # 削除対象のドキュメントを検索
    query = {
        "group_id": group_id, 
        "$or": [
            { "operator_id": { "$exists": False } },
            { "operator_id": { "$nin": valid_operator_ids } }
        ]
    }
    items_to_delete = list(db.images.find(query))

    if not items_to_delete:
        raise HTTPException(status_code=404, detail="No orphaned items found for the given group ID")

    # GridFSから関連ファイルを削除
    for item in items_to_delete:
        if "images" in item:
            for image_info in item["images"]:
                if filename := image_info.get("filename"):
                    if file := fs.find_one({"filename": filename}):
                        fs.delete(file._id)
                if thumb_filename := image_info.get("thumbnail_filename"):
                    if thumb_file := fs.find_one({"filename": thumb_filename}):
                        fs.delete(thumb_file._id)

    # MongoDBからドキュメントを削除
    result = db.images.delete_many(query)

    return Response(status_code=status.HTTP_204_NO_CONTENT)

@router.get("/api/image-groups/download/{group_id}")
async def download_orphaned_image_group(
    group_id: str,
    db: Database = Depends(lambda: db),
    current_user: User = Depends(get_current_system_admin)
):
    """孤立した画像グループをZIPファイルとしてダウンロードする。"""
    # 孤立の定義
    operators = list(db.users.find({"role": "operator"}, {"_id": 1}))
    valid_operator_ids = [str(op["_id"]) for op in operators]
    query = {
        "group_id": group_id,
        "$or": [
            {"operator_id": {"$exists": False}},
            {"operator_id": {"$nin": valid_operator_ids}}
        ]
    }
    items_to_download = list(db.images.find(query))

    if not items_to_download:
        raise HTTPException(status_code=404, detail="No orphaned items found for the given group ID")

    # ZIPファイルをメモリ上に作成
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for item in items_to_download:
            operator_id_folder = item.get("operator_id", "unknown_operator")
            for image_info in item.get("images", []):
                if filename := image_info.get("filename"):
                    gridfs_file = fs.find_one({"filename": filename})
                    if gridfs_file:
                        # 運営者ID/ファイル名 のパス構造でZIPに追加
                        zip_path = f"{operator_id_folder}/{filename}"
                        zf.writestr(zip_path, fs.get(gridfs_file._id).read())

    zip_buffer.seek(0)

    # StreamingResponseでZIPファイルを返す
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename=orphaned_group_{group_id}.zip"
        }
    )

# --- ここからAPIエンドポイントを追加 ---

@router.get("/api/operators", response_model=List[UserInDB])
async def get_all_operators(
    db: Database = Depends(lambda: db), 
    current_user: User = Depends(get_current_system_admin)
):
    """
    すべての運営者アカウントを取得する。
    """
    operators = user_crud.get_operators(db)
    return operators

@router.post("/api/operators", response_model=UserInDB, status_code=status.HTTP_201_CREATED)
async def create_new_operator(
    user: UserCreate, 
    db: Database = Depends(lambda: db), 
    current_user: User = Depends(get_current_system_admin)
):
    """
    新しい運営者アカウントを作成する。
    """
    # メールアドレスの重複チェック
    db_user = user_crud.get_user_by_email(db, email=user.email)
    if db_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="このメールアドレスは既に使用されています。",
        )
    
    # 運営者としてユーザーを作成
    # 注意: スキーマでroleが指定されていることを確認
    if user.role != "operator":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="役割は 'operator' である必要があります。",
        )
    new_operator = user_crud.create_user(db=db, user=user)
    return new_operator

@router.delete("/api/operators/{user_id}")
async def delete_operator(
    user_id: str, 
    db: Database = Depends(lambda: db), 
    current_user: User = Depends(get_current_system_admin)
):
    """
    指定されたIDの運営者アカウントを削除する。
    """
    user_to_delete = user_crud.get_user(db, user_id)
    if not user_to_delete:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="指定されたユーザーが見つかりません。",
        )
    if user_to_delete.role != "operator":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="運営者アカウントのみ削除できます。",
        )

    success = user_crud.delete_user_by_id(db, user_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="ユーザーの削除に失敗しました。",
        )
    # 削除成功メッセージを返す
    return JSONResponse(content={"message": "運営者を削除しました。"}, status_code=status.HTTP_200_OK)
