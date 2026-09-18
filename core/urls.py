from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.home, name="home"),
    path("api/posts/", views.posts_api, name="posts-api"),
    path("api/posts/<int:post_id>/<str:action>/", views.post_action_api, name="post-action-api"),
    path("api/profiles/<str:handle>/follow/", views.follow_api, name="follow-api"),
    path("api/auth/<str:action>/", views.auth_api, name="auth-api"),
]
