from django.conf import settings
from django.db import models
from django.utils import timezone


class Profile(models.Model):
    """Public identity used by the social layer."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    display_name = models.CharField(max_length=80)
    handle = models.SlugField(max_length=40, unique=True)
    avatar_initial = models.CharField(max_length=3, default="أ")
    avatar_tone = models.CharField(max_length=30, default="violet")
    # Cropped profile photo stored as a data-URL (jpeg/png/webp, small square).
    # Kept as text so it works on SQLite and Supabase Postgres with no media bucket.
    avatar_image = models.TextField(blank=True, default="")
    bio = models.CharField(max_length=160, blank=True)
    verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["display_name"]
        verbose_name = "ملف شخصي"
        verbose_name_plural = "ملفات شخصية"

    def __str__(self):
        return f"{self.display_name} (@{self.handle})"


class Follow(models.Model):
    follower = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="following_links")
    following = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="follower_links")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["follower", "following"], name="unique_profile_follow"),
            models.CheckConstraint(check=~models.Q(follower=models.F("following")), name="profile_cannot_follow_self"),
        ]
        ordering = ["-created_at"]


class Topic(models.Model):
    category = models.CharField(max_length=80)
    name = models.CharField(max_length=120, unique=True)
    rank = models.PositiveIntegerField(default=1, db_index=True)

    class Meta:
        ordering = ["rank", "name"]
        verbose_name = "موضوع"
        verbose_name_plural = "مواضيع"

    def __str__(self):
        return self.name


class Post(models.Model):
    """A database-backed short post in the public أثر feed."""

    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="posts")
    # These denormalized author fields keep existing content readable if an account is removed.
    author_name = models.CharField(max_length=80)
    handle = models.CharField(max_length=40)
    avatar_initial = models.CharField(max_length=3, default="أ")
    avatar_tone = models.CharField(max_length=30, default="violet")
    # Denormalized copy of the author's cropped photo at publish time.
    avatar_image = models.TextField(blank=True, default="")
    body = models.TextField(max_length=500)
    tags = models.JSONField(default=list, blank=True)
    topic = models.ForeignKey(Topic, null=True, blank=True, on_delete=models.SET_NULL, related_name="posts")
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.CASCADE, related_name="replies_to")
    published_at = models.DateTimeField(default=timezone.now, db_index=True)
    published_label = models.CharField(max_length=40, default="الآن")
    verified = models.BooleanField(default=False)
    # Seed counts are retained as a baseline; new interactions are stored below.
    likes = models.PositiveIntegerField(default=0)
    replies = models.PositiveIntegerField(default=0)
    reposts = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-published_at"]
        verbose_name = "منشور"
        verbose_name_plural = "منشورات"
        indexes = [
            models.Index(fields=["-published_at"], name="post_pub_desc_idx"),
            models.Index(fields=["parent", "-published_at"], name="post_parent_pub_idx"),
        ]

    def __str__(self):
        return f"{self.author_name}: {self.body[:42]}"


class PostLike(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="post_likes")
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="like_events")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "post"], name="unique_post_like")]


class PostRepost(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="post_reposts")
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="repost_events")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "post"], name="unique_post_repost")]


class Bookmark(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="bookmarks")
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="bookmark_events")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "post"], name="unique_post_bookmark")]
