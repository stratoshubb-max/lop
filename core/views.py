import json
import re
from datetime import timedelta

from django.contrib.auth import authenticate, get_user_model, login, logout
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods, require_POST

from .models import Bookmark, Follow, Post, PostLike, PostRepost, Profile, Topic

User = get_user_model()

SEED_TOPICS = [
    {"rank": 1, "category": "في الثقافة", "name": "المدن التي تشبهنا", "meta": "٢٬٤٨٠ منشور"},
    {"rank": 2, "category": "تصميم", "name": "الجمال الوظيفي", "meta": "١٬٩٢٠ منشور"},
    {"rank": 3, "category": "أفكار", "name": "وقت أقل، معنى أكثر", "meta": "٨٧٤ منشور"},
]

SEED_PROFILES = [
    {"display_name": "ليان الشمري", "handle": "layan.s", "initial": "ل", "tone": "violet", "bio": "باحثة في جماليات المدن.", "verified": True},
    {"display_name": "سامر حدّاد", "handle": "samer.haddad", "initial": "س", "tone": "copper", "bio": "أفكار صغيرة، كل صباح.", "verified": False},
    {"display_name": "نورا يونس", "handle": "noura.y", "initial": "ن", "tone": "mint", "bio": "أصمم الأشياء التي تترك مساحة.", "verified": True},
    {"display_name": "عمر فاضل", "handle": "omar.f", "initial": "ع", "tone": "blue", "bio": "أسئلة تجعل الغد أخف.", "verified": False},
    {"display_name": "هدى العتيبي", "handle": "huda.a", "initial": "ه", "tone": "rose", "bio": "أكتب عن الفن والحياة.", "verified": False},
    {"display_name": "بدر منصور", "handle": "badr.m", "initial": "ب", "tone": "gold", "bio": "أبني بهدوء.", "verified": False},
    {"display_name": "مريم ناصر", "handle": "maryam.n", "initial": "م", "tone": "sky", "bio": "بين كتابين ومشوار.", "verified": False},
]

SEED_POSTS = [
    {
        "author_handle": "layan.s",
        "body": "في المدن التي نحبّها، لا نتذكّر الشوارع بقدر ما نتذكّر الضوء الذي كان يلامسها. ربما لهذا تبدو بعض الأمكنة كأنها تعرف أسماءنا.",
        "tags": ["المدينة", "ذاكرة"],
        "published_label": "منذ ٨ دقائق",
        "likes": 184,
        "replies": 12,
        "reposts": 21,
        "topic": "المدن التي تشبهنا",
        "following": True,
    },
    {
        "author_handle": "samer.haddad",
        "body": "فكرة صغيرة لهذا الصباح: ليس كل ما يستحق الانتشار يحتاج إلى ضجيج. أحيانًا يكفيه قارئ واحد، في الوقت المناسب.",
        "tags": ["أفكار", "صباح"],
        "published_label": "منذ ٢٣ دقيقة",
        "likes": 96,
        "replies": 8,
        "reposts": 14,
        "topic": "وقت أقل، معنى أكثر",
        "following": False,
    },
    {
        "author_handle": "noura.y",
        "body": "أحبّ الأشياء المصمّمة بهدوء: كتابًا يترك مساحة للهوامش، غرفة لا تشرح نفسها، ومنتجًا يعرف متى يتوقّف.",
        "tags": ["تصميم", "بساطة"],
        "published_label": "منذ ٤٧ دقيقة",
        "likes": 321,
        "replies": 27,
        "reposts": 38,
        "topic": "الجمال الوظيفي",
        "following": True,
    },
    {
        "author_handle": "omar.f",
        "body": "السؤال الأفضل ليس: كيف ننجز أكثر؟ بل: ما الشيء الوحيد الذي لو أنجزناه اليوم سيجعل الغد أخفّ؟",
        "tags": [],
        "published_label": "منذ ساعة",
        "likes": 72,
        "replies": 5,
        "reposts": 6,
        "topic": "وقت أقل، معنى أكثر",
        "following": True,
    },
]


def arabic_number(value):
    return str(value).translate(str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩"))


def ensure_demo_data():
    """Create editable starter content once; all subsequent changes live in SQLite."""
    profiles = {}
    for item in SEED_PROFILES:
        user, _ = User.objects.get_or_create(username=item["handle"], defaults={"is_active": True})
        if not user.has_usable_password():
            user.set_unusable_password()
            user.save(update_fields=["password"])
        profile, _ = Profile.objects.update_or_create(
            user=user,
            defaults={
                "display_name": item["display_name"],
                "handle": item["handle"],
                "avatar_initial": item["initial"],
                "avatar_tone": item["tone"],
                "bio": item["bio"],
                "verified": item["verified"],
            },
        )
        profiles[item["handle"]] = profile

    topics = {}
    for item in SEED_TOPICS:
        topic, _ = Topic.objects.update_or_create(
            name=item["name"], defaults={"rank": item["rank"], "category": item["category"]}
        )
        topics[item["name"]] = topic

    now = timezone.now()
    for index, item in enumerate(SEED_POSTS):
        author = profiles[item["author_handle"]]
        post, created = Post.objects.get_or_create(
            body=item["body"],
            defaults={
                "author": author.user,
                "author_name": author.display_name,
                "handle": author.handle,
                "avatar_initial": author.avatar_initial,
                "avatar_tone": author.avatar_tone,
                "tags": item["tags"],
                "topic": topics[item["topic"]],
                "published_at": now - timedelta(minutes=(index * 19 + 8)),
                "published_label": item["published_label"],
                "verified": author.verified,
                "likes": item["likes"],
                "replies": item["replies"],
                "reposts": item["reposts"],
            },
        )
        if not created and post.author_id is None:
            post.author = author.user
            post.topic = topics[item["topic"]]
            post.save(update_fields=["author", "topic"])


def get_actor(request):
    """Return a real database user even before the visitor creates an account."""
    if request.user.is_authenticated:
        return request.user

    guest, _ = User.objects.get_or_create(username="athar_guest", defaults={"is_active": True})
    if not guest.has_usable_password():
        guest.set_unusable_password()
        guest.save(update_fields=["password"])
    Profile.objects.get_or_create(
        user=guest,
        defaults={
            "display_name": "أنت",
            "handle": "you",
            "avatar_initial": "أ",
            "avatar_tone": "lime",
            "bio": "أجمع الأشياء التي تجعل الأيام أوسع.",
        },
    )
    return guest


def profile_for(user):
    return Profile.objects.get_or_create(
        user=user,
        defaults={"display_name": "أنت", "handle": "you", "avatar_initial": "أ", "avatar_tone": "lime"},
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


def serialize_profile(profile, actor):
    following = Follow.objects.filter(follower=actor, following=profile.user).exists()
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
    ensure_demo_data()
    actor = get_actor(request)
    actor_profile = profile_for(actor)
    posts = [serialize_post(post, actor) for post in Post.objects.select_related("author", "topic").all()[:20]]
    profile_qs = Profile.objects.exclude(user=actor).order_by("display_name")[:3]
    suggestions = [serialize_profile(profile, actor) for profile in profile_qs]
    topics = [topic_payload(topic) for topic in Topic.objects.all()[:5]]
    viewer_stats = {
        "posts": Post.objects.filter(author=actor, parent__isnull=True).count(),
        "followers": Follow.objects.filter(following=actor).count(),
        "following": Follow.objects.filter(follower=actor).count(),
    }
    return render(
        request,
        "core/home.html",
        {
            "posts": posts,
            "topics": topics,
            "suggestions": suggestions,
            "viewer": actor_profile,
            "viewer_stats": viewer_stats,
            "csrf_token_value": get_token(request),
            "active_view": "home",
        },
    )


@csrf_protect
@require_http_methods(["GET", "POST"])
def posts_api(request):
    ensure_demo_data()
    actor = get_actor(request)

    if request.method == "GET":
        query = request.GET.get("q", "").strip()
        posts = Post.objects.select_related("author", "topic").all()
        if query:
            needle = query.casefold()
            candidates = posts[:100]
            posts = [
                post for post in candidates
                if needle in " ".join(
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
    ensure_demo_data()
    actor = get_actor(request)
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
    ensure_demo_data()
    actor = get_actor(request)
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
        actor = get_actor(request)
        profile = profile_for(actor)
        return JsonResponse({"authenticated": request.user.is_authenticated, "profile": serialize_profile(profile, actor) | {"bio": profile.bio}})

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
        profile = Profile.objects.create(user=user, display_name=display_name, handle=handle, avatar_initial=display_name[:1])
        login(request, user)
        return JsonResponse({"ok": True, "profile": serialize_profile(profile, user)}, status=201)

    return JsonResponse({"error": "الإجراء غير متاح."}, status=404)
