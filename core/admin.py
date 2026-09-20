from django.contrib import admin
from django.utils.html import format_html

from .models import Bookmark, Follow, Post, PostLike, PostRepost, Profile, Topic


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("display_name", "handle", "avatar_preview", "has_picture", "verified", "created_at")
    list_filter = ("verified",)
    search_fields = ("display_name", "handle", "bio")
    readonly_fields = ("avatar_preview", "avatar_blob", "avatar_mime", "avatar_hash", "avatar_version", "avatar_updated_at")

    @admin.display(description="Picture")
    def avatar_preview(self, obj):
        if not obj.has_avatar:
            return "—"
        return format_html('<img src="{}" style="width:34px;height:34px;border-radius:50%;object-fit:cover">', obj.avatar_url)

    @admin.display(boolean=True, description="Custom PFP")
    def has_picture(self, obj):
        return obj.has_avatar


@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = ("author_name", "handle", "excerpt", "topic", "published_at", "likes", "replies", "reposts")
    list_filter = ("verified", "topic", "edited_at")
    search_fields = ("author_name", "handle", "body")
    readonly_fields = ("published_at", "image_preview", "image_blob", "image_mime", "image_version", "image_width", "image_height")
    raw_id_fields = ("parent", "author")

    @admin.display(description="Body")
    def excerpt(self, obj):
        return obj.body[:60]

    @admin.display(description="Attachment")
    def image_preview(self, obj):
        if not obj.has_image:
            return "—"
        return format_html('<img src="{}" style="max-width:180px;border-radius:10px">', obj.image_url)


@admin.register(Topic)
class TopicAdmin(admin.ModelAdmin):
    list_display = ("rank", "name", "category", "post_total")
    list_display_links = ("name",)
    ordering = ("rank",)
    list_editable = ("rank", "category")

    @admin.display(description="Posts")
    def post_total(self, obj):
        return obj.posts.count()


@admin.register(Follow)
class FollowAdmin(admin.ModelAdmin):
    list_display = ("follower", "following", "created_at")
    search_fields = ("follower__username", "following__username")


@admin.register(PostLike)
class PostLikeAdmin(admin.ModelAdmin):
    list_display = ("user", "post", "created_at")


@admin.register(PostRepost)
class PostRepostAdmin(admin.ModelAdmin):
    list_display = ("user", "post", "created_at")


@admin.register(Bookmark)
class BookmarkAdmin(admin.ModelAdmin):
    list_display = ("user", "post", "created_at")
