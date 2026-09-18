import json
import re

from django.contrib.auth import authenticate, get_user_model, login, logout
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods, require_POST

from .models import Bookmark, Follow, Post, PostLike, PostRepost, Profile, Topic

User = get_user_model()


def arabic_number(value):
    return str(value).translate(str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩"))


def current_user(request):
    return request.user if request.user.is_authenticated else None


def auth_required_response():
    return JsonResponse(
        {"error": "أنشئ حسابًا أو سجّل الدخول أولًا للمتابعة.", "requires_auth": True},
        status=401,
    )


def profile_for(user):
    return Profile.objects.get_or_create(
        user=user,
        defaults={"display_name": user.username, "handle": user.username, "avatar_initial": user.username[:1] or "أ", "avatar_tone": "lime"},
    )[0]


def serialize_post(post, actor=None):
    author_profile = None
    if post.author_id:
        author_profile = Profile.objects.filter(user_id=post.author_id).first()
    author_name = author_profile.display_name if author_profile else post.author_name
    handle = author_profile.handle if author_profile else post.handle
    initial = author_profile.avatar_initial if author_profile else post.avatar_initial
    tone = author_profile.avatar_tone if author_profile else post.avatar_tone
    verified = author_profile.verified if author_profile else post.verified

    likes = post.likes + PostLike.objects.filter(post=post).count()
    reposts = post.reposts + PostRepost.objects.filter(post=post).count()
    replies = post.replies + post.replies_to.count()
    actor_id = getattr(actor, "id", None)
    is_liked = bool(actor_id and PostLike.objects.filter(post=post, user_id=actor_id).exists())
    is_reposted = bool(actor_id and PostRepost.objects.filter(post=post, user_id=actor_id).exists())
    is_bookmarked = bool(actor_id and Bookmark.objects.filter(post=post, user_id=actor_id).exists())
    following = bool(
        actor_id
        and post.author_id
        and (post.author_id == actor_id or Follow.objects.filter(follower_id=actor_id, following_id=post.author_id).exists())
    )
    return {
        "id": post.id,
        "author_name": author_name,
        "handle": handle,
        "avatar_initial": initial,
        "avatar_tone": tone,
        "body": post.body,
        "tags": post.tags or [],
        "published_label": post.published_label,
        "verified": verified,
        "following": following,
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
        "handle": profile.handle,
        "initial": profile.avatar_initial,
        "tone": profile.avatar_tone,
        "verified": profile.verified,
        "following": following,
    }


def topic_payload(topic):
    return {
        "rank": arabic_number(topic.rank).zfill(2),
        "category": topic.category,
        "name": topic.name,
        "meta": f"{topic.posts.count()} منشور",
    }


def home(request):
    actor = current_user(request)
    posts = [serialize_post(post, actor) for post in Post.objects.select_related("author", "topic").all()[:20]]
    profiles = Profile.objects.exclude(user=actor) if actor else Profile.objects.all()
    suggestions = [serialize_profile(profile, actor) for profile in profiles.order_by("-created_at")[:3]]
    topics = [topic_payload(topic) for topic in Topic.objects.all()[:5]]
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
            "suggestions": suggestions,
            "viewer": viewer,
            "viewer_stats": viewer_stats,
            "authenticated": bool(actor),
            "csrf_token_value": get_token(request),
            "active_view": "home",
        },
    )


@csrf_protect
@require_http_methods(["GET", "POST"])
def posts_api(request):
    actor = current_user(request)

    if request.method == "GET":
        query = request.GET.get("q", "").strip()
        posts = Post.objects.select_related("author", "topic").all()
        if query:
            needle = query.casefold()
            candidates = posts[:100]
            posts = [
                post
                for post in candidates
                if needle
                in " ".join(
                    [
                        post.body,
                        post.author_name,
                        post.handle,
                        post.topic.name if post.topic else "",
                        post.topic.category if post.topic else "",
                        " ".join(post.tags or []),
                    ]
                ).casefold()
            ]
        else:
            posts = posts[:30]
        return JsonResponse({"posts": [serialize_post(post, actor) for post in posts[:30]]})

    if actor is None:
        return auth_required_response()

    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "تعذّر فهم المنشور."}, status=400)

    body = str(payload.get("body", "")).strip()
    if not body:
        return JsonResponse({"error": "اكتب شيئًا أولًا."}, status=400)
    if len(body) > 500:
        return JsonResponse({"error": "المنشور أطول من المساحة المتاحة."}, status=400)

    profile = profile_for(actor)
    tags = payload.get("tags", [])
    if not isinstance(tags, list):
        tags = []
    tags = [str(tag).strip()[:30] for tag in tags if str(tag).strip()][:4]
    post = Post.objects.create(
        author=actor,
        author_name=profile.display_name,
        handle=profile.handle,
        avatar_initial=profile.avatar_initial,
        avatar_tone=profile.avatar_tone,
        body=body,
        tags=tags,
        published_label="الآن",
        published_at=timezone.now(),
        verified=profile.verified,
    )
    return JsonResponse({"post": serialize_post(post, actor)}, status=201)


@csrf_protect
@require_POST
def post_action_api(request, post_id, action):
    actor = current_user(request)
    if actor is None:
        return auth_required_response()
    post = get_object_or_404(Post, pk=post_id)

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
    if action == "reply":
        try:
            payload = json.loads(request.body or "{}")
        except json.JSONDecodeError:
            payload = {}
        body = str(payload.get("body", "")).strip()
        if not body or len(body) > 500:
            return JsonResponse({"error": "اكتب ردًا قصيرًا أولًا."}, status=400)
        profile = profile_for(actor)
        reply = Post.objects.create(
            author=actor,
            author_name=profile.display_name,
            handle=profile.handle,
            avatar_initial=profile.avatar_initial,
            avatar_tone=profile.avatar_tone,
            body=body,
            parent=post,
            published_label="الآن",
            published_at=timezone.now(),
            verified=profile.verified,
        )
        return JsonResponse({"action": action, "reply": serialize_post(reply, actor), "post": serialize_post(post, actor)}, status=201)
    return JsonResponse({"error": "هذا الإجراء غير متاح."}, status=400)


@csrf_protect
@require_POST
def follow_api(request, handle):
    actor = current_user(request)
    if actor is None:
        return auth_required_response()
    target = get_object_or_404(Profile, handle=handle).user
    if target == actor:
        return JsonResponse({"error": "لا يمكنك متابعة نفسك."}, status=400)
    event, created = Follow.objects.get_or_create(follower=actor, following=target)
    if not created:
        event.delete()
    return JsonResponse({"handle": handle, "following": created, "followers": Follow.objects.filter(following=target).count()})


@csrf_protect
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

    if request.method != "POST":
        return JsonResponse({"error": "طريقة الطلب غير متاحة."}, status=405)
    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        payload = {}

    if action == "logout":
        logout(request)
        return JsonResponse({"ok": True})

    if action == "login":
        identifier = str(payload.get("username", "")).strip()
        password = str(payload.get("password", ""))
        user = authenticate(request, username=identifier, password=password)
        if user is None:
            return JsonResponse({"error": "بيانات الدخول غير صحيحة."}, status=400)
        login(request, user)
        return JsonResponse({"ok": True, "profile": serialize_profile(profile_for(user), user)})

    if action == "register":
        display_name = str(payload.get("display_name", "")).strip()[:80]
        handle = str(payload.get("handle", "")).strip().lower()
        password = str(payload.get("password", ""))
        if not display_name or not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{2,39}", handle):
            return JsonResponse({"error": "استخدم اسمًا ومعرّفًا لاتينيًا صالحًا."}, status=400)
        if len(password) < 8:
            return JsonResponse({"error": "كلمة المرور يجب أن تكون ٨ أحرف على الأقل."}, status=400)
        if Profile.objects.filter(handle=handle).exists() or User.objects.filter(username=handle).exists():
            return JsonResponse({"error": "هذا المعرّف مستخدم بالفعل."}, status=409)
        user = User.objects.create_user(username=handle, password=password)
        profile = Profile.objects.create(user=user, display_name=display_name, handle=handle, avatar_initial=display_name[:1] or "أ")
        login(request, user)
        return JsonResponse({"ok": True, "profile": serialize_profile(profile, user)}, status=201)

    return JsonResponse({"error": "الإجراء غير متاح."}, status=404)
