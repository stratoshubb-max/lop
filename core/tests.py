import base64
import json
import pathlib
import struct
import zlib

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from . import ai, media
from .models import Bookmark, Follow, Post, PostLike, PostRepost, Profile, Topic

User = get_user_model()


def tiny_png(width=8, height=8, colour=(120, 200, 140)):
    """A real, valid PNG built without Pillow so tests exercise both paths."""
    raw = b"".join(b"\x00" + bytes(colour) * width for _ in range(height))

    def chunk(tag, data):
        payload = tag + data
        return struct.pack(">I", len(data)) + payload + struct.pack(">I", zlib.crc32(payload) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )
    return png


def data_url(png_bytes, mime="image/png"):
    return f"data:{mime};base64,{base64.b64encode(png_bytes).decode()}"


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

    def json_post(self, url, payload, **extra):
        headers = {**self.headers, **extra}
        return self.client.post(url, data=json.dumps(payload), content_type="application/json", **headers)

    # ------------------------------------------------------------------ #
    # Core social behaviour
    # ------------------------------------------------------------------ #
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
            {"display_name": "مستخدم جديد", "handle": "@new.person", "password": "strongpass123"},
        )
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json()["ok"])
        self.assertTrue(Profile.objects.filter(handle="new.person").exists())
        self.assertTrue(response.wsgi_request.user.is_authenticated)

    def test_login_and_logout_api(self):
        response = self.json_post("/api/auth/logout/", {})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])

        response = self.json_post("/api/auth/login/", {"username": "@tester", "password": "tester-pass-123"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])

    def test_post_hashtag_extraction_and_topic_linking(self):
        response = self.json_post("/api/posts/", {"body": "فكرة ملهمة عن #البرمجة والتصميم #إبداع"})
        self.assertEqual(response.status_code, 201)
        post_data = response.json()["post"]
        self.assertIn("البرمجة", post_data["tags"])
        self.assertIn("إبداع", post_data["tags"])
        post = Post.objects.get(id=post_data["id"])
        self.assertIsNotNone(post.topic)
        self.assertEqual(post.topic.name, "البرمجة")
        self.assertTrue(post.topic.category)

    def test_health_check_api(self):
        response = self.client.get("/api/health/")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "healthy")
        self.assertIn("ai", payload)
        self.assertIn("posts", payload)

    def test_post_deletion_permissions(self):
        response = self.json_post(f"/api/posts/{self.post.id}/delete/", {})
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Post.objects.filter(id=self.post.id).exists())

        create_res = self.json_post("/api/posts/", {"body": "منشور سيتم حذفه"})
        own_post_id = create_res.json()["post"]["id"]
        del_res = self.json_post(f"/api/posts/{own_post_id}/delete/", {})
        self.assertEqual(del_res.status_code, 200)
        self.assertTrue(del_res.json()["deleted"])
        self.assertFalse(Post.objects.filter(id=own_post_id).exists())

    def test_bookmarks_tab_filtering(self):
        self.json_post(f"/api/posts/{self.post.id}/bookmark/", {})
        res = self.client.get("/api/posts/?tab=bookmarks")
        self.assertEqual(res.status_code, 200)
        posts = res.json()["posts"]
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]["id"], self.post.id)

    def test_update_profile(self):
        res = self.json_post("/api/auth/update_profile/", {"bio": "مطور شغوف", "display_name": "مختبر متميز"})
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["ok"])
        profile = Profile.objects.get(handle="tester")
        self.assertEqual(profile.bio, "مطور شغوف")
        self.assertEqual(profile.display_name, "مختبر متميز")

    def test_csrf_exempt_allows_iframe_requests_without_tokens(self):
        client = self.client_class(enforce_csrf_checks=True)
        res = client.post(
            "/api/auth/login/",
            data=json.dumps({"username": "tester", "password": "tester-pass-123"}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["ok"])

    def test_registration_with_display_name_emojis_and_unique_username_rules(self):
        self.client.logout()
        response = self.json_post(
            "/api/auth/register/",
            {"display_name": "Sarah Connor ✦✨🔥", "handle": "@s", "password": "strongpassword123"},
        )
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json()["ok"])
        profile = Profile.objects.get(handle="s")
        self.assertEqual(profile.display_name, "Sarah Connor ✦✨🔥")

        dup_res = self.json_post(
            "/api/auth/register/",
            {"display_name": "Another Person", "handle": "s", "password": "strongpassword123"},
        )
        self.assertEqual(dup_res.status_code, 409)

        allowed_res = self.json_post(
            "/api/auth/register/",
            {"display_name": "Sarah Connor ✦✨🔥", "handle": "s2", "password": "strongpassword123"},
        )
        self.assertEqual(allowed_res.status_code, 201)

        too_long_res = self.json_post(
            "/api/auth/register/",
            {"display_name": "Valid Name", "handle": "a" * 31, "password": "strongpassword123"},
        )
        self.assertEqual(too_long_res.status_code, 400)

        absurd_name_res = self.json_post(
            "/api/auth/register/",
            {"display_name": "X" * 51, "handle": "validuser", "password": "strongpassword123"},
        )
        self.assertEqual(absurd_name_res.status_code, 400)

    def test_user_is_logged_in_after_registration_on_next_request(self):
        client = self.client_class()
        res = client.post(
            "/api/auth/register/",
            data=json.dumps({"display_name": "Alex Smith", "handle": "alex_smith", "password": "password1234"}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 201)
        home_res = client.get("/")
        self.assertEqual(home_res.status_code, 200)
        self.assertTrue(home_res.context["authenticated"])
        self.assertEqual(home_res.context["viewer"].handle, "alex_smith")
        self.assertNotContains(home_res, 'class="hero-panel feed-heading"')
        self.assertNotContains(home_res, 'Who to Follow')
        self.assertNotContains(home_res, '${icons.reply}')

    def test_guest_sees_top_hero_panel_and_no_reply_dollar_bug(self):
        client = self.client_class()
        home_res = client.get("/")
        self.assertEqual(home_res.status_code, 200)
        self.assertFalse(home_res.context["authenticated"])
        self.assertContains(home_res, 'class="hero-panel feed-heading"')
        self.assertNotContains(home_res, 'Who to Follow')
        self.assertNotContains(home_res, '${icons.reply}')

    def test_twitter_profile_page_rendering(self):
        client = self.client_class()
        response = client.get(f"/u/{self.owner.username}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["profile"].handle, "owner")
        self.assertContains(response, "@owner")
        self.assertContains(response, "profile-cover-banner")
        self.assertContains(response, "profile-tabs-bar")
        self.assertContains(response, "Follow")

    def test_profile_page_owner_controls(self):
        client = self.client_class()
        client.force_login(self.owner)
        response = client.get(f"/u/{self.owner.username}/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["is_owner"])
        self.assertContains(response, "Edit profile")

    def test_profile_tabs_api(self):
        client = self.client_class()
        orig = Post.objects.create(
            author=self.owner,
            body="Original thought by owner",
            author_name="Layan",
            handle="owner",
            avatar_initial="L",
            avatar_tone="violet",
            published_at=timezone.now(),
        )
        reply = Post.objects.create(
            author=self.user,
            parent=orig,
            body="Reply to owner",
            author_name="Tester",
            handle="tester",
            avatar_initial="T",
            avatar_tone="mint",
            published_at=timezone.now(),
        )
        PostLike.objects.create(user=self.user, post=orig)

        thoughts_res = client.get("/api/profiles/owner/posts/?tab=thoughts")
        self.assertEqual(thoughts_res.status_code, 200)
        self.assertTrue(any(p["id"] == orig.id for p in thoughts_res.json()["posts"]))

        replies_res = client.get("/api/profiles/tester/posts/?tab=replies")
        self.assertEqual(replies_res.status_code, 200)
        self.assertEqual(len(replies_res.json()["posts"]), 1)
        self.assertEqual(replies_res.json()["posts"][0]["id"], reply.id)

        likes_res = client.get("/api/profiles/tester/posts/?tab=likes")
        self.assertEqual(likes_res.status_code, 200)
        self.assertEqual(likes_res.json()["posts"][0]["id"], orig.id)

    def test_update_profile_and_syncs_posts(self):
        client = self.client_class()
        client.force_login(self.user)
        response = client.get("/")
        csrf = response.cookies["csrftoken"].value
        user_post = Post.objects.create(
            author=self.user,
            body="Old thought by tester",
            author_name="Old Tester",
            handle="tester",
            avatar_initial="T",
            avatar_tone="mint",
            published_at=timezone.now(),
        )
        res = client.post(
            "/api/auth/update_profile/",
            data=json.dumps({
                "display_name": "Alex ✦",
                "bio": "Writer & thinker exploring quiet spaces.",
                "avatar_tone": "gold",
            }),
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf,
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["profile"]["display_name"], "Alex ✦")
        self.assertEqual(data["profile"]["avatar_tone"], "gold")

        user_profile = self.user.profile
        user_profile.refresh_from_db()
        self.assertEqual(user_profile.display_name, "Alex ✦")
        self.assertEqual(user_profile.bio, "Writer & thinker exploring quiet spaces.")
        self.assertEqual(user_profile.avatar_tone, "gold")

        user_post.refresh_from_db()
        self.assertEqual(user_post.author_name, "Alex ✦")
        self.assertEqual(user_post.avatar_tone, "gold")

    def test_profile_not_found_returns_404(self):
        client = self.client_class()
        res = client.get("/u/nobody_here_xyz/")
        self.assertEqual(res.status_code, 404)
        self.assertContains(res, "This account doesn't exist", status_code=404)

    def test_website_settings_modal_rendered(self):
        client = self.client_class()
        res = client.get("/")
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'id="websiteSettingsModal"')
        self.assertContains(res, "Dark Obsidian")
        self.assertContains(res, "Warm Paper")
        self.assertContains(res, "System Default")

    # ------------------------------------------------------------------ #
    # Security: CSRF for cookie sessions, token auth for iframes
    # ------------------------------------------------------------------ #
    def test_cookie_session_mutations_require_csrf(self):
        res = self.client.post(
            "/api/posts/",
            data=json.dumps({"body": "no csrf header"}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 403)
        self.assertTrue(res.json()["csrf_failed"])

    def test_session_token_authenticates_without_cookies(self):
        response = self.json_post("/api/auth/login/", {"username": "tester", "password": "tester-pass-123"})
        token = response.json()["token"]
        self.assertTrue(token)

        client = self.client_class()
        client.cookies.clear()
        res = client.post(
            "/api/posts/",
            data=json.dumps({"body": "posted from an iframe via token"}),
            content_type="application/json",
            HTTP_X_SESSION_TOKEN=token,
        )
        self.assertEqual(res.status_code, 201)
        self.assertEqual(Post.objects.get(body="posted from an iframe via token").author, self.user)

    # ------------------------------------------------------------------ #
    # Feed, threads, pagination, search
    # ------------------------------------------------------------------ #
    def test_replies_stay_out_of_the_main_feed(self):
        self.json_post(f"/api/posts/{self.post.id}/reply/", {"body": "A reply that should not top the feed"})
        res = self.client.get("/api/posts/?tab=all")
        bodies = [post["body"] for post in res.json()["posts"]]
        self.assertNotIn("A reply that should not top the feed", bodies)

    def test_feed_pagination_and_sorting(self):
        for index in range(6):
            Post.objects.create(
                author=self.owner,
                author_name="ليان",
                handle="owner",
                avatar_initial="ل",
                body=f"Thought number {index}",
                likes=index,
                published_at=timezone.now(),
            )
        first = self.client.get("/api/posts/?limit=3&offset=0").json()
        second = self.client.get("/api/posts/?limit=3&offset=3").json()
        self.assertEqual(len(first["posts"]), 3)
        self.assertTrue(first["has_more"])
        self.assertEqual(first["next_offset"], 3)
        self.assertNotEqual(first["posts"][0]["id"], second["posts"][0]["id"])

        top = self.client.get("/api/posts/?sort=top").json()
        self.assertGreaterEqual(top["posts"][0]["likes"], top["posts"][-1]["likes"])

        trending = self.client.get("/api/posts/?sort=trending").json()
        self.assertEqual(len(trending["posts"]), 7)

    def test_thread_page_and_detail_api(self):
        reply = Post.objects.create(
            author=self.user,
            parent=self.post,
            body="A threaded reply",
            author_name="Tester",
            handle="tester",
            avatar_initial="T",
            avatar_tone="mint",
            published_at=timezone.now(),
        )
        page = self.client.get(f"/p/{self.post.id}/")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "A threaded reply")
        self.assertContains(page, 'data-page="thread"')

        api = self.client.get(f"/api/posts/{self.post.id}/")
        payload = api.json()
        self.assertEqual(api.status_code, 200)
        self.assertEqual(payload["post"]["id"], self.post.id)
        self.assertEqual(payload["replies"][0]["id"], reply.id)
        self.assertIn("permalink", payload["post"])

    def test_search_api_returns_posts_people_and_topics(self):
        Topic.objects.create(category="Writing", name="writing", rank=1)
        Post.objects.create(
            author=self.owner,
            author_name="ليان",
            handle="owner",
            body="Notes about writing slowly and deliberately.",
            topic=Topic.objects.get(name="writing"),
            published_at=timezone.now(),
        )
        res = self.client.get("/api/search/?q=writing")
        self.assertEqual(res.status_code, 200)
        payload = res.json()
        self.assertTrue(payload["posts"])
        self.assertTrue(payload["topics"])
        self.assertIn("summary", payload["insights"])

    def test_follow_is_case_insensitive_and_lists_people(self):
        res = self.json_post("/api/profiles/OWNER/follow/", {})
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["following"])

        followers = self.client.get("/api/profiles/owner/followers/").json()
        self.assertEqual(followers["count"], 1)
        self.assertEqual(followers["people"][0]["handle"], "tester")

        following = self.client.get("/api/profiles/tester/following/").json()
        self.assertEqual(following["people"][0]["handle"], "owner")

    def test_suggestions_and_topics_api(self):
        Topic.objects.create(category="Learning", name="learning", rank=2)
        Post.objects.create(
            author=self.owner,
            author_name="ليان",
            handle="owner",
            body="Learning in public about learning",
            topic=Topic.objects.get(name="learning"),
            published_at=timezone.now(),
        )
        suggestions = self.client.get("/api/suggestions/").json()
        self.assertIn("people", suggestions)
        self.assertTrue(any(person["handle"] == "owner" for person in suggestions["people"]))

        topics = self.client.get("/api/topics/").json()
        self.assertTrue(topics["topics"])
        self.assertIn("momentum", topics["topics"][0])

    def test_post_edit_permissions_and_content(self):
        own = Post.objects.create(
            author=self.user,
            author_name="Tester",
            handle="tester",
            body="Original body text",
            published_at=timezone.now(),
        )
        res = self.json_post(f"/api/posts/{own.id}/edit/", {"body": "Edited body text about #focus"})
        self.assertEqual(res.status_code, 200)
        payload = res.json()["post"]
        self.assertEqual(payload["body"], "Edited body text about #focus")
        self.assertTrue(payload["edited"])
        own.refresh_from_db()
        self.assertIsNotNone(own.edited_at)

        forbidden = self.json_post(f"/api/posts/{self.post.id}/edit/", {"body": "hijacked"})
        self.assertEqual(forbidden.status_code, 403)

    def test_post_length_limit_enforced(self):
        res = self.json_post("/api/posts/", {"body": "x" * 501})
        self.assertEqual(res.status_code, 400)

    def test_handle_change_updates_existing_posts(self):
        own = Post.objects.create(
            author=self.user,
            author_name="Tester",
            handle="tester",
            body="Thought before rename",
            published_at=timezone.now(),
        )
        res = self.json_post("/api/auth/update_profile/", {"handle": "tester-renamed"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["profile"]["handle"], "tester-renamed")
        self.post.refresh_from_db()
        own.refresh_from_db()
        self.assertEqual(own.handle, "tester-renamed")
        self.assertEqual(User.objects.get(pk=self.user.pk).username, "tester-renamed")

    def test_change_password(self):
        res = self.json_post("/api/auth/change_password/", {"current_password": "wrong", "new_password": "brandnewpass1"})
        self.assertEqual(res.status_code, 400)
        res = self.json_post("/api/auth/change_password/", {"current_password": "tester-pass-123", "new_password": "brandnewpass1"})
        self.assertEqual(res.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("brandnewpass1"))

    # ------------------------------------------------------------------ #
    # Profile pictures & attachments
    # ------------------------------------------------------------------ #
    def test_profile_picture_upload_serve_and_remove(self):
        png = tiny_png(32, 32)
        res = self.json_post("/api/auth/update_profile/", {"avatar_data": data_url(png)})
        self.assertEqual(res.status_code, 200)
        profile = Profile.objects.get(handle="tester")
        profile.refresh_from_db()
        self.assertTrue(profile.has_avatar)
        self.assertEqual(profile.avatar_version, 1)
        self.assertIn(profile.avatar_url, res.json()["profile"]["avatar_url"])

        image = self.client.get(profile.avatar_url)
        self.assertEqual(image.status_code, 200)
        self.assertIn(image["Content-Type"], ("image/png", "image/jpeg", "image/webp"))
        self.assertIn("immutable", image["Cache-Control"])
        self.assertTrue(image.headers.get("ETag"))

        cached = self.client.get(profile.avatar_url, HTTP_IF_NONE_MATCH=image["ETag"])
        self.assertEqual(cached.status_code, 304)

        old_url = profile.avatar_url
        removed = self.json_post("/api/auth/update_profile/", {"remove_avatar": True})
        self.assertEqual(removed.status_code, 200)
        profile.refresh_from_db()
        self.assertFalse(profile.has_avatar)
        self.assertEqual(profile.avatar_url, "")
        self.assertEqual(self.client.get(old_url).status_code, 404)

    def test_replacing_a_picture_retires_the_previous_version_url(self):
        self.json_post("/api/auth/update_profile/", {"avatar_data": data_url(tiny_png(28, 28))})
        profile = Profile.objects.get(handle="tester")
        profile.refresh_from_db()
        first_url = profile.avatar_url
        self.assertEqual(self.client.get(first_url).status_code, 200)

        self.json_post("/api/auth/update_profile/", {"avatar_data": data_url(tiny_png(40, 24, (200, 90, 60)))})
        profile.refresh_from_db()
        self.assertEqual(profile.avatar_version, 2)
        self.assertNotEqual(profile.avatar_url, first_url)
        self.assertEqual(self.client.get(first_url).status_code, 404,
                         "a replaced picture must not keep serving as an immutable asset")
        self.assertEqual(self.client.get(profile.avatar_url).status_code, 200)

    def test_post_image_versions_are_enforced_too(self):
        res = self.json_post("/api/posts/", {"body": "Versioned photo", "image_data": data_url(tiny_png(30, 30))})
        url = res.json()["post"]["image_url"]
        self.assertEqual(self.client.get(url).status_code, 200)
        stale = url.replace("/1/", "/9/")
        self.assertEqual(self.client.get(stale).status_code, 404)

    def test_profile_picture_rejects_non_images_and_oversized_payloads(self):
        res = self.json_post("/api/auth/update_profile/", {"avatar_data": "data:image/png;base64,bm90YW5pbWFnZQ=="})
        self.assertEqual(res.status_code, 400)
        self.assertTrue(res.json()["image_error"])
        self.assertFalse(Profile.objects.get(handle="tester").has_avatar)

    def test_avatar_appears_in_feed_and_profile_markup(self):
        png = tiny_png(24, 24)
        self.json_post("/api/auth/update_profile/", {"avatar_data": data_url(png)})
        profile = Profile.objects.get(handle="tester")
        profile.refresh_from_db()
        body = f"Thought from a face"
        Post.objects.create(author=self.user, author_name="Tester", handle="tester", body=body, published_at=timezone.now())

        feed = self.client.get("/api/posts/?tab=all").json()
        post = [item for item in feed["posts"] if item["body"] == body][0]
        self.assertTrue(post["has_avatar"])
        self.assertIn(profile.avatar_url, post["avatar_url"])

        page = self.client.get("/u/tester/")
        self.assertContains(page, profile.avatar_url)

    def test_post_accepts_an_image_attachment(self):
        png = tiny_png(64, 40)
        res = self.json_post("/api/posts/", {"body": "A photo thought", "image_data": data_url(png)})
        self.assertEqual(res.status_code, 201)
        payload = res.json()["post"]
        self.assertTrue(payload["image_url"])
        binary = self.client.get(payload["image_url"])
        self.assertEqual(binary.status_code, 200)
        self.assertTrue(binary["Content-Length"])

        media_tab = self.client.get("/api/profiles/tester/posts/?tab=media").json()
        self.assertEqual(len(media_tab["posts"]), 1)

    def test_media_module_sniffs_real_bytes(self):
        self.assertEqual(media.sniff_image_mime(tiny_png()), "image/png")
        self.assertIsNone(media.sniff_image_mime(b"not an image at all"))

    # ------------------------------------------------------------------ #
    # Assistant (AI) endpoints
    # ------------------------------------------------------------------ #
    def test_ai_coach_reports_tone_readability_and_checks(self):
        res = self.json_post("/api/ai/coach/", {"text": "i think this is a really great idea about writing slowly!!!"})
        self.assertEqual(res.status_code, 200)
        payload = res.json()
        self.assertTrue(payload["ok"])
        self.assertIn("tone", payload)
        self.assertIn("readability", payload)
        self.assertTrue(payload["checks"])
        self.assertIn(payload["provider"], ("athar-local", "hosted", payload["provider"]))

    def test_ai_rewrite_returns_multiple_variants(self):
        res = self.json_post("/api/ai/improve/", {"text": "u cant just ship it without notes dont u think"})
        payload = res.json()
        self.assertGreaterEqual(len(payload["suggestions"]), 3)
        polished = payload["suggestions"][0]["text"]
        self.assertIn("you", polished.lower())
        self.assertNotIn("cant", polished)

    def test_ai_hashtag_and_tone_endpoints(self):
        tags = self.json_post("/api/ai/hashtags/", {"text": "Notes about designing calm interfaces for reading"}).json()
        self.assertTrue(tags["hashtags"])
        self.assertTrue(all(len(str(tag)) > 1 for tag in tags["hashtags"]))

        tone = self.json_post("/api/ai/tone/", {"text": "So grateful for this quiet morning of writing"}).json()
        self.assertIn(tone["tone"]["label"], ("positive", "neutral"))
        self.assertTrue(tone["tone"]["advice"])

    def test_ai_reply_suggestions_use_the_parent_post(self):
        res = self.json_post("/api/ai/reply/", {"post_id": self.post.id})
        self.assertEqual(res.status_code, 200)
        payload = res.json()
        self.assertEqual(len(payload["suggestions"]), 3)
        self.assertTrue(all(item["text"] for item in payload["suggestions"]))

    def test_ai_digest_summarises_the_feed(self):
        for index in range(4):
            Post.objects.create(
                author=self.owner,
                author_name="ليان",
                handle="owner",
                body=f"Reading about attention and focus part {index}?",
                published_at=timezone.now(),
            )
        res = self.client.get("/api/ai/digest/")
        self.assertEqual(res.status_code, 200)
        digest = res.json()["digest"]
        self.assertTrue(digest["summary"])
        self.assertEqual(digest["stats"]["posts"], 5)
        self.assertTrue(digest["themes"])
        self.assertIsInstance(res.json()["topics"], list)

    def test_ai_prompts_work_without_any_draft(self):
        res = self.client.get("/api/ai/prompts/")
        self.assertEqual(res.status_code, 200)
        payload = res.json()
        self.assertGreaterEqual(len(payload["prompts"]), 3)

    def test_ai_thread_summary_endpoint(self):
        res = self.json_post("/api/ai/summary/", {"post_id": self.post.id})
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["summary"])

    def test_ai_moderation_flags_hostile_language(self):
        res = self.json_post("/api/ai/moderate/", {"text": "This is a stupid idea and everyone knows it, SHUT UP NOW"})
        payload = res.json()
        self.assertFalse(payload["safe"])
        self.assertTrue(any(check["level"] == "warn" for check in payload["checks"]))

    def test_assistant_engine_is_deterministic_and_offline(self):
        variants = ai.rewrite_variants("this   is  is a test!!")
        self.assertTrue(variants)
        self.assertEqual(ai.detect_language("هذه فكرة جميلة"), "ar")
        self.assertEqual(ai.detect_language("this is a lovely idea"), "en")
        self.assertTrue(ai.keywords("Attention is the rarest and purest form of generosity", 3))
        summary = ai.summarize(["One long thought about attention.", "Another thought about focus."], 2)
        self.assertTrue(summary["summary"])


class AssistantEnhancementTests(TestCase):
    """The assistant should behave like a real writing partner, offline."""

    def setUp(self):
        self.user = User.objects.create_user(username="writer", password="writer-pass-123")
        Profile.objects.create(user=self.user, display_name="Writer", handle="writer", avatar_initial="W")
        Post.objects.create(
            author=self.user, author_name="Writer", handle="writer", body="A first thought about mornings.",
            published_at=timezone.now(),
        )
        self.client.login(username="writer", password="writer-pass-123")
        response = self.client.get("/")
        self.csrf = response.cookies["csrftoken"].value
        self.headers = {"HTTP_X_CSRFTOKEN": self.csrf, "HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}

    def json_post(self, url, payload, **extra):
        return self.client.post(url, data=json.dumps(payload), content_type="application/json",
                                **{**self.headers, **extra})

    def test_compose_endpoint_returns_live_draft_hints(self):
        res = self.json_post("/api/ai/compose/", {
            "text": "Designing calm interfaces means protecting attention in small ways and",
        })
        self.assertEqual(res.status_code, 200)
        payload = res.json()
        self.assertEqual(payload["action"], "compose")
        self.assertGreater(payload["score"], 40)
        self.assertIn("tone", payload)
        self.assertIn("readability", payload)
        self.assertTrue(payload["hashtags"])
        self.assertTrue(payload["continuation"]["text"], "a Tab completion should be offered")
        self.assertTrue(payload["nudge"])

    def test_compose_endpoint_needs_something_to_read(self):
        res = self.json_post("/api/ai/compose/", {"text": "   "})
        self.assertEqual(res.status_code, 400)

    def test_canonical_tags_fold_word_forms(self):
        self.assertEqual(ai.canonical("designing"), "design")
        self.assertEqual(ai.canonical("interfaces"), "interface")
        self.assertEqual(ai.canonical("cities"), "city")
        self.assertEqual(ai.canonical("morning"), "morning", "real words must survive stemming")
        self.assertEqual(ai.canonical("business"), "business")
        tags = ai.hashtags("Designing designing designs for the designers of interfaces", 4)
        self.assertEqual(tags.count("design"), 1)
        self.assertNotIn("designing", tags)

    def test_hashtags_ignore_filler_words(self):
        tags = ai.hashtags("Following my own thought about the thing I wrote today", 4)
        for weak in ("following", "own", "thing", "today"):
            self.assertNotIn(weak, tags)

    def test_explicit_tags_win_over_generated_ones(self):
        tags = ai.meaningful_tags("Reading about attention #slowweb #quiet", 4)
        self.assertEqual(tags[:2], ["slowweb", "quiet"])

    def test_continuation_completes_connectors_and_questions(self):
        connector = ai.continuation("I keep writing about attention and")
        self.assertTrue(connector["text"])
        self.assertEqual(connector["label"], "Complete the sentence")
        question = ai.continuation("Why do we rush the things that matter?")
        self.assertIn("question", question["label"].lower())
        self.assertTrue(ai.continuation("")["reason"])

    def test_draft_score_rewards_ready_drafts(self):
        empty = ai.draft_score("")
        short = ai.draft_score("too short")
        ready = ai.draft_score("A calm, complete thought about reading slowly and keeping attention in one place.")
        self.assertEqual(empty, 0)
        self.assertLess(short, ready)
        self.assertLessEqual(ready, 100)

    def test_readability_reports_its_method(self):
        brief = ai.readability("Designing calm interfaces means protecting attention in small ways.")
        self.assertEqual(brief["method"], "short-text estimate")
        self.assertGreaterEqual(brief["score"], 50, "a plain short sentence must not read as dense")
        long_form = ai.readability(" ".join(["A long paragraph sentence keeps going and going with several clauses"] * 12))
        self.assertEqual(long_form["method"], "flesch")
        self.assertGreater(brief["score"], long_form["score"])

    def test_digest_describes_the_feed_instead_of_dumping_posts(self):
        for index in range(3):
            Post.objects.create(
                author=self.user, author_name="Writer", handle="writer",
                body=f"Reading about attention and design, note {index}?", published_at=timezone.now(),
            )
        digest = ai.digest(list(Post.objects.all()))
        self.assertIn("thoughts", digest["summary"])
        self.assertTrue(digest["themes"])
        self.assertTrue(all(len(theme["name"]) >= 4 for theme in digest["themes"]))
        self.assertTrue(digest["highlights"])
        self.assertIn("questions", digest["stats"])

    def test_every_assistant_action_answers(self):
        for action in ("coach", "improve", "hashtags", "tone", "shorten", "expand", "compose", "prompts", "reply"):
            payload = self.json_post(f"/api/ai/{action}/", {"text": "A thought worth polishing and sharing today."}).json()
            self.assertTrue(payload.get("ok"), f"{action} should answer with ok=True")
            self.assertEqual(payload.get("provider", "athar-local"), "athar-local")
            self.assertTrue(payload.get("summary") is not None, f"{action} should explain itself")


class FrontendContractTests(TestCase):
    """Guards for the front-end wiring that unit tests cannot click."""

    def setUp(self):
        self.user = User.objects.create_user(username="clicker", password="clicker-pass-123")
        Profile.objects.create(user=self.user, display_name="Clicker", handle="clicker", avatar_initial="C")
        Post.objects.create(author=self.user, author_name="Clicker", handle="clicker", body="Hello world of Athar.")
        self.client.login(username="clicker", password="clicker-pass-123")

    def test_sort_menu_does_not_collide_with_feed_state(self):
        html = self.client.get("/").content.decode()
        self.assertIn('data-sort-option="latest"', html)
        self.assertIn('data-sort-option="top"', html)
        self.assertIn('class="feed-list" id="feedList"', html)
        self.assertIn('data-sort="latest"', html, "the feed container keeps its state attribute")
        script = (pathlib.Path(__file__).parent / "static" / "core" / "js" / "site.js").read_text()
        self.assertNotIn("closest('[data-sort]')", script,
                         "clicking inside the feed must not re-sort the whole list")

    def test_every_page_ships_the_confirmation_dialog(self):
        for url in ("/", "/u/clicker/", "/p/1/", "/u/definitely-missing/"):
            response = self.client.get(url)
            self.assertIn(b'id="confirmLayer"', response.content, f"{url} needs the confirmation dialog")

    def test_composer_ships_the_live_assistant_strip(self):
        html = self.client.get("/").content.decode()
        self.assertIn('id="aiInlineSuggest"', html)
        self.assertIn('id="postInput"', html)
        self.assertIn('id="publishButton"', html)

    def test_profile_settings_offer_the_picture_editor(self):
        html = self.client.get("/u/clicker/").content.decode()
        self.assertIn('id="avatarDropZone"', html)
        self.assertIn('id="avatarFileInput"', html)
        self.assertIn('id="btnRemoveAvatar"', html)
        self.assertIn("data-tone-choice", html)

    def test_feed_items_render_the_actions_the_script_binds(self):
        html = self.client.get("/").content.decode()
        for hook in ('data-action="like"', 'data-action="repost"', 'data-action="bookmark"',
                     'data-post-menu', 'data-action="reply"'):
            self.assertIn(hook, html, f"{hook} is required by site.js")
