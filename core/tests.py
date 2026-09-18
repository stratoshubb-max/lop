import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from .models import Bookmark, Follow, Post, PostLike, PostRepost, Profile

User = get_user_model()


class SocialApiTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="owner", password="owner-pass-123")
        Profile.objects.create(user=self.owner, display_name="ليان", handle="owner", avatar_initial="ل")
        self.user = User.objects.create_user(username="tester", password="tester-pass-123")
        Profile.objects.create(user=self.user, display_name="مختبر", handle="tester", avatar_initial="م")
        self.post = Post.objects.create(
            author=self.owner,
            author_name="ليان",
            handle="owner",
            avatar_initial="ل",
            avatar_tone="violet",
            body="منشور حقيقي للاختبار.",
            published_at=timezone.now(),
        )
        self.client.login(username="tester", password="tester-pass-123")
        response = self.client.get("/")
        self.csrf = response.cookies["csrftoken"].value
        self.headers = {"HTTP_X_CSRFTOKEN": self.csrf, "HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}

    def json_post(self, url, payload):
        return self.client.post(url, data=json.dumps(payload), content_type="application/json", **self.headers)

    def test_post_is_persisted_with_authenticated_profile(self):
        response = self.json_post("/api/posts/", {"body": "فكرة تعيش في قاعدة البيانات."})
        self.assertEqual(response.status_code, 201)
        post = Post.objects.get(body="فكرة تعيش في قاعدة البيانات.")
        self.assertEqual(post.author, self.user)
        self.assertEqual(response.json()["post"]["handle"], "tester")

    def test_reactions_are_database_backed_and_toggle(self):
        response = self.json_post(f"/api/posts/{self.post.id}/like/", {})
        self.assertTrue(response.json()["active"])
        self.assertEqual(PostLike.objects.count(), 1)

        response = self.json_post(f"/api/posts/{self.post.id}/like/", {})
        self.assertFalse(response.json()["active"])
        self.assertEqual(PostLike.objects.count(), 0)

        self.assertTrue(self.json_post(f"/api/posts/{self.post.id}/repost/", {}).json()["active"])
        self.assertTrue(self.json_post(f"/api/posts/{self.post.id}/bookmark/", {}).json()["active"])
        self.assertEqual(PostRepost.objects.count(), 1)
        self.assertEqual(Bookmark.objects.count(), 1)

    def test_follow_search_and_reply_use_real_records(self):
        response = self.json_post("/api/profiles/owner/follow/", {})
        self.assertTrue(response.json()["following"])
        self.assertEqual(Follow.objects.count(), 1)

        response = self.json_post(f"/api/posts/{self.post.id}/reply/", {"body": "هذا الرد محفوظ فعلًا."})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Post.objects.filter(parent_id=self.post.id).count(), 1)

        response = self.client.get("/api/posts/?q=حقيقي")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["posts"])

    def test_anonymous_mutations_require_authentication(self):
        self.client.logout()
        response = self.client.post(
            "/api/posts/",
            data=json.dumps({"body": "غير مسموح"}),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(response.status_code, 401)
        self.assertTrue(response.json()["requires_auth"])

    def test_registration_creates_an_authenticated_profile(self):
        self.client.logout()
        response = self.json_post(
            "/api/auth/register/",
            {"display_name": "مستخدم جديد", "handle": "new.person", "password": "strongpass123"},
        )
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json()["ok"])
        self.assertTrue(Profile.objects.filter(handle="new.person").exists())
        self.assertTrue(response.wsgi_request.user.is_authenticated)
