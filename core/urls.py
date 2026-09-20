from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.home, name="home"),
    path("u/<str:handle>/", views.profile_view, name="profile"),
    path("profile/<str:handle>/", views.profile_view, name="profile-alt"),
    path("api/health/", views.health_api, name="health-api"),
    path("api/csrf/", views.csrf_api, name="csrf-api"),
    path("api/posts/", views.posts_api, name="posts-api"),
    path("api/posts/<int:post_id>/<str:action>/", views.post_action_api, name="post-action-api"),
    path("api/profiles/<str:handle>/follow/", views.follow_api, name="follow-api"),
    path("api/profiles/<str:handle>/posts/", views.profile_posts_api, name="profile-posts-api"),
    path("api/auth/<str:action>/", views.auth_api, name="auth-api"),
]
