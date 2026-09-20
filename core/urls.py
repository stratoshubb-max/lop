from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    # Pages
    path("", views.home, name="home"),
    path("u/<str:handle>/", views.profile_view, name="profile"),
    path("profile/<str:handle>/", views.profile_view, name="profile-alt"),
    path("p/<int:post_id>/", views.post_detail_view, name="post-detail"),

    # Utility APIs
    path("api/health/", views.health_api, name="health-api"),
    path("api/csrf/", views.csrf_api, name="csrf-api"),

    # Posts
    path("api/posts/", views.posts_api, name="posts-api"),
    path("api/posts/<int:post_id>/", views.post_detail_api, name="post-detail-api"),
    path("api/posts/<int:post_id>/<str:action>/", views.post_action_api, name="post-action-api"),

    # Profiles & social graph
    path("api/profiles/<str:handle>/posts/", views.profile_posts_api, name="profile-posts-api"),
    path("api/profiles/<str:handle>/follow/", views.follow_api, name="follow-api"),
    path("api/profiles/<str:handle>/<str:mode>/", views.followers_api, name="followers-api"),
    path("api/suggestions/", views.suggestions_api, name="suggestions-api"),
    path("api/topics/", views.topics_api, name="topics-api"),
    path("api/search/", views.search_api, name="search-api"),

    # AI assistant
    path("api/ai/<str:action>/", views.ai_api, name="ai-api"),

    # Auth
    path("api/auth/<str:action>/", views.auth_api, name="auth-api"),

    # Media (profile pictures & attachments served from the database)
    path("api/avatar/<str:handle>/<int:version>/", views.avatar_media, name="avatar-media"),
    path("api/avatar/<str:handle>/", views.avatar_media, name="avatar-media-latest"),
    path("api/media/posts/<int:post_id>/<int:version>/", views.post_image_media, name="post-image-media"),
    path("api/media/posts/<int:post_id>/", views.post_image_media, name="post-image-media-latest"),
]
