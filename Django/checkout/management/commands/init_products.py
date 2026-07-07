from django.core.management.base import BaseCommand
from checkout.models import Product


class Command(BaseCommand):
    help = '初始化YOLO模型对应的商品数据'

    def handle(self, *args, **options):
        # 清空现有数据
        Product.objects.all().delete()
        self.stdout.write('🗑️  已清空现有商品数据')

        # YOLO模型对应的商品
        products_data = [
            {"name": "苹果", "price": 8.0, "barcode": "1000", "class_name": "apple"},
            {"name": "香蕉", "price": 6.0, "barcode": "1001", "class_name": "bananan"},
            {"name": "橙子", "price": 5.0, "barcode": "1002", "class_name": "orange"},
            {"name": "梨", "price": 7.0, "barcode": "1003", "class_name": "pear"},
            {"name": "胡萝卜", "price": 3.0, "barcode": "1004", "class_name": "carrot"},
            {"name": "樱桃", "price": 25.0, "barcode": "1005", "class_name": "cherry"},
            {"name": "葡萄", "price": 12.0, "barcode": "1006", "class_name": "grape"},
            {"name": "西瓜", "price": 15.0, "barcode": "1007", "class_name": "waterlemon"},
            {"name": "哈密瓜", "price": 20.0, "barcode": "1008", "class_name": "hamimelon"},
            {"name": "向日葵籽", "price": 15.0, "barcode": "1009", "class_name": "sunflower"},
            {"name": "花生", "price": 8.0, "barcode": "1010", "class_name": "peanut"},
            {"name": "南瓜", "price": 12.0, "barcode": "1011", "class_name": "pumpkin"},
        ]

        created_count = 0
        for product_data in products_data:
            # 移除class_name，因为模型中没有这个字段
            data_to_create = {k: v for k, v in product_data.items() if k != 'class_name'}
            Product.objects.create(**data_to_create)
            created_count += 1
            self.stdout.write(
                self.style.SUCCESS(f'✅ 创建商品: {product_data["name"]} - ¥{product_data["price"]}')
            )

        self.stdout.write(
            self.style.SUCCESS(f'🎉 商品数据初始化完成！共创建 {created_count} 个商品')
        )