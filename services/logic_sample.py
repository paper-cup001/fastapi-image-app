@app.post("/trim")
async def upload_trim(file: UploadFile = File(...)):

    # マーカーの頂点を見つける(QR)
    def find_corner_point(points, corner="right"):
        """
        指定された頂点（右上または左上）を見つける関数。
        :param points: 頂点の座標のリストまたはNumPy配列。
        :param corner: 探す頂点の種類 ("right" または "left")。
        :return: 指定された頂点の座標。
        """
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

    # (1) 画像をnumpy 配列にして、cv2に渡す
    contents = await file.read()
    nparr = np.frombuffer(contents, np.uint8)
    decoded_image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    # (2) decoded_imageに対して、QRコード認識を試みる
    retval, decoded_info, points, straight_qrcode = qr_detector.detectAndDecodeMulti(decoded_image)

    # QRコードが見つからない場合は終了
    if points is None:
        print("QRコードが見つかりません")
        return Response(content=contents, media_type="image/jpeg")

    # F1, F2, F3, B1, B2, B3 のQRコードのみをフィルタリング
    valid_qr_codes = ["F1", "F2", "F3", "B1", "B2", "B3"]
    d_marker_int = {}
    if decoded_info is not None:
        for i, info in enumerate(decoded_info):
            if info in valid_qr_codes:
                d_marker_int[info] = points[i].astype(np.int32)

    # 有効なQRコードが3つ未満の場合、画像をそのまま返して終了
    if len(d_marker_int) < 3:
        print(f"F1, F2, F3のQRコードが3つ見つかりませんでした。検出された有効なQRコード: {list(d_marker_int.keys())}")
        return Response(content=contents, media_type="image/jpeg")

    print("QRコードが見つかりました")
    #print(d_marker_int)

    # (3) 治具の左右確定。画像を縦に2分割して、マーカーの数でright, leftとしている。
    center_x = decoded_image.shape[1] / 2

    # マーカーの数をカウント
    left_count = sum(
        pt[0] < center_x for marker in d_marker_int.values() for pt in marker
    )
    right_count = sum(
        pt[0] > center_x for marker in d_marker_int.values() for pt in marker
    )

    # 左右のマーカーの位置を判定
    if left_count < right_count:
        side = "left"
    elif right_count <= left_count:
        side = "right"
    else:
        side = "undetermined"  # どちらの側にも2つのQRコードがない場合

    # 結果を表示
    print(f"Detected side: {side}")

    # (4) 画像のトリミング
    corner_points = []
    for key, value in d_marker_int.items():
        corner_point = find_corner_point(value, corner=side)
        corner_points.append(corner_point)

    print("コーナーポイント", corner_points)

    if len(corner_points) >= 3:
        # トリミング座標の決定。大文字の変数は微調整の値
        x_min = min(point[0] for point in corner_points) + X_MIN
        x_max = max(point[0] for point in corner_points) + X_MAX
        y_min = min(point[1] for point in corner_points) + Y_MIN
        y_max = max(point[1] for point in corner_points) + Y_MAX

        # トリミング
        cropped_image = decoded_image[
            int(y_min) : int(y_max), int(x_min) : int(x_max)
        ]

        # 画像をJPEG形式にエンコード
        is_success, buffer = cv2.imencode(".jpg", cropped_image)
        if is_success:
            # FastAPIのResponseを使って画像バイナリを返す
            return Response(content=buffer.tobytes(), media_type="image/jpeg")
        else:
            return {"error": "Error in image encoding"}

    # マーカーが3つない場合
    else:
        print("マーカーが３つ認識できませんでした")

    # 画像をそのまま返す
    return Response(content=contents, media_type="image/jpeg")