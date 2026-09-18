from django.contrib import admin

from .models import Article, Author, Category, Event, NewsletterSubscriber, Region, Tag, Volume


@admin.register(Region)
class RegionAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'article_count')
    search_fields = ('name', 'code')


@admin.register(Author)
class AuthorAdmin(admin.ModelAdmin):
    list_display = ('name', 'region')
    list_filter = ('region',)
    search_fields = ('name',)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('label', 'slug', 'color_variant')
    prepopulated_fields = {'slug': ('label',)}


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ('label', 'slug', 'usage_count')
    search_fields = ('label',)


@admin.register(Volume)
class VolumeAdmin(admin.ModelAdmin):
    list_display = ('code', 'title', 'author')
    search_fields = ('title', 'code')


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ('title', 'starts_at', 'location', 'status')
    list_filter = ('status',)
    search_fields = ('title', 'location')
    prepopulated_fields = {'slug': ('title',)}


@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = ('title', 'category', 'author', 'status', 'published_at')
    list_filter = ('status', 'category', 'has_narration')
    search_fields = ('title', 'excerpt', 'body')
    prepopulated_fields = {'slug': ('title',)}
    filter_horizontal = ('tags',)
    autocomplete_fields = ('author', 'region')
    date_hierarchy = 'published_at'


@admin.register(NewsletterSubscriber)
class NewsletterSubscriberAdmin(admin.ModelAdmin):
    list_display = ('email', 'created_at')
    search_fields = ('email',)
    ordering = ('-created_at',)


admin.site.site_header = 'El Hacedor · Panel'
admin.site.site_title = 'El Hacedor'
admin.site.index_title = 'Gestión editorial'
