from django.urls import path

from . import views

urlpatterns = [
    path('articles/', views.ArticleListView.as_view(), name='article-list'),
    path('articles/featured/', views.ArticleFeaturedView.as_view(), name='article-featured'),
    path('articles/trending/', views.ArticleTrendingView.as_view(), name='article-trending'),
    path('articles/<slug:slug>/', views.ArticleDetailView.as_view(), name='article-detail'),
    path('articles/<slug:slug>/related/', views.ArticleRelatedView.as_view(), name='article-related'),
    path('regions/', views.RegionListView.as_view(), name='region-list'),
    path('regions/<str:code>/', views.RegionDetailView.as_view(), name='region-detail'),
    path('regions/<str:code>/authors/', views.RegionAuthorsView.as_view(), name='region-authors'),
    path('volumes/', views.VolumeListView.as_view(), name='volume-list'),
    path('tags/', views.TagListView.as_view(), name='tag-list'),
    path('tags/<slug:slug>/', views.TagDetailView.as_view(), name='tag-detail'),
    path('categories/', views.CategoryListView.as_view(), name='category-list'),
    path('categories/<slug:slug>/', views.CategoryDetailView.as_view(), name='category-detail'),
    path('events/', views.EventListView.as_view(), name='event-list'),
    path('library/', views.LibraryListView.as_view(), name='library-list'),
    path('library/<slug:slug>/', views.LibraryDetailView.as_view(), name='library-detail'),
    path('newsletter/', views.NewsletterSubscribeView.as_view(), name='newsletter-subscribe'),
]
