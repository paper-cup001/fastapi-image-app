# このファイルは元々、バックエンドでArucoマーカーの検出と画像のトリミングを処理していました。
# 2025年7月9日現在、QRコードの検出とトリミングはフロントエンド（upload.htmlのOpenCV.js経由）で実行されます。
#
# しかし、このファイル内の一部のユーティリティ関数（例：画像検証、リサイズ、
# 画像を正方形にする処理など）は、バックエンドの画像処理タスク（例：GridFSへの保存前の最終処理、
# または他のソースからの画像処理）で引き続き有用である可能性があります。
#
# したがって、このファイルの残りのユーティリティ機能について慎重に検討することなく、
# ファイル全体を削除しないでください。
# このファイルの本来の目的が完全に不要になった場合は、有用な関数をより汎用的な画像ユーティリティモジュールに
# リファクタリングまたは移動することを検討してください。

# image_processing.py
# main.pyにおいて、tst_mode=Falseの場合、このコードが利用される。
# QRコードを検出し、トリミング画像（JPEGバイナリ）を返す。
# 検出に失敗した場合は元画像をそのままJPEG形式で返し、理由を文字列として返す。
# トリミング後の画像は、バイナリ形式で返す。

import cv2
import numpy as np
import imghdr
import logging
import threading
from PIL import Image, ImageOps # ExifTagsを削除
import io

logging.basicConfig(level=logging.INFO)
lock = threading.Lock()
MAX_IMAGE_SIZE = 5 * 1024 * 1024
max_dim = 1080

# QRコード検出器の初期化
qr_detector = cv2.QRCodeDetector()

def find_corner_point(points, corner="right"):
    """
    指定された頂点（右上または左上）を見つける関数。
    :param points: 頂点の座標のリストまたはNumPy配列。
    :param corner: 探す頂点の種類 ("right" または "left")。
    :return: 指定された頂点の座標。
    """
    points = np.array(points) # リストの場合があるのでnumpy配列に変換
    if corner == "right":
        # 右上の点を選択：x座標の最大値とy座標の最小値を持つ点
        max_x = max(points[:, 0])
        min_y = min(points[:, 1])
        target_point = points[
            np.argmin(
                [np.linalg.norm([max_x - p[0], min_y - p[1]]) for p in points]
            )
        ]
    else:
        # 左上の点を選択：x座標の最小値とy座標の最小値を持つ点
        min_x = min(points[:, 0])
        min_y = min(points[:, 1])
        target_point = points[
            np.argmin(
                [np.linalg.norm([min_x - p[0], min_y - p[1]]) for p in points]
            )
        ]

    return target_point

def validate_image_file(image_data: bytes):
    if len(image_data) > MAX_IMAGE_SIZE:
        return False, "Image too large."
    # Pillowで画像を読み込めるかチェック
    try:
        Image.open(io.BytesIO(image_data)).verify()
    except Exception:
        return False, "Invalid image format or corrupted file."
    return True, None

def load_and_orient_image_pil(image_data: bytes) -> Image.Image:
    """
    Pillowで画像を読み込み、EXIFのOrientationタグに基づいて自動回転させたPIL Imageオブジェクトを返す。
    """
    img_pil = Image.open(io.BytesIO(image_data))
    logging.info(f"Image opened. Original size: {img_pil.size}")

    # EXIF情報を取得
    exif_data = img_pil._getexif()
    if exif_data:
        logging.info(f"EXIF data found.")
    else:
        logging.info("No EXIF data found.")

    img_pil = ImageOps.exif_transpose(img_pil) # EXIF Orientationを自動適用
    logging.info(f"After exif_transpose. New size: {img_pil.size}")
    return img_pil

def read_image(image_data: bytes):
    """
    Pillowで画像を読み込み、EXIFのOrientationタグに基づいて自動回転させ、OpenCV形式に変換して返す。
    """
    try:
        img_pil = load_and_orient_image_pil(image_data)
        
        # Pillow画像をOpenCV形式（NumPy配列）に変換
        img_cv = np.array(img_pil)
        # RGBからBGRへ変換 (OpenCVはBGRを期待するため)
        if len(img_cv.shape) == 3 and img_cv.shape[2] == 3: # RGB画像の場合
            img_cv = cv2.cvtColor(img_cv, cv2.COLOR_RGB2BGR)
        elif len(img_cv.shape) == 3 and img_cv.shape[2] == 4: # RGBA画像の場合
            img_cv = cv2.cvtColor(img_cv, cv2.COLOR_RGBA2BGR)

        return img_cv
    except Exception as e:
        logging.error(f"Error reading or rotating image: {e}")
        return None

def make_square(image, min_x, max_x, min_y, max_y):
    height, width = max_y - min_y, max_x - min_x
    square_side = max(height, width)
    if height > width:
        pad = (square_side - width) // 2
        return cv2.copyMakeBorder(image[min_y:max_y, min_x:max_x], 0, 0, pad, square_side - width - pad, cv2.BORDER_CONSTANT, value=(255,255,255))
    else:
        pad = (square_side - height) // 2
        return cv2.copyMakeBorder(image[min_y:max_y, min_x:max_x], pad, square_side - height - pad, 0, 0, cv2.BORDER_CONSTANT, value=(255,255,255))

def resize_image(img, max_dimension):
    """
    画像の最大辺が指定された長さを超える場合、アスペクト比を維持してリサイズする。
    リサイズされた画像とリサイズ率を返す。
    """
    h, w = img.shape[:2]
    if max(h, w) > max_dimension:
        ratio = max_dimension / max(h, w)
        resized_img = cv2.resize(img, (int(w * ratio), int(h * ratio)))
        return resized_img, ratio
    return img, 1.0

def process_image(image_data: bytes, x_offset: int, y_offset: int, mode: str, ip: str) -> tuple[bytes, str | None]:
    """
    QRコードを検出し、画像をトリミングして返す。
    1. 画像を最大1800pxにリサイズしてQRコード検出のパフォーマンスを向上させる。
    2. 検出された座標を元の画像のスケールに変換する。
    3. 元の画像を高解像度でトリミングする。
    4. 最終的な画像を最大1080pxにリサイズして返す。
    """
    logging.info(f"[{ip}] Starting image processing with x_offset={x_offset}, y_offset={y_offset}, mode={mode}")
    valid, error = validate_image_file(image_data)
    if not valid:
        return None, error

    img = read_image(image_data)
    if img is None:
        return None, "Failed to decode image or apply rotation."

    # パフォーマンスのために画像をリサイズしてQRコードを検出
    img_for_detection, ratio = resize_image(img, 1800)
    
    retval, decoded_info, points, straight_qrcode = qr_detector.detectAndDecodeMulti(img_for_detection)
    logging.info(f"[{ip}] QR detection result: retval={retval}, decoded_info_size={len(decoded_info) if decoded_info is not None else 'None'}, points_len={len(points) if points is not None else 'None'}")

    if not retval or points is None or len(points) == 0:
        logging.warning(f"[{ip}] No QR codes found.")
        # QRが見つからない場合は、元画像を1080pxにリサイズして返す
        final_img, _ = resize_image(img, max_dim)
        _, encoded_image = cv2.imencode(".jpg", final_img)
        return encoded_image.tobytes(), "No QR codes found."

    if len(points) != 3:
        logging.warning(f"[{ip}] Expected 3 QR codes, found {len(points)}.")
        final_img, _ = resize_image(img, max_dim)
        _, encoded_image = cv2.imencode(".jpg", final_img)
        return encoded_image.tobytes(), f"Exactly 3 QR codes required. Found {len(points)}"

    logging.info(f"[{ip}] Successfully detected 3 QR codes.")

    # 座標を元の画像のスケールに戻す
    original_points = points / ratio if ratio != 1.0 else points

    # 治具の左右判定
    center_x = img.shape[1] / 2
    left_count = sum(1 for qr_points_set in original_points for point in qr_points_set if point[0] < center_x)
    right_count = sum(1 for qr_points_set in original_points for point in qr_points_set if point[0] >= center_x)
    
    side = "right" if right_count > left_count else "left"
    logging.info(f"[{ip}] Detected side: {side}")

    # コーナーポイントの取得
    corner_points = []
    for qr_points_set in original_points:
        corner = "left" if side == "right" else "right"
        corner_points.append(find_corner_point(qr_points_set, corner=corner))

    # トリミング座標の決定
    x_coords = [p[0] for p in corner_points]
    y_coords = [p[1] for p in corner_points]
    x_min, x_max = min(x_coords) + x_offset, max(x_coords) + x_offset
    y_min, y_max = min(y_coords) + y_offset, max(y_coords) + y_offset
    logging.info(f"[{ip}] Calculated crop coordinates: x_min={x_min}, y_min={y_min}, x_max={x_max}, y_max={y_max}")

    # 画像の境界内に収まるように調整
    h, w = img.shape[:2]
    min_x, min_y = max(0, int(x_min)), max(0, int(y_min))
    max_x, max_y = min(w, int(x_max)), min(h, int(y_max))

    if min_x >= max_x or min_y >= max_y:
        logging.warning(f"[{ip}] Invalid QR code geometry or offsets resulted in invalid crop area.")
        final_img, _ = resize_image(img, max_dim)
        _, encoded_image = cv2.imencode(".jpg", final_img)
        return encoded_image.tobytes(), "Invalid QR code geometry or offsets resulted in invalid crop area."

    if mode == "outline":
        cv2.rectangle(img, (min_x, min_y), (max_x, max_y), (0, 255, 0), 10)
        result, _ = resize_image(img, max_dim)
    else:
        cropped_img = img[min_y:max_y, min_x:max_x]
        squared_img = make_square(cropped_img, 0, cropped_img.shape[1], 0, cropped_img.shape[0])
        result, _ = resize_image(squared_img, max_dim)

    _, encoded_image = cv2.imencode(".jpg", result)
    logging.info(f"[{ip}] Image processing completed successfully.")
    return encoded_image.tobytes(), None