# checkout/urls.py
from django.urls import path
from . import views

urlpatterns = [
    # 页面
    path('', views.index, name='index'),
    path('login/', views.login_page, name='login_page'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('products/manage/', views.product_manager, name='product_manager'),
    path('checkout/payment/', views.payment_page, name='payment_page'),

    # 登录
    path('api/user/login/', views.api_user_login, name='api_user_login'),

    # 硬件
    path('api/hello/', views.hello_world, name='hello_world'),
    path('api/get-weight/', views.get_weight, name='get_weight'),
    path('api/video_feed/', views.video_feed, name='video_feed'),
    path('api/camera-snapshot/', views.camera_snapshot, name='camera_snapshot'),
    path('api/camera-exposure/', views.camera_exposure, name='camera_exposure'),
    path('api/camera-params/', views.camera_params, name='camera_params'),
    path('api/camera-sharpness/', views.camera_sharpness, name='camera_sharpness'),
    path('api/send-tts/', views.send_tts, name='send_tts'),
    path('api/tare/', views.tare_scale, name='tare_scale'),

    # 业务
    path('api/detect/onnx/', views.detect_products_onnx, name='detect_products_onnx'),
    path('api/create-order/', views.create_order, name='create_order'),
    path('api/pay-order/', views.pay_order, name='pay_order'),

    # 数据 & 管理
    path('api/sales/data/', views.sales_data, name='sales_data'),
    path('api/dashboard/data/', views.dashboard_data, name='dashboard_data'),
    path('api/product/list/', views.product_list, name='product_list'),
    path('api/upload/fruit/', views.upload_fruit, name='upload_fruit'),
    path('api/product/<int:pk>/', views.product_detail, name='product_detail'),
    path('api/rknn/health/', views.rknn_health, name='rknn_health'),

    # ============ AI 异步接口 ============
    path('api/ai-analysis/request/', views.request_ai_analysis, name='request_ai_analysis'),
    path('api/ai-analysis/status/', views.poll_ai_status, name='poll_ai_status'),
]