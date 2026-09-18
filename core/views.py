import json
from datetime import timedelta

from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .models import Post


SEED_POSTS = [
    {
        "author_name": "ليان الشمري",
        "handle": "layan.s",
        "avatar_initial": "ل",
        "avatar_tone": "violet",
        "body": "في المدن التي نحبّها، لا نتذكّر الشوارع بقدر ما نتذكّر الضوء الذي كان يلامسها. ربما لهذا تبدو بعض الأمكنة كأنها تعرف أسماءنا.",
        "tags": ["المدينة", "ذاكرة"],
        "published_label": "منذ ٨ دقائق",
        "verified": True,
        "following": True,
        "likes": 184,
        "replies": 12,
        "reposts": 21,
    },
    {
        "author_name": "سامر حدّاد",
        "handle": "samer.haddad",
        "avatar_initial": "س",
        "avatar_tone": "copper",
        "body": "فكرة صغيرة لهذا الصباح: ليس كل ما يستحق الانتشار يحتاج إلى ضجيج. أحيانًا يكفيه قارئ واحد، في الوقت المناسب.",
        "tags": ["أفكار", "صباح"],
        "published_label": "منذ ٢٣ دقيقة",
        "verified": False,
        "following": False,
        "likes": 96,
        "replies": 8,
        "reposts": 14,
    },
    {
        "author_name": "نورا يونس",
        "handle": "noura.y",
        "avatar_initial": "ن",
        "avatar_tone": "mint",
        "body": "أحبّ الأشياء المصمّمة بهدوء: كتابًا يترك مساحة للهوامش، غرفة لا تشرح نفسها، ومنتجًا يعرف متى يتوقّف.",
        "tags": ["تصميم", "بساطة"],
        "published_label": "منذ ٤٧ دقيقة",
        "verified": True,
        "following": True,
        "likes": 321,
        "replies": 27,
        "reposts": 38,
    },
    {
        "author_name": "عمر فاضل",
        "handle": "omar.f",
        "avatar_initial": "ع",
        "avatar_tone": "blue",
        "body": "السؤال الأفضل ليس: كيف ننجز أكثر؟ بل: ما الشيء الوحيد الذي لو أنجزناه اليوم سيجعل الغد أخفّ؟",
        "tags": [],
        "published_label": "منذ ساعة",
        "verified": False,
        "following": True,
        "likes": 72,
        "replies": 5,
        "reposts": 6,
    },
]

TOPICS = [
    {"rank": "٠١", "category": "في الثقافة", "name": "المدن التي تشبهنا", "meta": "٢٬٤٨٠ منشور"},
    {"rank": "٠٢", "category": "تصميم", "name": "الجمال الوظيفي", "meta": "١٬٩٢٠ منشور"},
    {"rank": "٠٣", "category": "أفكار", "name": "وقت أقل، معنى أكثر", "meta": "٨٧٤ منشور"},
]

SUGGESTIONS = [
    {"name": "هدى العتيبي", "handle": "huda.a", "initial": "ه", "tone": "rose", "following": False},
    {"name": "بدر منصور", "handle": "badr.m", "initial": "ب", "tone": "gold", "following": False},
    {"name": "مريم ناصر", "handle": "maryam.n", "initial": "م", "tone": "sky", "following": False},
]


def seed_posts():
    """Give a new checkout a thoughtful feed without requiring a fixture command."""
    if Post.objects.exists():
        return

    now = timezone.now()
    for index, item in enumerate(SEED_POSTS):
        data = item.copy()
        data["published_at"] = now - timedelta(minutes=(index * 19 + 8))
        Post.objects.create(**data)


def serialize_post(post):
    return {
        "id": post.id,
        "author_name": post.author_name,
        "handle": post.handle,
        "avatar_initial": post.avatar_initial,
        "avatar_tone": post.avatar_tone,
        "body": post.body,
        "tags": post.tags or [],
        "published_label": post.published_label,
        "verified": post.verified,
        "following": post.following,
        "likes": post.likes,
        "replies": post.replies,
        "reposts": post.reposts,
    }


def home(request):
    seed_posts()
    posts = Post.objects.all()[:20]
    return render(
        request,
        "core/home.html",
        {
            "posts": posts,
            "topics": TOPICS,
            "suggestions": SUGGESTIONS,
            "active_view": "home",
        },
    )


@csrf_exempt
@require_http_methods(["GET", "POST"])
def posts_api(request):
    seed_posts()

    if request.method == "GET":
        query = request.GET.get("q", "").strip()
        posts = Post.objects.all()
        if query:
            posts = posts.filter(
                Q(body__icontains=query)
                | Q(author_name__icontains=query)
                | Q(handle__icontains=query)
            )
        return JsonResponse({"posts": [serialize_post(post) for post in posts[:30]]})

    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "تعذّر فهم المنشور."}, status=400)

    body = str(payload.get("body", "")).strip()
    if not body:
        return JsonResponse({"error": "اكتب شيئًا أولًا."}, status=400)
    if len(body) > 500:
        return JsonResponse({"error": "المنشور أطول من المساحة المتاحة."}, status=400)

    post = Post.objects.create(
        author_name="أنت",
        handle="you",
        avatar_initial="أ",
        avatar_tone="lime",
        body=body,
        tags=[],
        published_label="الآن",
        published_at=timezone.now(),
        verified=False,
        following=True,
        likes=0,
        replies=0,
        reposts=0,
    )
    return JsonResponse({"post": serialize_post(post)}, status=201)
