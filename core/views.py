import json
import math
import os
import re
from functools import wraps

from django.conf import settings as django_settings
from django.core.cache import cache
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.db import models, transaction
from django.db.models import Count, Exists, OuterRef, Q
from django.http import HttpResponse, JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import constant_time_compare
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from . import ai, media
from .models import Bookmark, Follow, Post, PostLike, PostRepost, Profile, Topic

User = get_user_model()
AVATAR_TONES = ["violet", "lime", "sky", "copper", "rose", "blue", "mint", "gold"]
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")
MAX_POST_LENGTH = 500


# --------------------------------------------------------------------------- #
# Request helpers
# --------------------------------------------------------------------------- #

def current_user(request):
    return request.user if request.user.is_authenticated else None


def auth_required_response():
    return JsonResponse(
        {"error": "Please sign in or create an account to continue.", "requires_auth": True},
        status=401,
    )


def parse_int(value, default, *, low=None, high=None):
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        parsed = default
    if low is not None:
        parsed = max(low, parsed)
    if high is not None:
        parsed = min(high, parsed)
    return parsed


def bearer_token(request):
    token = (
        request.headers.get("X-Session-Token")
        or request.META.get("HTTP_X_SESSION_TOKEN")
        or ""
    )
    if not token and "Authorization" in request.headers:
        auth = request.headers["Authorization"].strip()
        if auth.startswith("Bearer "):
            token = auth[7:].strip()
    if not token and request.method in SAFE_METHODS:
        token = request.GET.get("auth_token", "").strip()
    return token


def csrf_token_ok(request) -> bool:
    """Manual CSRF check for token-less, cookie-authenticated mutations."""
    header = request.META.get("HTTP_X_CSRFTOKEN") or request.POST.get("csrfmiddlewaretoken") or ""
    if not header:
        return False
    cookie = request.COOKIES.get(django_settings.CSRF_COOKIE_NAME, "")
    if cookie and constant_time_compare(str(header), str(cookie)):
        return True
    # Fall back to Django's own comparison (handles masked/unmasked variants).
    try:
        from django.middleware.csrf import _does_token_match, _get_secret  # type: ignore
        if cookie:
            return bool(_does_token_match(header, _get_secret(cookie)))
    except Exception:
        return False
    return False


def csrf_violation(request) -> bool:
    """
    True only when a state-changing request could actually abuse a cookie
    session: it is authenticated by cookie (no bearer token) and carries no
    valid CSRF token. Anonymous requests cannot abuse anything, so they fall
    through to the normal 401 / validation responses.
    """
    if request.method in SAFE_METHODS:
        return False
    if bearer_token(request) or csrf_token_ok(request):
        return False
    return current_user(request) is not None


def api_endpoint(view=None, *, csrf=True):
    """
    Wraps an API view with:
      * CSRF exemption (needed so cross-origin preview iframes work),
      * a real CSRF check for cookie-authenticated mutations,
      * ``ImageRejected`` translated into a clean JSON 400.

    Bearer/``X-Session-Token`` authenticated requests cannot be forged by a
    third-party site, so they bypass the cookie check. Endpoints that only
    validate credentials (``login``/``register``) opt out entirely.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(request, *args, **kwargs):
            if csrf and csrf_violation(request):
                return JsonResponse(
                    {
                        "error": "Security check failed. Reload the page and try again.",
                        "csrf_failed": True,
                    },
                    status=403,
                )
            try:
                return func(request, *args, **kwargs)
            except media.ImageRejected as exc:
                return JsonResponse({"error": str(exc), "image_error": True}, status=400)
        return csrf_exempt(wrapper)

    if view is None:
        return decorator
    return decorator(view)


# --------------------------------------------------------------------------- #
# Serialization
# --------------------------------------------------------------------------- #

def relative_time(moment) -> str:
    if not moment:
        return ""
    now = timezone.now()
    seconds = (now - moment).total_seconds()
    if seconds < 0:
        return "Scheduled"
    if seconds < 45:
        return "Just now"
    if seconds < 90:
        return "1 min"
    if seconds < 3600:
        return f"{int(seconds // 60)} min"
    if seconds < 7200:
        return "1 h"
    if seconds < 86400:
        return f"{int(seconds // 3600)} h"
    if seconds < 172800:
        return "Yesterday"
    if seconds < 604800:
        return f"{int(seconds // 86400)} d"
    label = moment.strftime("%b %d")
    if moment.year != now.year:
        label += f", {moment.year}"
    return label


def avatar_payload(profile=None, post=None) -> dict:
    """Avatar data for templates/JS, with a graceful initial fallback."""
    if profile is not None:
        return {
            "avatar_url": profile.avatar_url,
            "avatar_initial": profile.avatar_initial or profile.initials,
            "avatar_tone": profile.avatar_tone,
            "has_avatar": profile.has_avatar,
        }
    if post is not None:
        return {
            "avatar_url": "",
            "avatar_initial": post.avatar_initial,
            "avatar_tone": post.avatar_tone,
            "has_avatar": False,
        }
    return {"avatar_url": "", "avatar_initial": "أ", "avatar_tone": "violet", "has_avatar": False}


def profile_for(user):
    """Return (and lazily create) the profile backing an account."""
    tone = AVATAR_TONES[len(user.username) % len(AVATAR_TONES)]
    initial = (user.username[:1] or "A").upper()
    return Profile.objects.get_or_create(
        user=user,
        defaults={"display_name": user.username, "handle": user.username, "avatar_initial": initial, "avatar_tone": tone},
    )[0]


def post_queryset(actor=None, *, include_blobs: bool = False):
    """Annotated, deferred feed queryset — one SQL round-trip, no blob reads."""
    qs = Post.objects.select_related("author__profile", "topic")
    if not include_blobs:
        qs = qs.defer("image_blob", "author__profile__avatar_blob")
    actor_id = getattr(actor, "id", None)
    qs = qs.annotate(
        annotated_likes=Count("like_events", distinct=True),
        annotated_reposts=Count("repost_events", distinct=True),
        annotated_replies=Count("replies_to", distinct=True),
    )
    if actor_id:
        qs = qs.annotate(
            annotated_is_liked=Exists(PostLike.objects.filter(post=OuterRef("pk"), user_id=actor_id)),
            annotated_is_reposted=Exists(PostRepost.objects.filter(post=OuterRef("pk"), user_id=actor_id)),
            annotated_is_bookmarked=Exists(Bookmark.objects.filter(post=OuterRef("pk"), user_id=actor_id)),
            annotated_following=Exists(
                Follow.objects.filter(follower_id=actor_id, following_id=OuterRef("author_id"))
            ),
        )
    return qs


# Backwards-compatible name used across the codebase.
def get_annotated_posts(queryset, actor=None):
    actor_id = getattr(actor, "id", None)
    qs = queryset.select_related("author__profile", "topic").annotate(
        annotated_likes=Count("like_events", distinct=True),
        annotated_reposts=Count("repost_events", distinct=True),
        annotated_replies=Count("replies_to", distinct=True),
    )
    if actor_id:
        qs = qs.annotate(
            annotated_is_liked=Exists(PostLike.objects.filter(post=OuterRef("pk"), user_id=actor_id)),
            annotated_is_reposted=Exists(PostRepost.objects.filter(post=OuterRef("pk"), user_id=actor_id)),
            annotated_is_bookmarked=Exists(Bookmark.objects.filter(post=OuterRef("pk"), user_id=actor_id)),
            annotated_following=Exists(
                Follow.objects.filter(follower_id=actor_id, following_id=OuterRef("author_id"))
            ),
        )
    return qs


def serialize_post(post, actor=None, *, include_preview: bool = False) -> dict:
    author_profile = None
    if post.author_id:
        author_profile = getattr(post.author, "profile", None) if post.author else None
        if author_profile is None and not post.author_id:
            author_profile = None
    if author_profile is None and post.author_id:
        author_profile = Profile.objects.filter(user_id=post.author_id).only(
            "display_name", "handle", "avatar_initial", "avatar_tone", "avatar_version", "avatar_mime", "verified"
        ).first()

    if author_profile is not None:
        author_name = author_profile.display_name
        handle = author_profile.handle
        initial = author_profile.avatar_initial or author_profile.initials
        tone = author_profile.avatar_tone
        verified = author_profile.verified
        avatar_url = author_profile.avatar_url
    else:
        author_name, handle = post.author_name, post.handle
        initial, tone, verified, avatar_url = post.avatar_initial, post.avatar_tone, post.verified, ""

    actor_id = getattr(actor, "id", None)

    likes = post.likes + (post.annotated_likes if hasattr(post, "annotated_likes") else PostLike.objects.filter(post=post).count())
    reposts = post.reposts + (post.annotated_reposts if hasattr(post, "annotated_reposts") else PostRepost.objects.filter(post=post).count())
    replies = post.replies + (post.annotated_replies if hasattr(post, "annotated_replies") else post.replies_to.count())

    def relation(annotation: str, model):
        if hasattr(post, annotation):
            return bool(getattr(post, annotation))
        return bool(actor_id and model.objects.filter(post=post, user_id=actor_id).exists())

    is_liked = relation("annotated_is_liked", PostLike)
    is_reposted = relation("annotated_is_reposted", PostRepost)
    is_bookmarked = relation("annotated_is_bookmarked", Bookmark)

    if hasattr(post, "annotated_following"):
        following = bool(actor_id and (post.author_id == actor_id or post.annotated_following))
    else:
        following = bool(
            actor_id
            and post.author_id
            and (post.author_id == actor_id or Follow.objects.filter(follower_id=actor_id, following_id=post.author_id).exists())
        )

    payload = {
        "id": post.id,
        "author_name": author_name,
        "handle": handle,
        "avatar_initial": initial,
        "avatar_tone": tone,
        "avatar_url": avatar_url,
        "has_avatar": bool(avatar_url),
        "body": post.body,
        "tags": post.tags or [],
        "published_label": relative_time(post.published_at) or post.published_label,
        "published_at": post.published_at.isoformat() if post.published_at else "",
        "edited": bool(post.edited_at),
        "image_url": post.image_url,
        "image_width": post.image_width,
        "image_height": post.image_height,
        "parent_id": post.parent_id,
        "permalink": post.permalink,
        "verified": verified,
        "following": following,
        "is_owner": bool(actor_id and post.author_id == actor_id),
        "likes": likes,
        "replies": replies,
        "reposts": reposts,
        "is_liked": is_liked,
        "is_reposted": is_reposted,
        "is_bookmarked": is_bookmarked,
    }
    if include_preview:
        payload["related"] = [item["permalink"] for item in related_posts_for(post, actor, limit=3)]
    return payload


def serialize_reply_author(post) -> dict:
    return serialize_post(post, None)


def serialize_profile(profile, actor=None, *, include_stats: bool = False) -> dict:
    following = bool(actor and profile.user_id != actor.id and Follow.objects.filter(follower=actor, following=profile.user).exists())
    payload = {
        "name": profile.display_name,
        "display_name": profile.display_name,
        "handle": profile.handle,
        "initial": profile.avatar_initial or profile.initials,
        "avatar_initial": profile.avatar_initial or profile.initials,
        "tone": profile.avatar_tone,
        "avatar_tone": profile.avatar_tone,
        "avatar_url": profile.avatar_url,
        "has_avatar": profile.has_avatar,
        "bio": profile.bio,
        "location": profile.location,
        "website": profile.website,
        "verified": profile.verified,
        "following": following,
        "is_owner": bool(actor and profile.user_id == actor.id),
        "joined": profile.created_at.isoformat() if profile.created_at else "",
        "url": reverse("core:profile", kwargs={"handle": profile.handle}),
    }
    if include_stats:
        payload["stats"] = profile_stats(profile.user)
    return payload


def serialize_person(profile, actor=None, *, reason: str = "", match: float | None = None) -> dict:
    payload = serialize_profile(profile, actor, include_stats=True)
    if reason:
        payload["reason"] = reason
    if match is not None:
        payload["match"] = match
    return payload


def profile_stats(user) -> dict:
    return {
        "posts": Post.objects.filter(author=user, parent__isnull=True).count(),
        "replies": Post.objects.filter(author=user, parent__isnull=False).count(),
        "likes_given": PostLike.objects.filter(user=user).count(),
        "likes_received": PostLike.objects.filter(post__author=user).count(),
        "followers": Follow.objects.filter(following=user).count(),
        "following": Follow.objects.filter(follower=user).count(),
    }


def topic_payload(topic, *, momentum: str = "", score: float | None = None) -> dict:
    count = getattr(topic, "post_count", None)
    if count is None:
        count = topic.posts.count()
    payload = {
        "rank": str(topic.rank).zfill(2),
        "category": topic.category,
        "name": topic.name,
        "count": count,
        "meta": f"{count} post" if count == 1 else f"{count} posts",
    }
    if momentum:
        payload["momentum"] = momentum
    if score is not None:
        payload["score"] = score
    return payload


def related_posts_for(post, actor, limit: int = 3) -> list[dict]:
    candidates = (
        Post.objects.filter(parent__isnull=True)
        .exclude(pk=post.pk)
        .only("id", "body", "handle", "author_name", "likes", "reposts", "published_at")[:120]
    )
    payload = [
        {
            "text": candidate.body,
            "engagement": candidate.likes + candidate.reposts,
            "permalink": candidate.permalink,
            "handle": candidate.handle,
            "author_name": candidate.author_name,
            "id": candidate.id,
            "published_label": relative_time(candidate.published_at),
            "excerpt": (candidate.body[:120] + "…") if len(candidate.body) > 120 else candidate.body,
        }
        for candidate in candidates
    ]
    return ai.related_posts(post.body, payload, limit=limit)


def viewer_affinity(actor) -> dict:
    """Topic weights the viewer engages with — used for recommendations."""
    if not actor:
        return {}
    weights: dict[str, float] = {}
    for topic_name in (
        Post.objects.filter(author=actor).exclude(topic__isnull=True).values_list("topic__name", flat=True)
    ):
        weights[topic_name] = weights.get(topic_name, 0) + 2.0
    for topic_name in (
        Post.objects.filter(like_events__user=actor).exclude(topic__isnull=True).values_list("topic__name", flat=True)
    ):
        weights[topic_name] = weights.get(topic_name, 0) + 1.4
    for topic_name in (
        Post.objects.filter(bookmark_events__user=actor).exclude(topic__isnull=True).values_list("topic__name", flat=True)
    ):
        weights[topic_name] = weights.get(topic_name, 0) + 1.6
    for topic_name in (
        Post.objects.filter(author__follower_links__follower=actor).exclude(topic__isnull=True).values_list("topic__name", flat=True)
    ):
        weights[topic_name] = weights.get(topic_name, 0) + 0.9
    return weights


def feed_topics(limit: int = 5) -> list[dict]:
    """Ranked topics — database topics first, then live keyword momentum."""
    topics = list(Topic.objects.annotate(post_count=Count("posts")))
    ranked = ai.suggest_topics(Post.objects.select_related("topic")[:200], topics, limit=limit)
    payload = [
        {
            "rank": str(index + 1).zfill(2),
            "category": item["category"],
            "name": item["name"],
            "count": item["posts"],
            "momentum": item["momentum"],
            "score": item["score"],
            "sample": item["sample"],
            "meta": item["meta"],
        }
        for index, item in enumerate(ranked)
    ]

    if len(payload) < limit:
        recent = list(Post.objects.order_by("-published_at").values_list("body", flat=True)[:80])
        corpus = " ".join(recent)
        taken = {item["name"].lower() for item in payload}
        for word in ai.keywords(corpus, 20):
            if len(payload) >= limit:
                break
            if word.lower() in taken or len(word) < 4 or word in ai.WEAK_TAGS:
                continue
            count = sum(1 for body in recent if word in body.lower())
            if count < 2:
                continue
            payload.append({
                "rank": str(len(payload) + 1).zfill(2),
                "category": ai.categorise_topic(word, corpus),
                "name": word,
                "count": count,
                "momentum": "rising",
                "score": round(count * 1.5, 2),
                "sample": "",
                "meta": f"{count} mentions",
            })
            taken.add(word.lower())

    for index, item in enumerate(payload):
        item["rank"] = str(index + 1).zfill(2)
    return payload


def people_suggestions(actor, limit: int = 4) -> list[dict]:
    affinity = viewer_affinity(actor)
    following_ids = set()
    if actor:
        following_ids = set(Follow.objects.filter(follower=actor).values_list("following_id", flat=True))
        following_ids.add(actor.id)

    candidate_profiles = (
        Profile.objects.select_related("user")
        .defer("avatar_blob")
        .exclude(user_id__in=following_ids)
        .annotate(
            follower_total=Count("user__follower_links", distinct=True),
            post_total=Count("user__posts", distinct=True),
        )
        .order_by("-post_total", "-follower_total")[:40]
    )

    topic_map: dict[int, set] = {}
    for user_id, topic_name in (
        Post.objects.exclude(topic__isnull=True).values_list("author_id", "topic__name")[:600]
    ):
        if user_id:
            topic_map.setdefault(user_id, set()).add(topic_name)
        if topic_name and not actor:
            affinity[topic_name] = affinity.get(topic_name, 0) + 0.4

    candidates = []
    for profile in candidate_profiles:
        candidates.append({
            "id": profile.user_id,
            "handle": profile.handle,
            "display_name": profile.display_name,
            "avatar_initial": profile.avatar_initial or profile.initials,
            "avatar_tone": profile.avatar_tone,
            "avatar_url": profile.avatar_url,
            "verified": profile.verified,
            "followers": profile.follower_total,
            "posts": profile.post_total,
            "topics": topic_map.get(profile.user_id, set()),
            "profile": profile,
        })

    ranked = ai.suggest_people(actor, candidates, limit=limit, following_ids=following_ids, affinity=affinity)
    output = []
    for item in ranked:
        payload = serialize_person(item["profile"], actor, reason=item.get("reason", ""), match=item.get("match"))
        output.append(payload)
    return output


def default_context(request, *, active_view: str, extra: dict | None = None) -> dict:
    actor = current_user(request)
    viewer = profile_for(actor) if actor else None
    context = {
        "viewer": viewer,
        "authenticated": bool(actor),
        "csrf_token_value": get_token(request),
        "avatar_tones": AVATAR_TONES,
        "active_view": active_view,
        "ai_provider": ai.provider_info(),
        "today": timezone.localdate(),
        "max_post_length": MAX_POST_LENGTH,
    }
    if viewer:
        context["viewer_stats"] = profile_stats(actor)
    else:
        context["viewer_stats"] = {"posts": 0, "followers": 0, "following": 0}
    if extra:
        context.update(extra)
    return context


# --------------------------------------------------------------------------- #
# Small APIs
# --------------------------------------------------------------------------- #

@ensure_csrf_cookie
@require_GET
def csrf_api(request):
    return JsonResponse({"ok": True})


@require_GET
def health_api(request):
    """Health check verifying application + database + AI engine status."""
    try:
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        db_vendor = connection.vendor
        provider = ai.provider_info()
        return JsonResponse({
            "status": "healthy",
            "database": db_vendor,
            "supabase_configured": bool(os.getenv("DATABASE_URL")),
            "supabase_connected": db_vendor == "postgresql",
            "ai": provider,
            "pillow": media.PIL_AVAILABLE,
            "posts": Post.objects.count(),
            "profiles": Profile.objects.count(),
            "timestamp": timezone.now().isoformat(),
        })
    except Exception as exc:
        return JsonResponse({"status": "unhealthy", "error": str(exc)}, status=503)


# --------------------------------------------------------------------------- #
# Pages
# --------------------------------------------------------------------------- #

def home(request):
    actor = current_user(request)
    tab = request.GET.get("tab", "all")
    sort = request.GET.get("sort", "latest")
    posts = feed_queryset(actor, tab=tab, sort=sort)[:20]
    context = default_context(request, active_view="home", extra={
        "posts": [serialize_post(post, actor) for post in posts],
        "topics": feed_topics(5),
        "suggested_people": people_suggestions(actor, 3),
        "active_feed_tab": tab,
        "active_sort": sort,
        "daily_prompt": ai.writing_prompts(None, "en", 1)[0],
    })
    return render(request, "core/home.html", context)


def feed_queryset(actor, *, tab: str = "all", sort: str = "latest", query: str = "", topic: str = "",
                  author=None, parent: str | None = "root"):
    """The single source of truth for feed ordering and filtering."""
    qs = get_annotated_posts(Post.objects.all(), actor)

    if parent == "root":
        qs = qs.filter(parent__isnull=True)
    elif parent == "replies":
        qs = qs.filter(parent__isnull=False)
    elif parent and str(parent).isdigit():
        qs = qs.filter(parent_id=int(parent))

    if tab == "following" and actor:
        qs = qs.filter(author__in=Follow.objects.filter(follower=actor).values("following_id"))
    elif tab in ("bookmarks", "saved") and actor:
        qs = qs.filter(bookmark_events__user=actor)
    elif tab == "likes" and actor:
        qs = qs.filter(like_events__user=actor)
    elif tab == "mine" and actor:
        qs = qs.filter(author=actor)

    if author is not None:
        qs = qs.filter(author=author)
    if topic:
        qs = qs.filter(Q(topic__name__iexact=topic) | Q(tags__icontains=topic))

    if query:
        needle = query.lstrip("#").strip()
        qs = qs.filter(
            Q(body__icontains=needle)
            | Q(author_name__icontains=needle)
            | Q(handle__icontains=needle)
            | Q(topic__name__icontains=needle)
            | Q(topic__category__icontains=needle)
        )

    if sort == "top":
        qs = qs.annotate(engagement=models.F("annotated_likes") + models.F("annotated_reposts") * 2 + models.F("annotated_replies")).order_by("-engagement", "-published_at")
    elif sort == "trending":
        qs = qs.annotate(
            engagement=models.F("annotated_likes") + models.F("annotated_reposts") * 3 + models.F("annotated_replies") * 2
        ).order_by("-engagement", "-published_at")
    else:
        qs = qs.order_by("-published_at", "-id")

    return qs.distinct()


def profile_view(request, handle):
    actor = current_user(request)
    clean_handle = handle.strip().lstrip("@").lower()
    target_profile = Profile.objects.select_related("user").filter(handle__iexact=clean_handle).first()

    if not target_profile:
        target_user = User.objects.filter(username__iexact=clean_handle).first()
        if target_user:
            target_profile = profile_for(target_user)
        else:
            context = default_context(request, active_view="profile", extra={
                "handle": clean_handle,
                "topics": feed_topics(5),
                "suggested_people": people_suggestions(actor, 3),
            })
            return render(request, "core/profile_not_found.html", context, status=404)

    target_user = target_profile.user
    is_owner = bool(actor and actor == target_user)
    is_following = bool(actor and Follow.objects.filter(follower=actor, following=target_user).exists())

    stats = profile_stats(target_user)
    tab = request.GET.get("tab", "thoughts").lower()
    if tab == "replies":
        qs = Post.objects.filter(author=target_user, parent__isnull=False)
    elif tab == "likes":
        qs = Post.objects.filter(like_events__user=target_user)
    elif tab == "media":
        qs = Post.objects.filter(author=target_user, image_version__gt=0)
    else:
        tab = "thoughts"
        qs = Post.objects.filter(author=target_user, parent__isnull=True)

    posts = [serialize_post(post, actor) for post in get_annotated_posts(qs, actor).distinct()[:40]]

    context = default_context(request, active_view="profile", extra={
        "profile": target_profile,
        "profile_stats": stats,
        "posts": posts,
        "active_tab": tab,
        "is_owner": is_owner,
        "is_following": is_following,
        "topics": feed_topics(5),
        "suggested_people": people_suggestions(actor, 3),
    })
    return render(request, "core/profile.html", context)


def post_detail_view(request, post_id):
    actor = current_user(request)
    post = get_object_or_404(get_annotated_posts(Post.objects.all(), actor), pk=post_id)
    replies_qs = get_annotated_posts(Post.objects.filter(parent=post), actor).order_by("published_at")
    parent = None
    if post.parent_id:
        parent = serialize_post(get_object_or_404(get_annotated_posts(Post.objects.all(), actor), pk=post.parent_id), actor)
    context = default_context(request, active_view="post", extra={
        "post": serialize_post(post, actor),
        "post_object": post,
        "replies": [serialize_post(reply, actor) for reply in replies_qs[:60]],
        "parent_post": parent,
        "related": related_posts_for(post, actor, limit=3),
        "topics": feed_topics(5),
        "suggested_people": people_suggestions(actor, 3),
        "thread_meta": {
            "title": f"{post.author_name} on Athar",
            "description": post.body[:150],
        },
    })
    return render(request, "core/post_detail.html", context)


# --------------------------------------------------------------------------- #
# Posts API
# --------------------------------------------------------------------------- #

@api_endpoint
@require_http_methods(["GET", "POST"])
def posts_api(request):
    actor = current_user(request)

    if request.method == "GET":
        tab = request.GET.get("tab", "all").strip() or "all"
        sort = request.GET.get("sort", "latest").strip() or "latest"
        query = request.GET.get("q", "").strip()
        topic = request.GET.get("topic", "").strip()
        parent = request.GET.get("parent", "root")
        limit = parse_int(request.GET.get("limit"), 20, low=1, high=50)
        offset = parse_int(request.GET.get("offset"), 0, low=0, high=5000)

        qs = feed_queryset(actor, tab=tab, sort=sort, query=query, topic=topic, parent=parent)
        total = qs.count()
        page = list(qs[offset:offset + limit])

        ranked = False
        if query and page:
            documents = [{"text": post.body, "post": post} for post in page]
            ordered = ai.rank_documents(query, documents, text_key="text")
            page = [item["post"] for item in ordered]
            ranked = True

        return JsonResponse({
            "posts": [serialize_post(post, actor) for post in page],
            "tab": tab,
            "sort": sort,
            "query": query,
            "topic": topic,
            "total": total,
            "offset": offset,
            "limit": limit,
            "has_more": offset + len(page) < total,
            "next_offset": offset + len(page),
            "ranked": ranked,
        })

    if actor is None:
        return auth_required_response()

    payload, uploaded = read_payload(request)
    body = str(payload.get("body", "")).strip()
    if not body and not uploaded:
        return JsonResponse({"error": "Please write something first."}, status=400)
    if len(body) > MAX_POST_LENGTH:
        return JsonResponse({"error": f"Post exceeds {MAX_POST_LENGTH} characters."}, status=400)

    parent_id = payload.get("parent_id") or payload.get("parent")
    parent = None
    if parent_id:
        parent = Post.objects.filter(pk=parent_id).first()
        if parent is None:
            return JsonResponse({"error": "The thought you are replying to no longer exists."}, status=404)

    profile = profile_for(actor)
    tags = payload.get("tags", [])
    if not isinstance(tags, list) or not tags:
        tags = ai.explicit_tags(body, 4)
    else:
        tags = [str(tag).strip().lstrip("#")[:30] for tag in tags if str(tag).strip()][:4]

    with transaction.atomic():
        topic = None
        if tags:
            primary = tags[0]
            topic, created = Topic.objects.get_or_create(
                name=primary,
                defaults={"category": ai.categorise_topic(primary, body), "rank": min(Topic.objects.count() + 1, 99)},
            )
            if not created and topic.category in ("Trending", ""):
                topic.category = ai.categorise_topic(primary, body)
                topic.save(update_fields=["category"])

        post = Post.objects.create(
            author=actor,
            author_name=profile.display_name,
            handle=profile.handle,
            avatar_initial=profile.avatar_initial or profile.initials,
            avatar_tone=profile.avatar_tone,
            body=body,
            tags=tags,
            topic=topic,
            parent=parent,
            published_label="Just now",
            published_at=timezone.now(),
            verified=profile.verified,
        )

        if uploaded is not None:
            media.store_post_image(post, uploaded[0], uploaded[1])

    return JsonResponse({"post": serialize_post(post, actor), "parent_id": post.parent_id}, status=201)


def read_payload(request) -> tuple[dict, tuple[bytes, str] | None]:
    """Read JSON or multipart payloads, including optional images."""
    uploaded = None
    if request.content_type and request.content_type.startswith("multipart/form-data"):
        payload = {key: request.POST.get(key) for key in request.POST}
        if request.POST.get("tags"):
            payload["tags"] = [tag for tag in re.split(r"[,\s]+", request.POST.get("tags", "")) if tag]
        file_obj = request.FILES.get("image") or request.FILES.get("avatar")
        if file_obj is not None:
            uploaded = media.read_upload(file_obj, max_bytes=media.MAX_POST_IMAGE_BYTES)
        return payload, uploaded

    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    image_data = payload.get("image_data") or payload.get("image")
    avatar_data = payload.get("avatar_data") or payload.get("avatar")
    if isinstance(image_data, str) and image_data.startswith("data:"):
        uploaded = media.decode_data_url(image_data, max_bytes=media.MAX_POST_IMAGE_BYTES)
    elif isinstance(avatar_data, str) and avatar_data.startswith("data:"):
        uploaded = media.decode_data_url(avatar_data, max_bytes=media.MAX_AVATAR_BYTES)
    return payload, uploaded


@api_endpoint
@require_GET
def post_detail_api(request, post_id):
    actor = current_user(request)
    post = get_object_or_404(get_annotated_posts(Post.objects.all(), actor), pk=post_id)
    replies = get_annotated_posts(Post.objects.filter(parent=post), actor).order_by("published_at")[:60]
    parent = None
    if post.parent_id:
        parent_post = get_annotated_posts(Post.objects.all(), actor).filter(pk=post.parent_id).first()
        if parent_post:
            parent = serialize_post(parent_post, actor)
    return JsonResponse({
        "post": serialize_post(post, actor),
        "parent": parent,
        "replies": [serialize_post(reply, actor) for reply in replies],
        "related": related_posts_for(post, actor, limit=3),
    })


@api_endpoint
@require_POST
def post_action_api(request, post_id, action):
    actor = current_user(request)
    if actor is None:
        return auth_required_response()
    post = get_object_or_404(Post, pk=post_id)

    if action == "delete":
        if post.author != actor and not actor.is_staff:
            return JsonResponse({"error": "You are not authorized to delete this post."}, status=403)
        removed_id = post.id
        with transaction.atomic():
            post.delete()
        return JsonResponse({"action": "delete", "deleted": True, "id": removed_id})

    if action == "reply":
        payload, _ = read_payload(request)
        body = str(payload.get("body", "")).strip()
        if not body or len(body) > MAX_POST_LENGTH:
            return JsonResponse({"error": f"Write a short reply first (max {MAX_POST_LENGTH} characters)."}, status=400)
        profile = profile_for(actor)
        tags = ai.explicit_tags(body, 3)
        with transaction.atomic():
            topic = None
            if tags:
                topic, _ = Topic.objects.get_or_create(
                    name=tags[0],
                    defaults={"category": ai.categorise_topic(tags[0], body), "rank": min(Topic.objects.count() + 1, 99)},
                )
            reply = Post.objects.create(
                author=actor,
                author_name=profile.display_name,
                handle=profile.handle,
                avatar_initial=profile.avatar_initial or profile.initials,
                avatar_tone=profile.avatar_tone,
                body=body,
                tags=tags,
                topic=topic,
                parent=post,
                published_label="Just now",
                published_at=timezone.now(),
                verified=profile.verified,
            )
        fresh = get_annotated_posts(Post.objects.filter(pk=post.pk), actor).first()
        return JsonResponse({
            "action": action,
            "reply": serialize_post(reply, actor),
            "post": serialize_post(fresh or post, actor),
        }, status=201)

    if action == "edit":
        if post.author != actor and not actor.is_staff:
            return JsonResponse({"error": "You are not authorized to edit this post."}, status=403)
        payload, uploaded = read_payload(request)
        body = str(payload.get("body", post.body)).strip()
        if not body:
            return JsonResponse({"error": "A thought cannot be empty."}, status=400)
        if len(body) > MAX_POST_LENGTH:
            return JsonResponse({"error": f"Post exceeds {MAX_POST_LENGTH} characters."}, status=400)
        post.body = body
        post.edited_at = timezone.now()
        tags = ai.explicit_tags(body, 3)
        post.tags = tags
        if tags:
            topic, created = Topic.objects.get_or_create(
                name=tags[0],
                defaults={"category": ai.categorise_topic(tags[0], body), "rank": min(Topic.objects.count() + 1, 99)},
            )
            post.topic = topic
        post.save(update_fields=["body", "tags", "topic", "edited_at"])
        if uploaded is not None:
            media.store_post_image(post, uploaded[0], uploaded[1])
        if payload.get("remove_image") in (True, "true", "1", 1):
            media.clear_post_image(post)
        return JsonResponse({"action": "edit", "post": serialize_post(post, actor)})

    if action in ("like", "repost", "bookmark"):
        model = {"like": PostLike, "repost": PostRepost, "bookmark": Bookmark}[action]
        with transaction.atomic():
            event, created = model.objects.get_or_create(user=actor, post=post)
            if not created:
                event.delete()
        fresh = get_annotated_posts(Post.objects.filter(pk=post.pk), actor).first()
        return JsonResponse({"action": action, "active": created, "post": serialize_post(fresh or post, actor)})

    return JsonResponse({"error": "This action is not available."}, status=404)


@api_endpoint
@require_POST
def follow_api(request, handle):
    actor = current_user(request)
    if actor is None:
        return auth_required_response()
    target_profile = get_object_or_404(Profile.objects.select_related("user"), handle__iexact=handle.strip().lstrip("@"))
    target = target_profile.user
    if target == actor:
        return JsonResponse({"error": "You cannot follow yourself."}, status=400)

    with transaction.atomic():
        event, created = Follow.objects.get_or_create(follower=actor, following=target)
        if not created:
            event.delete()
    return JsonResponse({
        "handle": target_profile.handle,
        "following": created,
        "followers": Follow.objects.filter(following=target).count(),
        "bio": target_profile.bio,
    })


@api_endpoint
@require_GET
def followers_api(request, handle, mode="followers"):
    actor = current_user(request)
    profile = get_object_or_404(Profile.objects.select_related("user"), handle__iexact=handle.strip().lstrip("@"))
    if mode not in ("followers", "following"):
        mode = request.GET.get("mode", "followers")
    limit = parse_int(request.GET.get("limit"), 50, low=1, high=200)

    if mode == "following":
        user_ids = Follow.objects.filter(follower=profile.user).values_list("following_id", flat=True)
    else:
        user_ids = Follow.objects.filter(following=profile.user).values_list("follower_id", flat=True)

    profiles = Profile.objects.select_related("user").defer("avatar_blob").filter(user_id__in=list(user_ids)[:limit])
    people = [serialize_person(item, actor) for item in profiles]
    people.sort(key=lambda item: (not item["following"], -item["stats"]["followers"], item["display_name"].lower()))
    return JsonResponse({
        "handle": profile.handle,
        "mode": "following" if mode == "following" else "followers",
        "people": people,
        "count": len(people),
    })


@api_endpoint
@require_GET
def suggestions_api(request):
    actor = current_user(request)
    limit = parse_int(request.GET.get("limit"), 4, low=1, high=20)
    return JsonResponse({"people": people_suggestions(actor, limit), "affinity": list(viewer_affinity(actor).keys())[:5]})


@api_endpoint
@require_GET
def topics_api(request):
    limit = parse_int(request.GET.get("limit"), 12, low=1, high=40)
    return JsonResponse({"topics": feed_topics(limit)})


@api_endpoint
@require_GET
def search_api(request):
    actor = current_user(request)
    query = request.GET.get("q", "").strip()
    limit = parse_int(request.GET.get("limit"), 20, low=1, high=50)
    if not query:
        return JsonResponse({"query": "", "posts": [], "people": [], "topics": [], "insights": {"summary": "Type to search thoughts, people and topics.", "related_terms": []}})

    needle = query.lstrip("#").strip()
    qs = get_annotated_posts(Post.objects.all(), actor).filter(
        Q(body__icontains=needle)
        | Q(author_name__icontains=needle)
        | Q(handle__icontains=needle)
        | Q(topic__name__icontains=needle)
        | Q(topic__category__icontains=needle)
        | Q(tags__icontains=needle)
    ).distinct()[:80]

    documents = [{"text": post.body, "post": post} for post in qs]
    ranked = ai.rank_documents(query, documents, text_key="text")[:limit]
    posts = [serialize_post(item["post"], actor) for item in ranked]

    people_qs = Profile.objects.select_related("user").defer("avatar_blob").filter(
        Q(handle__icontains=needle) | Q(display_name__icontains=needle) | Q(bio__icontains=needle)
    ).annotate(follower_total=Count("user__follower_links", distinct=True)).order_by("-follower_total")[:6]
    people = [serialize_person(person, actor) for person in people_qs]

    topic_qs = Topic.objects.annotate(post_count=Count("posts")).filter(
        Q(name__icontains=needle) | Q(category__icontains=needle)
    ).order_by("-post_count")[:6]
    topics = [topic_payload(topic) for topic in topic_qs]

    insights = ai.search_insights(query, [{"text": post["body"]} for post in posts])
    return JsonResponse({
        "query": query,
        "posts": posts,
        "people": people,
        "topics": topics,
        "total": len(posts),
        "insights": insights,
        "suggestions": [tag for tag in ai.hashtags(query, 3, extra_corpus=[post["body"] for post in posts])],
    })


@api_endpoint
@require_GET
def profile_posts_api(request, handle):
    actor = current_user(request)
    clean_handle = handle.strip().lstrip("@").lower()
    target_profile = get_object_or_404(Profile.objects.select_related("user"), handle__iexact=clean_handle)
    target_user = target_profile.user
    tab = request.GET.get("tab", "thoughts").lower()
    limit = parse_int(request.GET.get("limit"), 40, low=1, high=60)
    offset = parse_int(request.GET.get("offset"), 0, low=0, high=5000)

    if tab == "replies":
        qs = Post.objects.filter(author=target_user, parent__isnull=False)
    elif tab == "likes":
        qs = Post.objects.filter(like_events__user=target_user)
    elif tab == "media":
        qs = Post.objects.filter(author=target_user, image_version__gt=0)
    else:
        tab = "thoughts"
        qs = Post.objects.filter(author=target_user, parent__isnull=True)

    qs = get_annotated_posts(qs, actor).distinct().order_by("-published_at", "-id")
    total = qs.count()
    posts = [serialize_post(post, actor) for post in qs[offset:offset + limit]]
    return JsonResponse({
        "posts": posts,
        "tab": tab,
        "handle": target_profile.handle,
        "total": total,
        "has_more": offset + len(posts) < total,
        "next_offset": offset + len(posts),
    })


# --------------------------------------------------------------------------- #
# AI API
# --------------------------------------------------------------------------- #

# The assistant is free and offline by default, but a configured hosted model
# costs money, so anonymous traffic is kept on a short leash.
AI_RATE_LIMIT = {"anonymous": (60, 600), "member": (300, 600)}   # requests, seconds


def ai_rate_limited(request, action: str) -> int:
    """Return seconds to wait when the caller is over their assistant budget."""
    limit, window = AI_RATE_LIMIT["member" if current_user(request) else "anonymous"]
    identity = request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or request.META.get("REMOTE_ADDR", "local")
    actor = current_user(request)
    scope = f"u{actor.pk}" if actor else f"ip{identity}"
    key = f"athar:ai:{scope}"
    used = cache.get(key, 0)
    if used >= limit:
        return window
    cache.set(key, used + 1, window)
    return 0


@api_endpoint
@require_http_methods(["GET", "POST"])
def ai_api(request, action):
    if action not in {"digest", "topics"}:
        wait = ai_rate_limited(request, action)
        if wait:
            response = JsonResponse({
                "error": "The assistant is taking a short break — try again in a minute.",
                "retry_after": wait,
            }, status=429)
            response.headers["Retry-After"] = str(wait)
            return response
    payload, _ = read_payload(request)
    text = str(payload.get("text") or request.GET.get("text") or "").strip()
    post_id = payload.get("post_id") or request.GET.get("post_id")

    if post_id and not text:
        target = Post.objects.filter(pk=post_id).only("id", "body").first()
        if target:
            text = target.body

    if action in {"reply", "replies"} and not text:
        return JsonResponse({"error": "A thought is needed to suggest replies."}, status=400)

    if action in {"digest"}:
        actor = current_user(request)
        limit = parse_int(payload.get("limit") or request.GET.get("limit"), 25, low=5, high=80)
        posts = list(feed_queryset(actor, tab="all", sort="latest")[:limit])
        result = ai.digest(posts)
        return JsonResponse({
            "provider": ai.provider_info()["provider"],
            "digest": result,
            "topics": feed_topics(5),
        })

    if action in {"search", "insights"}:
        query = text or str(payload.get("query", "")).strip()
        if not query:
            return JsonResponse({"error": "Nothing to analyse."}, status=400)
        matches = get_annotated_posts(Post.objects.all(), current_user(request)).filter(
            Q(body__icontains=query.lstrip("#")) | Q(topic__name__icontains=query.lstrip("#"))
        )[:30]
        insights = ai.search_insights(query, [{"text": post.body} for post in matches])
        return JsonResponse({"insights": insights, "provider": ai.provider_info()["provider"]})

    if action in {"topics"}:
        keywords = ai.keywords(" ".join(post.body for post in feed_queryset(current_user(request), tab="all")[:40]), 6)
        return JsonResponse({"topics": ai.suggest_topics(
            Post.objects.select_related("topic")[:200], Topic.objects.all(), limit=8
        ), "keywords": keywords, "provider": ai.provider_info()["provider"]})

    if not text and action not in {"prompts", "ideas"}:
        return JsonResponse({"error": "Write a few words first, then ask the assistant."}, status=400)

    corpus = []
    if payload.get("use_feed_context"):
        corpus = list(
            Post.objects.order_by("-published_at").values_list("body", flat=True)[:25]
        )

    result = ai.assist(action, text, context={"corpus": corpus, "keywords": ai.keywords(text, 4)})
    result = ai.enrich_with_hosted(action, text, result)
    result["ok"] = True
    return JsonResponse(result)


# --------------------------------------------------------------------------- #
# Media (profile pictures & attachments live in the database)
# --------------------------------------------------------------------------- #

def image_response(request, blob, mime, etag, *, not_found_status=404):
    if not blob:
        return JsonResponse({"error": "Image not found."}, status=not_found_status)
    payload = bytes(blob)
    current_etag = f'"{etag or len(payload)}"'
    if request.headers.get("If-None-Match") == current_etag:
        response = HttpResponse(status=304)
    else:
        response = HttpResponse(payload, content_type=mime or "image/jpeg")
    response.headers["ETag"] = current_etag
    response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    response.headers["Content-Length"] = str(len(payload)) if response.status_code == 200 else "0"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@require_GET
def avatar_media(request, handle, version=None):
    profile = (
        Profile.objects.filter(handle__iexact=handle.strip().lstrip("@"))
        .only("handle", "avatar_blob", "avatar_mime", "avatar_hash", "avatar_version")
        .first()
    )
    if profile is None or not profile.has_avatar:
        return JsonResponse({"error": "No profile picture for this account."}, status=404)
    # The version in the URL is part of the cache key: pictures are served as
    # immutable, so an older version must stop working once it is replaced.
    if version is not None and int(version) != int(profile.avatar_version or 1):
        return JsonResponse({"error": "That picture has been replaced."}, status=404)
    return image_response(request, profile.avatar_blob, profile.avatar_mime, profile.avatar_hash or profile.avatar_version)


@require_GET
def post_image_media(request, post_id, version=None):
    post = Post.objects.filter(pk=post_id).only("id", "image_blob", "image_mime", "image_version").first()
    if post is None or not post.has_image:
        return JsonResponse({"error": "No image attached to this thought."}, status=404)
    if version is not None and int(version) != int(post.image_version or 1):
        return JsonResponse({"error": "That image has been replaced."}, status=404)
    return image_response(request, post.image_blob, post.image_mime, f"post-{post.id}-{post.image_version}")


# --------------------------------------------------------------------------- #
# Auth API
# --------------------------------------------------------------------------- #

@api_endpoint(csrf=False)
@require_http_methods(["GET", "POST"])
def auth_api(request, action):
    """Login/register validate credentials, so they stay reachable from
    cookie-less iframes. Every other mutation is checked inside the view."""
    if action == "me":
        actor = current_user(request)
        return JsonResponse({
            "authenticated": bool(actor),
            "profile": serialize_profile(profile_for(actor), actor, include_stats=True) if actor else None,
            "ai": ai.provider_info(),
        })

    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed."}, status=405)

    payload, uploaded = read_payload(request)

    if action == "logout":
        if not csrf_violation(request):
            logout(request)
        return JsonResponse({"ok": True})

    if action == "login":
        identifier = str(payload.get("username", "")).strip().lower().lstrip("@")
        password = str(payload.get("password", ""))
        if not identifier or not password:
            return JsonResponse({"error": "Please enter your username and password."}, status=400)
        user = authenticate(request, username=identifier, password=password)
        if user is None:
            # Allow signing in with a handle when it differs from the username.
            profile = Profile.objects.filter(handle__iexact=identifier).select_related("user").first()
            if profile:
                user = authenticate(request, username=profile.user.username, password=password)
        if user is None:
            return JsonResponse({"error": "Invalid username or password."}, status=401)
        user.backend = "django.contrib.auth.backends.ModelBackend"
        login(request, user)
        request.session.save()
        return JsonResponse({
            "ok": True,
            "token": request.session.session_key,
            "profile": serialize_profile(profile_for(user), user, include_stats=True),
        })

    if action == "register":
        raw_display_name = str(payload.get("display_name", "")).strip()
        handle = str(payload.get("handle") or payload.get("username") or "").strip().lower().lstrip("@")
        password = str(payload.get("password", ""))

        if not handle or not re.fullmatch(r"[a-z0-9_.-]{1,30}", handle):
            return JsonResponse({"error": "Username must be between 1 and 30 characters (letters, numbers, _, -, .)."}, status=400)

        display_name = raw_display_name if raw_display_name else handle
        if len(display_name) > 50:
            return JsonResponse({"error": "Display Name cannot exceed 50 characters."}, status=400)

        if len(password) < 8:
            return JsonResponse({"error": "Password must be at least 8 characters."}, status=400)

        if Profile.objects.filter(handle__iexact=handle).exists() or User.objects.filter(username__iexact=handle).exists():
            return JsonResponse({"error": "This username is already taken. Please choose another."}, status=409)

        tone = AVATAR_TONES[len(handle) % len(AVATAR_TONES)]
        initial = (display_name[:1] or handle[:1] or "A").upper()
        with transaction.atomic():
            user = User.objects.create_user(username=handle, password=password)
            profile = Profile.objects.create(
                user=user,
                display_name=display_name,
                handle=handle,
                avatar_initial=initial,
                avatar_tone=tone,
            )
            if uploaded is not None:
                media.store_avatar(profile, uploaded[0], uploaded[1])
        user.backend = "django.contrib.auth.backends.ModelBackend"
        login(request, user)
        request.session.save()
        return JsonResponse({
            "ok": True,
            "token": request.session.session_key,
            "profile": serialize_profile(profile, user, include_stats=True),
        }, status=201)

    actor = current_user(request)
    if not actor:
        return auth_required_response()

    # Every remaining action is a cookie/token authenticated mutation.
    if csrf_violation(request):
        return JsonResponse({"error": "Security check failed. Reload the page and try again.", "csrf_failed": True}, status=403)

    if action == "update_profile":
        profile = profile_for(actor)
        bio = str(payload.get("bio", profile.bio)).strip()[:160]
        raw_display_name = str(payload.get("display_name", profile.display_name)).strip()
        avatar_tone = str(payload.get("avatar_tone", profile.avatar_tone)).strip()
        location = str(payload.get("location", profile.location)).strip()[:80]
        website = str(payload.get("website", profile.website)).strip()[:160]
        handle = str(payload.get("handle", "")).strip().lower().lstrip("@")
        messages = []

        if handle and handle != profile.handle:
            if not re.fullmatch(r"[a-z0-9_.-]{1,30}", handle):
                return JsonResponse({"error": "Username must be 1–30 characters (letters, numbers, _, -, .)."}, status=400)
            if Profile.objects.filter(handle__iexact=handle).exclude(pk=profile.pk).exists() or \
                    User.objects.filter(username__iexact=handle).exclude(pk=actor.pk).exists():
                return JsonResponse({"error": "This username is already taken."}, status=409)
            with transaction.atomic():
                profile.handle = handle
                actor.username = handle
                actor.save(update_fields=["username"])
                Post.objects.filter(author=actor).update(handle=handle)
            messages.append(f"Username changed to @{handle}")

        if raw_display_name:
            if len(raw_display_name) > 50:
                return JsonResponse({"error": "Display Name cannot exceed 50 characters."}, status=400)
            profile.display_name = raw_display_name
            profile.avatar_initial = (raw_display_name[:1] or profile.handle[:1] or "A").upper()

        if avatar_tone in AVATAR_TONES:
            profile.avatar_tone = avatar_tone

        if website and not re.match(r"^https?://", website):
            website = f"https://{website}"

        profile.bio = bio
        profile.location = location
        profile.website = website
        profile.save()

        if uploaded is not None:
            media.store_avatar(profile, uploaded[0], uploaded[1])
            messages.append("Profile picture updated")
        elif str(payload.get("remove_avatar", "")).lower() in ("1", "true", "yes"):
            media.clear_avatar(profile)
            messages.append("Profile picture removed")

        Post.objects.filter(author=actor).update(
            author_name=profile.display_name,
            avatar_tone=profile.avatar_tone,
            avatar_initial=profile.avatar_initial or profile.initials,
        )

        return JsonResponse({
            "ok": True,
            "profile": serialize_profile(profile, actor, include_stats=True),
            "messages": messages,
        })

    if action == "change_password":
        current = str(payload.get("current_password", ""))
        new_password = str(payload.get("new_password", ""))
        if not actor.check_password(current):
            return JsonResponse({"error": "Your current password is incorrect."}, status=400)
        if len(new_password) < 8:
            return JsonResponse({"error": "New password must be at least 8 characters."}, status=400)
        actor.set_password(new_password)
        actor.save(update_fields=["password"])
        login(request, actor, backend="django.contrib.auth.backends.ModelBackend")
        request.session.save()
        return JsonResponse({"ok": True, "token": request.session.session_key})

    return JsonResponse({"error": "Action not found."}, status=404)
