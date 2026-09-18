from django.contrib import admin

from .models import Post


@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = ("author_name", "handle", "published_label", "likes", "verified")
    list_filter = ("verified", "following")
    search_fields = ("author_name", "handle", "body")
