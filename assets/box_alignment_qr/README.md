# 箱体正面对齐二维码

标准打印文件：`box_alignment_qr_a4.pdf`

当前打印机实测把`100 mm`缩小为`96 mm`，请改用：

`box_alignment_qr_a4_compensated_96pct.pdf`

该文件已经按`1 / 0.96 = 1.0416667`倍预放大：

- PDF中的校验条：`104.1667 mm`，预计打印为`100 mm`
- PDF中的黑色码区：`156.25 mm`，预计打印为`150 mm`
- PDF中含静区总边长：约`199.353448 mm`，预计打印为`191.379310 mm`

## 固定参数

- 内容：`QRCOMP:BOX_CENTER:V1`
- QR版本：Version 3
- 纠错等级：H
- 黑色码区边长：`150.0 mm`
- 模块数：`29 x 29`
- 单模块边长：约`5.172414 mm`
- 四周静区：各4模块，约`20.689655 mm`
- 含静区总边长：约`191.379310 mm`
- PnP使用的方形边长：`0.150 m`，不包括白色静区

## 打印要求

1. 使用A4白色哑光纸，黑白打印即可。
2. 对当前固定缩放的打印机，直接打印`compensated_96pct.pdf`，不再额外调整比例。
3. 打印后先测量页面下方校验条，目标为`100 mm`；误差超过`1 mm`时不要粘贴。
4. 再测量二维码最外层黑色码区，边长应为`150 mm`。
5. 只沿四角裁切标记裁剪，完整保留白色静区。

## 粘贴要求

1. 二维码中心与箱子正面几何中心重合。
2. 二维码上边缘保持水平，纸面必须平整，不能翘曲或起皱。
3. 不要用透明胶覆盖黑色码区或静区，避免D455反光。
4. 箱面颜色复杂时，必须保留整块白色静区，不要只剪黑色码区。
5. 粘贴后重新测量黑色码区边长，并记录实际值供PnP配置使用。

`box_alignment_qr.svg`是固定物理尺寸的矢量备份；`box_alignment_qr_preview.png`仅用于屏幕预览和解码验证，不作为打印文件。

## 重新生成

```bash
python3 -m pip install 'qrcode[pil]' reportlab
python3 scripts/calibration/generate_box_alignment_qr.py
python3 scripts/calibration/generate_box_alignment_qr.py --printer-scale 0.96
```
