from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from datetime import datetime

# --- トークン関連のスキーマ ---

class Token(BaseModel):
    """クライアントに返すアクセストークンのスキーマ"""
    access_token: str
    token_type: str

class TokenWithRole(Token):
    """ユーザーの役割(role)を含むトークンスキーマ"""
    role: str

class TokenData(BaseModel):
    """アクセストークン内に保持するデータのスキーマ"""
    email: Optional[EmailStr] = None

# --- ユーザー関連のスキーマ ---

class UserBase(BaseModel):
    """ユーザーモデルの基本的なフィールドを定義するベースクラス"""
    email: EmailStr = Field(..., description="ユーザーのメールアドレス")
    role: str = Field(..., description="ユーザーの役割（operator or photographer）")

class UserCreate(UserBase):
    """ユーザー作成時に受け取るデータのスキーマ"""
    password: str = Field(..., min_length=8, description="ユーザーパスワード（8文字以上）")

class User(UserBase):
    """APIを通じてクライアントに返すユーザー情報のスキーマ"""
    id: str = Field(alias="_id", description="MongoDBのドキュメントID")
    is_active: bool = Field(..., description="アカウントが有効かどうか")
    created_at: datetime = Field(..., description="アカウント作成日時")

    class Config:
        # MongoDBの`_id`フィールドを`id`として扱えるようにする設定
        validate_by_name = True
        # ObjectIdをJSONシリアライズ可能なstrに変換する設定
        json_encoders = {
            datetime: lambda dt: dt.isoformat(),
        }

class UserInDB(User):
    """データベース内部で完全なユーザー情報を扱うためのスキーマ"""
    hashed_password: str = Field(..., description="ハッシュ化されたパスワード")
