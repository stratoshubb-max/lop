import json

from django.test import TestCase

from .models import Bookmark, Follow, Post, PostLike, PostRepost, Profile


class SocialApiTests(TestCase):
    def setUp(self):
        response = self.client.get("/")
        self.csrf = response.cookies["csrftoken"].value
        self.headers = {"HTTP_X_CSRFTOKEN": self.csrf, "HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}

    def json_post(self, url, payload):
        return self.client.post(
            url,
            data=json.dumps(payload),
            content_type="application/json",
            **self.headers,
        )

    def test_post_is_persisted_with_guest_profile(self):
        response = self.json_post("/api/posts/", {"body": "فكرة تعيش في قاعدة البيانات."})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Post.objects.filter(body="فكرة تعيش في قاعدة البيانات.").count(), 1)
        self.assertEqual(response.json()["post"]["handle"], "you")

    def test_reactions_are_database_backed_and_toggle(self):
        post_id = 1
        response = self.json_post(f"/api/posts/{post_id}/like/", {})
        self.assertTrue(response.json()["active"])
        self.assertEqual(PostLike.objects.count(), 1)

        response = self.json_post(f"/api/posts/{post_id}/like/", {})
        self.assertFalse(response.json()["active"])
        self.assertEqual(PostLike.objects.count(), 0)

        self.assertTrue(self.json_post(f"/api/posts/{post_id}/repost/", {}).json()["active"])
        self.assertTrue(self.json_post(f"/api/posts/{post_id}/bookmark/", {}).json()["active"])
        self.assertEqual(PostRepost.objects.count(), 1)
        self.assertEqual(Bookmark.objects.count(), 1)

    def test_follow_search_and_reply_use_real_records(self):
        response = self.json_post("/api/profiles/huda.a/follow/", {})
        self.assertTrue(response.json()["following"])
        self.assertEqual(Follow.objects.count(), 1)

        response = self.json_post("/api/posts/1/reply/", {"body": "هذا الرد محفوظ فعلًا."})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Post.objects.filter(parent_id=1).count(), 1)

        response = self.client.get("/api/posts/?q=تصميم")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["posts"])

    def test_registration_creates_an_authenticated_profile(self):
        response = self.json_post(
            "/api/auth/register/",
            {"display_name": "مستخدم جديد", "handle": "new.person", "password": "strongpass123"},
        )
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json()["ok"])
        self.assertTrue(Profile.objects.filter(handle="new.person").exists())
        self.assertTrue(response.wsgi_request.user.is_authenticated)
