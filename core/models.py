from django.db import models


class Post(models.Model):
    """A small, intentionally focused model for the public أثر feed."""

    author_name = models.CharField(max_length=80)
    handle = models.CharField(max_length=40)
    avatar_initial = models.CharField(max_length=3, default="أ")
    avatar_tone = models.CharField(max_length=30, default="violet")
    body = models.TextField(max_length=500)
    tags = models.JSONField(default=list, blank=True)
    published_at = models.DateTimeField()
    published_label = models.CharField(max_length=40, default="الآن")
    verified = models.BooleanField(default=False)
    following = models.BooleanField(default=False)
    likes = models.PositiveIntegerField(default=0)
    replies = models.PositiveIntegerField(default=0)
    reposts = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-published_at"]
        verbose_name = "منشور"
        verbose_name_plural = "منشورات"

    def __str__(self):
        return f"{self.author_name}: {self.body[:42]}"
