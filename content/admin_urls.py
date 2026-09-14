from django.urls import path

from . import admin_views

urlpatterns = [
    path('articles/', admin_views.AdminArticleListCreateView.as_view(), name='admin-article-list'),
    path('articles/<int:pk>/', admin_views.AdminArticleDetailView.as_view(), name='admin-article-detail'),
    path('articles/<int:pk>/trash/', admin_views.AdminArticleTrashView.as_view(), name='admin-article-trash'),
    path('articles/<int:pk>/restore/', admin_views.AdminArticleRestoreView.as_view(), name='admin-article-restore'),
    path('authors/', admin_views.AdminAuthorListCreateView.as_view(), name='admin-author-list'),
    path('authors/<int:pk>/', admin_views.AdminAuthorDeleteView.as_view(), name='admin-author-delete'),
    path('tags/', admin_views.AdminTagListCreateView.as_view(), name='admin-tag-list'),
    path('tags/<int:pk>/', admin_views.AdminTagDeleteView.as_view(), name='admin-tag-delete'),
    path('regions/', admin_views.AdminRegionListCreateView.as_view(), name='admin-region-list'),
    path('regions/<int:pk>/', admin_views.AdminRegionDeleteView.as_view(), name='admin-region-delete'),
    path('categories/', admin_views.AdminCategoryListView.as_view(), name='admin-category-list'),
    path('categories/<slug:slug>/', admin_views.AdminCategoryUpdateView.as_view(), name='admin-category-update'),
]
