"""Seed Athar with a small, believable community so every feature is visible.

    python manage.py seed_athar            # create demo voices + thoughts
    python manage.py seed_athar --reset    # delete demo content first

Every demo account uses the password ``athar-demo-2026``.
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from core import ai
from core.models import Follow, Post, PostLike, Profile, Topic

User = get_user_model()
DEMO_PASSWORD = "athar-demo-2026"

VOICES = [
    {
        "handle": "layan",
        "display_name": "Layan ✦",
        "tone": "violet",
        "bio": "Designing calm interfaces and reading slowly.",
        "location": "Laghouat",
        "verified": True,
        "thoughts": [
            "Attention is the rarest form of generosity we can offer each other. #attention",
            "A quiet interface is not an empty one. It simply refuses to shout.",
            "I redesigned my mornings around a single question: what deserves the first hour?",
            "Notes from a week of reading before sunrise — slower, but the ideas stayed.",
        ],
    },
    {
        "handle": "sohaib",
        "display_name": "Sohaib El Amine",
        "tone": "mint",
        "bio": "Backend engineer. Writing about systems and patience.",
        "location": "Oran",
        "verified": False,
        "thoughts": [
            "Every database decision is a promise about the future. Make fewer of them. #engineering",
            "Spent the morning deleting code. The system got faster and I felt lighter.",
            "Small tools, kept sharp, outlast grand plans.",
        ],
    },
    {
        "handle": "nour",
        "display_name": "Nour",
        "tone": "gold",
        "bio": "Poetry, cities, and long walks without headphones.",
        "location": "Tunis",
        "verified": True,
        "thoughts": [
            "A city teaches you its rhythm if you walk it slowly enough. #cities",
            "I keep a notebook of overheard sentences. It is the truest archive I own.",
            "Reading a poem aloud changes what it means. Try it tonight.",
        ],
    },
    {
        "handle": "yacine",
        "display_name": "Yacine B.",
        "tone": "blue",
        "bio": "Learning in public. Mostly failing quietly, occasionally useful.",
        "location": "Algiers",
        "verified": False,
        "thoughts": [
            "How do you keep a habit alive on the days you do not feel like it? Asking honestly. #learning",
            "Took the smallest possible step today. It counts.",
            "Reading about attention while being interrupted every four minutes. The irony is not lost.",
        ],
    },
]

REPLIES = [
    ("yacine", "layan", "The first-hour question is a good one — I am stealing it."),
    ("nour", "layan", "Attention as generosity: that reframed my whole morning."),
    ("layan", "sohaib", "Deleting code is the underrated craft of the year."),
    ("sohaib", "yacine", "Shrink the habit until it is almost embarrassing, then keep that version."),
    ("nour", "yacine", "Same question here. Walks without headphones help more than I expected."),
]


class Command(BaseCommand):
    help = "Create demo voices, thoughts, replies and topics so the app has content."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Remove existing demo content first")

    @transaction.atomic
    def handle(self, *args, **options):
        if options["reset"]:
            handles = [voice["handle"] for voice in VOICES]
            Post.objects.filter(handle__in=handles).delete()
            Profile.objects.filter(handle__in=handles).delete()
            User.objects.filter(username__in=handles).delete()
            self.stdout.write(self.style.WARNING("Removed previous demo content."))

        created_posts = {}
        created_count = 0
        tones = ["violet", "lime", "sky", "copper", "rose", "blue", "mint", "gold"]

        for index, voice in enumerate(VOICES):
            user, user_created = User.objects.get_or_create(username=voice["handle"])
            if user_created:
                user.set_password(DEMO_PASSWORD)
                user.save(update_fields=["password"])

            profile, _ = Profile.objects.get_or_create(
                user=user,
                defaults={
                    "display_name": voice["display_name"],
                    "handle": voice["handle"],
                    "avatar_initial": voice["display_name"][:1],
                    "avatar_tone": voice["tone"] or tones[index % len(tones)],
                    "bio": voice["bio"],
                    "location": voice.get("location", ""),
                    "verified": voice.get("verified", False),
                },
            )
            changed = []
            for field in ("display_name", "bio", "location", "verified"):
                if getattr(profile, field) != voice.get(field, getattr(profile, field)):
                    setattr(profile, field, voice.get(field, getattr(profile, field)))
                    changed.append(field)
            if changed:
                profile.save(update_fields=changed)

            for position, body in enumerate(voice["thoughts"]):
                tags = ai.explicit_tags(body, 3)
                topic = None
                if tags:
                    topic, topic_created = Topic.objects.get_or_create(
                        name=tags[0],
                        defaults={"category": ai.categorise_topic(tags[0], body), "rank": min(Topic.objects.count() + 1, 99)},
                    )
                    if topic_created:
                        self.stdout.write(f"  + topic #{topic.name} ({topic.category})")
                post, post_created = Post.objects.get_or_create(
                    handle=voice["handle"],
                    body=body,
                    defaults={
                        "author": user,
                        "author_name": profile.display_name,
                        "avatar_initial": profile.avatar_initial,
                        "avatar_tone": profile.avatar_tone,
                        "tags": tags,
                        "topic": topic,
                        "published_at": timezone.now() - timezone.timedelta(hours=index + position * 3),
                        "published_label": "Just now",
                        "verified": profile.verified,
                    },
                )
                if post_created:
                    created_count += 1
                    created_posts.setdefault(voice["handle"], []).append(post)

        for reply_handle, target_handle, body in REPLIES:
            author = Profile.objects.filter(handle=reply_handle).select_related("user").first()
            target = Post.objects.filter(handle=target_handle, parent__isnull=True).order_by("id").first()
            if not author or not target:
                continue
            if Post.objects.filter(handle=reply_handle, body=body).exists():
                continue
            Post.objects.create(
                author=author.user,
                author_name=author.display_name,
                handle=author.handle,
                avatar_initial=author.avatar_initial,
                avatar_tone=author.avatar_tone,
                body=body,
                parent=target,
                published_at=timezone.now() - timezone.timedelta(minutes=45),
                published_label="Just now",
                verified=author.verified,
            )
            created_count += 1

        handles = [voice["handle"] for voice in VOICES]
        for index, follower in enumerate(handles):
            for target in handles[index + 1:]:
                if (index + len(target)) % 2 == 0:
                    continue
                follower_user = User.objects.filter(username=follower).first()
                target_user = User.objects.filter(username=target).first()
                if follower_user and target_user:
                    Follow.objects.get_or_create(follower=follower_user, following=target_user)

        first_post = Post.objects.filter(parent__isnull=True).order_by("id").first()
        if first_post:
            for handle in handles[1:3]:
                user = User.objects.filter(username=handle).first()
                if user:
                    PostLike.objects.get_or_create(user=user, post=first_post)

        self.stdout.write(self.style.SUCCESS(
            f"Seeded {created_count} new posts · {Post.objects.count()} posts, "
            f"{Profile.objects.count()} profiles, {Topic.objects.count()} topics."
        ))
        self.stdout.write(f"Demo accounts: {', '.join(handles)} (password: {DEMO_PASSWORD})")
