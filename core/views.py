import json
import os
import re

from django.contrib.auth import authenticate, get_user_model, login, logout
from django.db import models, transaction
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .models import Bookmark, Follow, Post, PostLike, PostRepost, Profile, Topic

User = get_user_model()
AVATAR_TONES = ["violet", "lime", "sky", "copper", "rose", "blue", "mint", "gold"]

# Cropped profile photos arrive as data-URLs from the in-browser cropper.
# 600k chars ~= 450KB of binary -- plenty for a 256px square jpeg.
AVATAR_IMAGE_MAX_CHARS = 600_000
AVATAR_IMAGE_PREFIXES = (
    "data:image/jpeg;base64,",
    "data:image/png;base64,",
    "data:image/webp;base64,",
)


def validate_avatar_image(value):
    # Returns a cleaned avatar data-URL, or raises ValueError.
    if value is None:
        return ""
    cleaned = str(value).strip()
    if not cleaned:
        return ""
    if len(cleaned) > AVATAR_IMAGE_MAX_CHARS:
        raise ValueError("Profile photo is too large. Please use a smaller image.")
    if not cleaned.startswith(AVATAR_IMAGE_PREFIXES):
        raise ValueError("Profile photo must be a cropped JPEG, PNG, or WebP image.")
    payload = cleaned.split(",", 1)[1] if "," in cleaned else ""
    if not payload or len(payload) < 50:
        raise ValueError("Profile photo looks empty. Please crop it again.")
    import base64

    try:
        base64.b64decode(payload, validate=True)
    except Exception:
        raise ValueError("Profile photo is corrupted. Please upload it again.")
    return cleaned


def arabic_number(value):
    return str(value)


def current_user(request):
    return request.user if request.user.is_authenticated else None


def auth_required_response():
    return JsonResponse(
        {"error": "Please sign in or create an account to continue.", "requires_auth": True},
        status=401,
    )


def profile_for(user):
    tone = AVATAR_TONES[len(user.username) % len(AVATAR_TONES)]
    initial = (user.username[:1] or "A").upper()
    return Profile.objects.get_or_create(
        user=user,
        defaults={"display_name": user.username, "handle": user.username, "avatar_initial": initial, "avatar_tone": tone},
    )[0]


def get_annotated_posts(queryset, actor=None):
    """
    Optimizes social feed queries down to a single SQL query with database-level
    counts and viewer relation checks.
    """
    actor_id = getattr(actor, "id", None)
    qs = queryset.select_related("author__profile", "topic").annotate(
        annotated_likes=models.Count("like_events", distinct=True),
        annotated_reposts=models.Count("repost_events", distinct=True),
        annotated_replies=models.Count("replies_to", distinct=True),
    )
    if actor_id:
        qs = qs.annotate(
            annotated_is_liked=models.Exists(PostLike.objects.filter(post=models.OuterRef("pk"), user_id=actor_id)),
            annotated_is_reposted=models.Exists(PostRepost.objects.filter(post=models.OuterRef("pk"), user_id=actor_id)),
            annotated_is_bookmarked=models.Exists(Bookmark.objects.filter(post=models.OuterRef("pk"), user_id=actor_id)),
            annotated_following=models.Exists(
                Follow.objects.filter(follower_id=actor_id, following_id=models.OuterRef("author_id"))
            ),
        )
    return qs


def serialize_post(post, actor=None):
    author_profile = None
    if hasattr(post, "author") and post.author and hasattr(post.author, "profile"):
        author_profile = post.author.profile
    elif post.author_id:
        author_profile = Profile.objects.filter(user_id=post.author_id).first()

    author_name = author_profile.display_name if author_profile else post.author_name
    handle = author_profile.handle if author_profile else post.handle
    initial = author_profile.avatar_initial if author_profile else post.avatar_initial
    tone = author_profile.avatar_tone if author_profile else post.avatar_tone
    avatar_image = author_profile.avatar_image if author_profile else (post.avatar_image or "")
    verified = author_profile.verified if author_profile else post.verified

    actor_id = getattr(actor, "id", None)

    if hasattr(post, "annotated_likes"):
        likes = post.likes + post.annotated_likes
    else:
        likes = post.likes + PostLike.objects.filter(post=post).count()

    if hasattr(post, "annotated_reposts"):
        reposts = post.reposts + post.annotated_reposts
    else:
        reposts = post.reposts + PostRepost.objects.filter(post=post).count()

    if hasattr(post, "annotated_replies"):
        replies = post.replies + post.annotated_replies
    else:
        replies = post.replies + post.replies_to.count()

    if hasattr(post, "annotated_is_liked"):
        is_liked = bool(post.annotated_is_liked)
    else:
        is_liked = bool(actor_id and PostLike.objects.filter(post=post, user_id=actor_id).exists())

    if hasattr(post, "annotated_is_reposted"):
        is_reposted = bool(post.annotated_is_reposted)
    else:
        is_reposted = bool(actor_id and PostRepost.objects.filter(post=post, user_id=actor_id).exists())

    if hasattr(post, "annotated_is_bookmarked"):
        is_bookmarked = bool(post.annotated_is_bookmarked)
    else:
        is_bookmarked = bool(actor_id and Bookmark.objects.filter(post=post, user_id=actor_id).exists())

    if hasattr(post, "annotated_following"):
        following = bool(actor_id and (post.author_id == actor_id or post.annotated_following))
    else:
        following = bool(
            actor_id
            and post.author_id
            and (post.author_id == actor_id or Follow.objects.filter(follower_id=actor_id, following_id=post.author_id).exists())
        )

    is_owner = bool(actor_id and post.author_id == actor_id)

    return {
        "id": post.id,
        "author_name": author_name,
        "handle": handle,
        "avatar_initial": initial,
        "avatar_tone": tone,
        "avatar_image": avatar_image or "",
        "body": post.body,
        "tags": post.tags or [],
        "published_label": post.published_label,
        "verified": verified,
        "following": following,
        "is_owner": is_owner,
        "likes": likes,
        "replies": replies,
        "reposts": reposts,
        "is_liked": is_liked,
        "is_reposted": is_reposted,
        "is_bookmarked": is_bookmarked,
    }


def serialize_profile(profile, actor=None):
    following = bool(actor and Follow.objects.filter(follower=actor, following=profile.user).exists())
    return {
        "name": profile.display_name,
        "display_name": profile.display_name,
        "handle": profile.handle,
        "initial": profile.avatar_initial,
        "avatar_initial": profile.avatar_initial,
        "tone": profile.avatar_tone,
        "avatar_tone": profile.avatar_tone,
        "avatar_image": profile.avatar_image or "",
        "bio": profile.bio,
        "verified": profile.verified,
        "following": following,
    }


def topic_payload(topic):
    count = getattr(topic, "post_count", None)
    if count is None:
        count = topic.posts.count()
    return {
        "rank": str(topic.rank).zfill(2),
        "category": topic.category,
        "name": topic.name,
        "meta": f"{count} post" if count == 1 else f"{count} posts",
    }


@ensure_csrf_cookie
@require_GET
def csrf_api(request):
    return JsonResponse({"ok": True})


@require_GET
def health_api(request):
    """Health check endpoint verifying application & database connectivity."""
    try:
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        db_vendor = connection.vendor
        is_supabase = db_vendor == "postgresql"
        return JsonResponse({
            "status": "healthy",
            "database": db_vendor,
            "supabase_configured": bool(os.getenv("DATABASE_URL")),
            "supabase_connected": is_supabase,
            "project_ref": "ipwhnpfhevdaiogjuurq",
            "timestamp": timezone.now().isoformat(),
        })
    except Exception as exc:
        return JsonResponse({"status": "unhealthy", "error": str(exc)}, status=503)


def home(request):
    actor = current_user(request)
    posts = [serialize_post(post, actor) for post in get_annotated_posts(Post.objects.all(), actor)[:20]]
    topics = [
        topic_payload(topic)
        for topic in Topic.objects.annotate(post_count=models.Count("posts")).order_by("-post_count", "rank")[:5]
    ]
    viewer = profile_for(actor) if actor else None
    viewer_stats = {
        "posts": Post.objects.filter(author=actor, parent__isnull=True).count() if actor else 0,
        "followers": Follow.objects.filter(following=actor).count() if actor else 0,
        "following": Follow.objects.filter(follower=actor).count() if actor else 0,
    }
    return render(
        request,
        "core/home.html",
        {
            "posts": posts,
            "topics": topics,
            "viewer": viewer,
            "viewer_stats": viewer_stats,
            "authenticated": bool(actor),
            "csrf_token_value": get_token(request),
            "active_view": "home",
            "avatar_tones": AVATAR_TONES,
        },
    )


def profile_view(request, handle):
    actor = current_user(request)
    clean_handle = handle.strip().lstrip("@").lower()
    target_profile = Profile.objects.filter(handle__iexact=clean_handle).first()

    if not target_profile:
        target_user = User.objects.filter(username__iexact=clean_handle).first()
        if target_user:
            target_profile = profile_for(target_user)
        else:
            return render(
                request,
                "core/profile_not_found.html",
                {
                    "handle": clean_handle,
                    "viewer": profile_for(actor) if actor else None,
                    "authenticated": bool(actor),
                    "csrf_token_value": get_token(request),
                    "avatar_tones": AVATAR_TONES,
                },
                status=404,
            )

    target_user = target_profile.user
    is_owner = bool(actor and actor == target_user)
    is_following = bool(actor and Follow.objects.filter(follower=actor, following=target_user).exists())

    stats = {
        "posts": Post.objects.filter(author=target_user, parent__isnull=True).count(),
        "replies": Post.objects.filter(author=target_user, parent__isnull=False).count(),
        "likes": PostLike.objects.filter(user=target_user).count(),
        "followers": Follow.objects.filter(following=target_user).count(),
        "following": Follow.objects.filter(follower=target_user).count(),
    }

    tab = request.GET.get("tab", "thoughts").lower()
    if tab == "replies":
        qs = Post.objects.filter(author=target_user, parent__isnull=False)
    elif tab == "likes":
        qs = Post.objects.filter(like_events__user=target_user)
    else:
        tab = "thoughts"
        qs = Post.objects.filter(author=target_user, parent__isnull=True)

    posts = [serialize_post(post, actor) for post in get_annotated_posts(qs, actor)[:40]]
    topics = [
        topic_payload(topic)
        for topic in Topic.objects.annotate(post_count=models.Count("posts")).order_by("-post_count", "rank")[:5]
    ]
    viewer = profile_for(actor) if actor else None
    viewer_stats = {
        "posts": Post.objects.filter(author=actor, parent__isnull=True).count() if actor else 0,
        "followers": Follow.objects.filter(following=actor).count() if actor else 0,
        "following": Follow.objects.filter(follower=actor).count() if actor else 0,
    }

    return render(
        request,
        "core/profile.html",
        {
            "profile": target_profile,
            "profile_stats": stats,
            "posts": posts,
            "active_tab": tab,
            "is_owner": is_owner,
            "is_following": is_following,
            "topics": topics,
            "viewer": viewer,
            "viewer_stats": viewer_stats,
            "authenticated": bool(actor),
            "csrf_token_value": get_token(request),
            "avatar_tones": AVATAR_TONES,
            "active_view": "profile",
        },
    )


@require_GET
def profile_posts_api(request, handle):
    actor = current_user(request)
    clean_handle = handle.strip().lstrip("@").lower()
    target_profile = get_object_or_404(Profile, handle__iexact=clean_handle)
    target_user = target_profile.user
    tab = request.GET.get("tab", "thoughts").lower()

    if tab == "replies":
        qs = Post.objects.filter(author=target_user, parent__isnull=False)
    elif tab == "likes":
        qs = Post.objects.filter(like_events__user=target_user)
    else:
        tab = "thoughts"
        qs = Post.objects.filter(author=target_user, parent__isnull=True)

    posts = [serialize_post(post, actor) for post in get_annotated_posts(qs, actor)[:40]]
    return JsonResponse({"posts": posts, "tab": tab, "handle": target_profile.handle})


@csrf_exempt
@require_http_methods(["GET", "POST"])
def posts_api(request):
    actor = current_user(request)

    if request.method == "GET":
        query = request.GET.get("q", "").strip()
        tab = request.GET.get("tab", "").strip()
        posts = get_annotated_posts(Post.objects.all(), actor)

        if tab == "following" and actor:
            posts = posts.filter(author__follower_links__follower=actor)
        elif tab in ("bookmarks", "saved") and actor:
            posts = posts.filter(bookmark_events__user=actor)

        if query:
            needle = query.lstrip("#").strip()
            posts = posts.filter(
                models.Q(body__icontains=needle)
                | models.Q(author_name__icontains=needle)
                | models.Q(handle__icontains=needle)
                | models.Q(topic__name__icontains=needle)
                | models.Q(topic__category__icontains=needle)
            )

        limit = min(max(int(request.GET.get("limit", 30)), 1), 100)
        return JsonResponse({"posts": [serialize_post(post, actor) for post in posts[:limit]]})

    if actor is None:
        return auth_required_response()

    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "Could not understand post data."}, status=400)

    body = str(payload.get("body", "")).strip()
    if not body:
        return JsonResponse({"error": "Please write something first."}, status=400)
    if len(body) > 500:
        return JsonResponse({"error": "Post exceeds 500 characters."}, status=400)

    profile = profile_for(actor)
    tags = payload.get("tags", [])
    if not isinstance(tags, list) or not tags:
        tags = [t.strip() for t in re.findall(r"#([\w\u0600-\u06FF]+)", body)][:4]
    else:
        tags = [str(tag).strip()[:30] for tag in tags if str(tag).strip()][:4]

    with transaction.atomic():
        topic = None
        if tags:
            primary_tag = tags[0]
            topic, _ = Topic.objects.get_or_create(
                name=primary_tag,
                defaults={"category": "Trending", "rank": min(Topic.objects.count() + 1, 99)},
            )

        post = Post.objects.create(
            author=actor,
            author_name=profile.display_name,
            handle=profile.handle,
            avatar_initial=profile.avatar_initial,
            avatar_tone=profile.avatar_tone,
            avatar_image=profile.avatar_image or "",
            body=body,
            tags=tags,
            topic=topic,
            published_label="Just now",
            published_at=timezone.now(),
            verified=profile.verified,
        )
    return JsonResponse({"post": serialize_post(post, actor)}, status=201)


@csrf_exempt
@require_POST
def post_action_api(request, post_id, action):
    actor = current_user(request)
    if actor is None:
        return auth_required_response()
    post = get_object_or_404(Post, pk=post_id)

    with transaction.atomic():
        if action == "like":
            event, created = PostLike.objects.get_or_create(user=actor, post=post)
            if not created:
                event.delete()
            return JsonResponse({"action": action, "active": created, "post": serialize_post(post, actor)})

        if action == "repost":
            event, created = PostRepost.objects.get_or_create(user=actor, post=post)
            if not created:
                event.delete()
            return JsonResponse({"action": action, "active": created, "post": serialize_post(post, actor)})

        if action == "bookmark":
            event, created = Bookmark.objects.get_or_create(user=actor, post=post)
            if not created:
                event.delete()
            return JsonResponse({"action": action, "active": created, "post": serialize_post(post, actor)})

        if action == "delete":
            if post.author != actor and not actor.is_staff:
                return JsonResponse({"error": "You are not authorized to delete this post."}, status=403)
            post_id_val = post.id
            post.delete()
            return JsonResponse({"action": "delete", "deleted": True, "id": post_id_val})

        if action == "reply":
            try:
                payload = json.loads(request.body or "{}")
            except json.JSONDecodeError:
                payload = {}
            body = str(payload.get("body", "")).strip()
            if not body or len(body) > 500:
                return JsonResponse({"error": "Write a short reply first."}, status=400)
            profile = profile_for(actor)
            reply = Post.objects.create(
                author=actor,
                author_name=profile.display_name,
                handle=profile.handle,
                avatar_initial=profile.avatar_initial,
                avatar_tone=profile.avatar_tone,
                avatar_image=profile.avatar_image or "",
                body=body,
                parent=post,
                published_label="Just now",
                published_at=timezone.now(),
                verified=profile.verified,
            )
            return JsonResponse({"action": action, "reply": serialize_post(reply, actor), "post": serialize_post(post, actor)}, status=201)

    return JsonResponse({"error": "This action is not available."}, status=400)


@csrf_exempt
@require_POST
def follow_api(request, handle):
    actor = current_user(request)
    if actor is None:
        return auth_required_response()
    target = get_object_or_404(Profile, handle=handle).user
    if target == actor:
        return JsonResponse({"error": "You cannot follow yourself."}, status=400)

    with transaction.atomic():
        event, created = Follow.objects.get_or_create(follower=actor, following=target)
        if not created:
            event.delete()
    return JsonResponse({"handle": handle, "following": created, "followers": Follow.objects.filter(following=target).count()})


@csrf_exempt
@require_http_methods(["GET", "POST"])
def auth_api(request, action):
    if action == "me":
        actor = current_user(request)
        return JsonResponse(
            {
                "authenticated": bool(actor),
                "profile": serialize_profile(profile_for(actor), actor) if actor else None,
            }
        )

    if action == "check_handle":
        # Live username-availability check used by step 1 of the signup wizard.
        handle = str(request.GET.get("handle", "")).strip().lower().lstrip("@")
        if not handle:
            return JsonResponse({"available": False, "handle": handle, "error": "Enter a username first."})
        if not re.fullmatch(r"[a-z0-9_.-]{1,30}", handle):
            return JsonResponse({"available": False, "handle": handle, "error": "Letters, numbers, _, -, . only."})
        taken = Profile.objects.filter(handle__iexact=handle).exists() or User.objects.filter(
            username__iexact=handle
        ).exists()
        return JsonResponse({"available": not taken, "handle": handle})

    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed."}, status=405)

    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        payload = {}

    if action == "logout":
        logout(request)
        return JsonResponse({"ok": True})

    if action == "login":
        identifier = str(payload.get("username", "")).strip().lower().lstrip("@")
        password = str(payload.get("password", ""))
        if not identifier or not password:
            return JsonResponse({"error": "Please enter your username and password."}, status=400)
        user = authenticate(request, username=identifier, password=password)
        if user is None:
            return JsonResponse({"error": "Invalid username or password."}, status=400)
        user.backend = "django.contrib.auth.backends.ModelBackend"
        login(request, user)
        request.session.save()
        return JsonResponse({
            "ok": True,
            "token": request.session.session_key,
            "profile": serialize_profile(profile_for(user), user),
        })

    if action == "register":
        raw_display_name = str(payload.get("display_name", "")).strip()
        handle = str(payload.get("handle") or payload.get("username") or "").strip().lower().lstrip("@")
        password = str(payload.get("password", ""))
        bio = str(payload.get("bio", "")).strip()[:160]
        requested_tone = str(payload.get("avatar_tone", "")).strip()

        if not handle or not re.fullmatch(r"[a-z0-9_.-]{1,30}", handle):
            return JsonResponse({"error": "Username must be between 1 and 30 characters (letters, numbers, _, -, .)."}, status=400)

        display_name = raw_display_name if raw_display_name else handle
        if len(display_name) > 50:
            return JsonResponse({"error": "Display Name cannot exceed 50 characters."}, status=400)

        if len(password) < 8:
            return JsonResponse({"error": "Password must be at least 8 characters."}, status=400)

        try:
            avatar_image = validate_avatar_image(payload.get("avatar_image", ""))
        except ValueError as exc:
            return JsonResponse({"error": str(exc)}, status=400)

        if Profile.objects.filter(handle__iexact=handle).exists() or User.objects.filter(username__iexact=handle).exists():
            return JsonResponse({"error": "This username is already taken. Please choose another."}, status=409)

        tone = requested_tone if requested_tone in AVATAR_TONES else AVATAR_TONES[len(handle) % len(AVATAR_TONES)]
        initial = (display_name[:1] or handle[:1] or "A").upper()
        with transaction.atomic():
            user = User.objects.create_user(username=handle, password=password)
            profile = Profile.objects.create(
                user=user,
                display_name=display_name,
                handle=handle,
                avatar_initial=initial,
                avatar_tone=tone,
                avatar_image=avatar_image,
                bio=bio,
            )
        user.backend = "django.contrib.auth.backends.ModelBackend"
        login(request, user)
        request.session.save()
        return JsonResponse({
            "ok": True,
            "token": request.session.session_key,
            "profile": serialize_profile(profile, user),
        }, status=201)

    if action == "update_profile":
        actor = current_user(request)
        if not actor:
            return auth_required_response()
        profile = profile_for(actor)
        bio = str(payload.get("bio", profile.bio)).strip()[:160]
        raw_display_name = str(payload.get("display_name", profile.display_name)).strip()
        avatar_tone = str(payload.get("avatar_tone", profile.avatar_tone)).strip()

        if raw_display_name:
            if len(raw_display_name) > 50:
                return JsonResponse({"error": "Display Name cannot exceed 50 characters."}, status=400)
            profile.display_name = raw_display_name
            profile.avatar_initial = (raw_display_name[:1] or profile.handle[:1] or "A").upper()

        if avatar_tone in AVATAR_TONES:
            profile.avatar_tone = avatar_tone

        if "avatar_image" in payload:
            try:
                profile.avatar_image = validate_avatar_image(payload.get("avatar_image", ""))
            except ValueError as exc:
                return JsonResponse({"error": str(exc)}, status=400)
        elif str(payload.get("avatar_remove", "")).lower() in ("1", "true", "yes"):
            profile.avatar_image = ""

        profile.bio = bio
        profile.save()

        # Keep denormalized author attributes in sync for consistent rendering
        Post.objects.filter(author=actor).update(
            author_name=profile.display_name,
            avatar_tone=profile.avatar_tone,
            avatar_initial=profile.avatar_initial,
            avatar_image=profile.avatar_image or "",
        )

        return JsonResponse({"ok": True, "profile": serialize_profile(profile, actor)})

    return JsonResponse({"error": "Action not found."}, status=404)
