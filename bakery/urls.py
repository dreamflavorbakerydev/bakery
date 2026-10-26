from django.urls import path
from bakery import views
from bakery import workspace
from bakery import order_views

urlpatterns = [
    path('orders/', order_views.order_list, name='orders'),
    path('orders/new/', order_views.new_order, name='order-new'),
    path('orders/prices/', order_views.order_prices, name='order-prices'),
    path('orders/notifications/', order_views.order_notifications, name='order-notifications'),
    path('orders/<int:pk>/', order_views.order_detail, name='order-detail'),
    path('orders/<int:pk>/submit/', order_views.order_submit, name='order-submit'),
    path('orders/<int:pk>/status/', order_views.order_status, name='order-status'),
    path('production/', order_views.bake_plan, name='bake-plan'),
    path('', views.dashboard, name='dashboard'),
    path('customers/', views.customers, name='customers'),
    path('customers/new/', workspace.customer_editor, name='customer-new'),
    path('customers/<int:pk>/edit/', workspace.customer_editor, name='customer-edit'),
    path('customers/<int:pk>/catalog/', views.catalog, name='catalog'),
    path('products/', views.products, name='products'),
    path('products/price-records/', views.price_records, name='price-records'),
    path('products/special-prices/', workspace.records, {'kind': 'overrides'}, name='special-prices'),
    path('products/special-prices/<int:pk>/delete/', workspace.special_price_delete, name='special-price-delete'),
    path('pricing/', views.pricing, name='pricing'),
    path('imports/', views.import_data, name='imports'),
    path('imports/template/<str:kind>/', views.import_template, name='import-template'),
    path('account/', views.account, name='account'),
    path('administration/', workspace.administration, name='administration'),
    path('administration/users/', workspace.users, name='workspace-users'),
    path('administration/users/new/', workspace.user_create, name='workspace-user-create'),
    path('administration/users/<int:pk>/edit/', workspace.user_edit, name='workspace-user-edit'),
    path('administration/audit/', workspace.audit_trail, name='workspace-audit'),
    path('administration/<str:kind>/', workspace.records, name='workspace-records'),
    path('administration/<str:kind>/new/', workspace.record_editor, name='workspace-record-new'),
    path('administration/<str:kind>/<int:pk>/edit/', workspace.record_editor, name='workspace-record-edit'),
    path('products/<int:pk>/', workspace.product_detail, name='product-detail'),
    path('products/<int:pk>/prices/', workspace.product_prices, name='product-prices'),
    path('customers/<int:pk>/', workspace.customer_detail, name='customer-detail'),
]
