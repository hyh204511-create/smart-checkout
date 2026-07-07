from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    # 管理员原生后台
    path('admin/', admin.site.urls),

    # 🌟 将 checkout 应用的所有 URL 挂载到根路径
    # 这样:
    #   localhost:8000/                 -> 首页
    #   localhost:8000/checkout/payment -> 支付页
    #   localhost:8000/api/...          -> 接口
    path('', include('checkout.urls')),
]

# 静态文件/媒体文件配置 (用于显示上传的商品图片)
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)