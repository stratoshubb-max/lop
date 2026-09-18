from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.home, name="home"),
    path("api/posts/", views.posts_api, name="posts-api"),
]
