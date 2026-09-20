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
            {"display_name": "مستخدم جديد", "handle": "@new.person", "password": "strongpass123"},
        )
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json()["ok"])
        self.assertTrue(Profile.objects.filter(handle="new.person").exists())
        self.assertTrue(response.wsgi_request.user.is_authenticated)

    def test_login_and_logout_api(self):
        # Logout
        response = self.json_post("/api/auth/logout/", {})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])

        # Login with @ prefix
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

    def test_health_check_api(self):
        response = self.client.get("/api/health/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "healthy")

    def test_post_deletion_permissions(self):
        # Tester tries to delete owner's post -> 403 Forbidden
        response = self.json_post(f"/api/posts/{self.post.id}/delete/", {})
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Post.objects.filter(id=self.post.id).exists())

        # Tester creates their own post and deletes it -> 200 OK
        create_res = self.json_post("/api/posts/", {"body": "منشور سيتم حذفه"})
        own_post_id = create_res.json()["post"]["id"]
        del_res = self.json_post(f"/api/posts/{own_post_id}/delete/", {})
        self.assertEqual(del_res.status_code, 200)
        self.assertTrue(del_res.json()["deleted"])
        self.assertFalse(Post.objects.filter(id=own_post_id).exists())

    def test_bookmarks_tab_filtering(self):
        # Bookmark post
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
        # Even without CSRF cookie or header (like inside cross-origin preview iframes),
        # API endpoints do not fail with 403 CSRF verification failed.
        client = self.client_class(enforce_csrf_checks=True)
        # Login endpoint without CSRF token
        res = client.post(
            "/api/auth/login/",
            data=json.dumps({"username": "tester", "password": "tester-pass-123"}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["ok"])

    def test_registration_with_display_name_emojis_and_unique_username_rules(self):
        self.client.logout()
        # Register with emojis & symbols in display name, and valid 1-30 char username
        response = self.json_post(
            "/api/auth/register/",
            {"display_name": "Sarah Connor ✦✨🔥", "handle": "@s", "password": "strongpassword123"},
        )
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json()["ok"])
        profile = Profile.objects.get(handle="s")
        self.assertEqual(profile.display_name, "Sarah Connor ✦✨🔥")

        # Duplicate username should fail
        dup_res = self.json_post(
            "/api/auth/register/",
            {"display_name": "Another Person", "handle": "s", "password": "strongpassword123"},
        )
        self.assertEqual(dup_res.status_code, 409)

        # Same display name with different username is ALLOWED
        allowed_res = self.json_post(
            "/api/auth/register/",
            {"display_name": "Sarah Connor ✦✨🔥", "handle": "s2", "password": "strongpassword123"},
        )
        self.assertEqual(allowed_res.status_code, 201)

        # Username too long (> 30 chars) should fail
        too_long_res = self.json_post(
            "/api/auth/register/",
            {"display_name": "Valid Name", "handle": "a" * 31, "password": "strongpassword123"},
        )
        self.assertEqual(too_long_res.status_code, 400)

        # Display name too long (> 50 chars) should fail
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
        # Verify next request to / has the authenticated user
        home_res = client.get("/")
        self.assertEqual(home_res.status_code, 200)
        self.assertTrue(home_res.context["authenticated"])
        self.assertEqual(home_res.context["viewer"].handle, "alex_smith")
        # And the top hero panel does NOT appear when authenticated
        self.assertNotContains(home_res, 'class="hero-panel feed-heading"')
        # And Who to follow is removed
        self.assertNotContains(home_res, 'Who to Follow')
        self.assertNotContains(home_res, '${icons.reply}')

    def test_guest_sees_top_hero_panel_and_no_reply_dollar_bug(self):
        client = self.client_class()
        home_res = client.get("/")
        self.assertEqual(home_res.status_code, 200)
        self.assertFalse(home_res.context["authenticated"])
        # Guest sees the cool top thing
        self.assertContains(home_res, 'class="hero-panel feed-heading"')
        # Who to follow is removed
        self.assertNotContains(home_res, 'Who to Follow')
        # Dollar sign icons bug is gone
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
        # Owner creates an original thought
        orig = Post.objects.create(
            author=self.owner,
            body="Original thought by owner",
            author_name="Layan",
            handle="owner",
            avatar_initial="L",
            avatar_tone="violet",
            published_at=timezone.now(),
        )
        # User creates a reply to owner's post
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
        # User likes owner's post
        PostLike.objects.create(user=self.user, post=orig)

        # Tab thoughts for owner
        thoughts_res = client.get("/api/profiles/owner/posts/?tab=thoughts")
        self.assertEqual(thoughts_res.status_code, 200)
        thoughts_data = thoughts_res.json()
        self.assertTrue(any(p["id"] == orig.id for p in thoughts_data["posts"]))

        # Tab replies for user
        replies_res = client.get("/api/profiles/tester/posts/?tab=replies")
        self.assertEqual(replies_res.status_code, 200)
        replies_data = replies_res.json()
        self.assertEqual(len(replies_data["posts"]), 1)
        self.assertEqual(replies_data["posts"][0]["id"], reply.id)

        # Tab likes for user
        likes_res = client.get("/api/profiles/tester/posts/?tab=likes")
        self.assertEqual(likes_res.status_code, 200)
        likes_data = likes_res.json()
        self.assertEqual(len(likes_data["posts"]), 1)
        self.assertEqual(likes_data["posts"][0]["id"], orig.id)

    def test_update_profile_and_syncs_posts(self):
        client = self.client_class()
        client.force_login(self.user)
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
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["profile"]["display_name"], "Alex ✦")
        self.assertEqual(data["profile"]["avatar_tone"], "gold")

        # Verify profile model updated
        user_profile = self.user.profile
        user_profile.refresh_from_db()
        self.assertEqual(user_profile.display_name, "Alex ✦")
        self.assertEqual(user_profile.bio, "Writer & thinker exploring quiet spaces.")
        self.assertEqual(user_profile.avatar_tone, "gold")

        # Verify posts by tester have been synced
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




TINY_AVATAR = (
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
    "AAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


class SignupWizardApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="taken", password="taken-pass-123")
        Profile.objects.create(user=self.user, display_name="Taken", handle="taken", avatar_initial="T")
        response = self.client.get("/")
        self.csrf = response.cookies["csrftoken"].value
        self.headers = {"HTTP_X_CSRFTOKEN": self.csrf, "HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}

    def json_post(self, url, payload):
        return self.client.post(url, data=json.dumps(payload), content_type="application/json", **self.headers)

    def test_check_handle_reports_availability(self):
        res = self.client.get("/api/auth/check_handle/?handle=taken")
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.json()["available"])

        res = self.client.get("/api/auth/check_handle/?handle=@BrandNew")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["available"])
        self.assertEqual(res.json()["handle"], "brandnew")

        res = self.client.get("/api/auth/check_handle/?handle=bad%20name!")
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.json()["available"])

    def test_registration_accepts_bio_tone_and_cropped_photo(self):
        res = self.json_post(
            "/api/auth/register/",
            {
                "display_name": "Wizard User",
                "handle": "wizard_user",
                "password": "wizardpass123",
                "bio": "I signed up step by step.",
                "avatar_tone": "gold",
                "avatar_image": TINY_AVATAR,
            },
        )
        self.assertEqual(res.status_code, 201)
        profile = Profile.objects.get(handle="wizard_user")
        self.assertEqual(profile.bio, "I signed up step by step.")
        self.assertEqual(profile.avatar_tone, "gold")
        self.assertEqual(profile.avatar_image, TINY_AVATAR)
        data = res.json()["profile"]
        self.assertEqual(data["avatar_image"], TINY_AVATAR)
        self.assertEqual(data["bio"], "I signed up step by step.")

    def test_registration_rejects_bad_or_huge_photos(self):
        res = self.json_post(
            "/api/auth/register/",
            {"display_name": "Bad Photo", "handle": "badphoto", "password": "wizardpass123",
             "avatar_image": "data:image/gif;base64,AAAA"},
        )
        self.assertEqual(res.status_code, 400)

        huge = "data:image/jpeg;base64," + "A" * 700_000
        res = self.json_post(
            "/api/auth/register/",
            {"display_name": "Huge Photo", "handle": "hugephoto", "password": "wizardpass123",
             "avatar_image": huge},
        )
        self.assertEqual(res.status_code, 400)
        self.assertFalse(User.objects.filter(username="hugephoto").exists())

    def test_update_profile_sets_and_removes_photo_and_syncs_posts(self):
        post = Post.objects.create(
            author=self.user, author_name="Taken", handle="taken",
            avatar_initial="T", avatar_tone="violet", body="Hello.",
            published_at=timezone.now(),
        )
        self.client.force_login(self.user)

        res = self.client.post(
            "/api/auth/update_profile/",
            data=json.dumps({"avatar_image": TINY_AVATAR}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["profile"]["avatar_image"], TINY_AVATAR)
        post.refresh_from_db()
        self.assertEqual(post.avatar_image, TINY_AVATAR)

        res = self.client.post(
            "/api/auth/update_profile/",
            data=json.dumps({"avatar_image": ""}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["profile"]["avatar_image"], "")
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.avatar_image, "")

    def test_signup_wizard_markup_is_rendered(self):
        res = self.client.get("/")
        self.assertContains(res, 'id="registerWizard"')
        self.assertContains(res, 'id="regCropStage"')
        self.assertContains(res, 'id="regCropZoom"')
        self.assertContains(res, 'data-reg-panel="1"')
        self.assertContains(res, 'data-reg-panel="3"')

        profile_res = self.client.get("/u/taken/")
        self.assertContains(profile_res, 'id="registerWizard"')
        self.assertContains(profile_res, 'id="regCropStage"')
