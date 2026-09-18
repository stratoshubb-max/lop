from django.contrib import admin

from .models import Bookmark, Follow, Post, PostLike, PostRepost, Profile, Topic


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("display_name", "handle", "verified", "created_at")
    list_filter = ("verified",)
    search_fields = ("display_name", "handle")


@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = ("author_name", "handle", "published_at", "likes", "replies", "reposts")
    list_filter = ("verified", "topic")
    search_fields = ("author_name", "handle", "body")
    readonly_fields = ("published_at",)


@admin.register(Topic)
class TopicAdmin(admin.ModelAdmin):
    list_display = ("rank", "name", "category")
    ordering = ("rank",)


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
