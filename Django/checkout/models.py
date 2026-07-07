from django.db import models
from django.utils import timezone


# ================= 商品模型 (Product) =================
class Product(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name="水果名称")
    price = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="销售单价")

    # ✅ 修复字段：库存 (解决 'no attribute stock' 报错)
    stock = models.FloatField(default=0, verbose_name="库存数量(斤)")

    # ✅ 修复字段：进货价 (views.py 中用于计算利润)
    cost_price = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="进货单价")

    barcode = models.CharField(max_length=50, blank=True, null=True, verbose_name="条形码")

    # 自动添加创建和更新时间（用于解决 migration 时的提示）
    created_at = models.DateTimeField(default=timezone.now, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    def __str__(self):
        return f"{self.name} (库存: {self.stock})"


# ================= 订单模型 (Order) =================
class Order(models.Model):
    order_id = models.CharField(max_length=50, unique=True, verbose_name="订单号")
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="订单总额")
    products = models.JSONField(verbose_name="商品列表详情")  # 存储快照：[{name, price, quantity}...]
    status = models.CharField(max_length=20, default='success', verbose_name="状态")
    created_time = models.DateTimeField(default=timezone.now, verbose_name="创建时间")

    def __str__(self):
        return f"订单 {self.order_id} - ¥{self.total_amount}"


# ================= 识别历史记录 (DetectionHistory) =================
class DetectionHistory(models.Model):
    detection_time = models.DateTimeField(default=timezone.now)
    engine_type = models.CharField(max_length=20)  # ONNX / YOLO
    status = models.CharField(max_length=20)
    total_objects = models.IntegerField(default=0)
    total_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    processing_time = models.FloatField(default=0)
    error_message = models.TextField(blank=True)


# ================= 识别结果 (DetectionResult) =================
class DetectionResult(models.Model):
    detection_history = models.ForeignKey(DetectionHistory, on_delete=models.CASCADE)
    product_name = models.CharField(max_length=100)
    confidence = models.FloatField()
    price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.IntegerField(default=1)
    # 边界框坐标
    bbox_x1 = models.IntegerField(default=0)
    bbox_y1 = models.IntegerField(default=0)
    bbox_x2 = models.IntegerField(default=0)
    bbox_y2 = models.IntegerField(default=0)
    class_id = models.IntegerField(default=0)