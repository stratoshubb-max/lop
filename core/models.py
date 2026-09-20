from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone


class Profile(models.Model):
    """Public identity used by the social layer."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    display_name = models.CharField(max_length=80)
    handle = models.SlugField(max_length=40, unique=True)
    # Fallback identity for accounts without an uploaded picture.
    avatar_initial = models.CharField(max_length=3, default="أ")
    avatar_tone = models.CharField(max_length=30, default="violet")
    # Profile picture (PFP). Stored as a processed BLOB so it works on any host.
    avatar_blob = models.BinaryField(null=True, blank=True, editable=False)
    avatar_mime = models.CharField(max_length=40, blank=True, default="")
    avatar_hash = models.CharField(max_length=32, blank=True, default="")
    avatar_version = models.PositiveIntegerField(default=0)
    avatar_updated_at = models.DateTimeField(null=True, blank=True)
    bio = models.CharField(max_length=160, blank=True)
    location = models.CharField(max_length=80, blank=True, default="")
    website = models.CharField(max_length=160, blank=True, default="")
    verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["display_name"]
        verbose_name = "ملف شخصي"
        verbose_name_plural = "ملفات شخصية"

    def __str__(self):
        return f"{self.display_name} (@{self.handle})"

    # -- profile picture helpers ------------------------------------------- #
    @property
    def has_avatar(self) -> bool:
        return bool(self.avatar_version and self.avatar_mime)

    @property
    def avatar_url(self) -> str:
        """Cache-busted URL served by the app itself (no media server needed)."""
        if not self.has_avatar:
            return ""
        return reverse("core:avatar-media", kwargs={"handle": self.handle, "version": self.avatar_version})

    @property
    def avatar_bytes(self) -> int:
        try:
            return len(self.avatar_blob or b"")
        except TypeError:
            return 0

    @property
    def avatar_kind(self) -> str:
        return "photo" if self.has_avatar else "initial"

    @property
    def initials(self) -> str:
        name = (self.display_name or self.handle or "A").strip()
        parts = [part for part in name.split() if part]
        if len(parts) >= 2:
            return (parts[0][:1] + parts[1][:1]).upper()
        return name[:2].upper() or "A"


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
    body = models.TextField(max_length=500)
    tags = models.JSONField(default=list, blank=True)
    topic = models.ForeignKey(Topic, null=True, blank=True, on_delete=models.SET_NULL, related_name="posts")
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.CASCADE, related_name="replies_to")
    # Optional image attachment, stored as a processed BLOB (same rationale as avatars).
    image_blob = models.BinaryField(null=True, blank=True, editable=False)
    image_mime = models.CharField(max_length=40, blank=True, default="")
    image_version = models.PositiveIntegerField(default=0)
    image_width = models.PositiveIntegerField(default=0)
    image_height = models.PositiveIntegerField(default=0)
    published_at = models.DateTimeField(default=timezone.now, db_index=True)
    published_label = models.CharField(max_length=40, default="الآن")
    edited_at = models.DateTimeField(null=True, blank=True)
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

    @property
    def has_image(self) -> bool:
        return bool(self.image_version and self.image_mime)

    @property
    def image_url(self) -> str:
        if not self.has_image:
            return ""
        return reverse("core:post-image-media", kwargs={"post_id": self.pk, "version": self.image_version})

    @property
    def image_bytes(self) -> int:
        try:
            return len(self.image_blob or b"")
        except TypeError:
            return 0

    @property
    def is_reply(self) -> bool:
        return self.parent_id is not None

    @property
    def permalink(self) -> str:
        return reverse("core:post-detail", kwargs={"post_id": self.pk})

    @property
    def edited(self) -> bool:
        return self.edited_at is not None


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
