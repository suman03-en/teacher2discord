from django.urls import path

from . import views

urlpatterns = [
    # Auth
    path("", views.home_view, name="home"),
    path("login/", views.login_view, name="login"),
    path("auth/verify/<uuid:token>/", views.verify_token, name="verify_token"),
    path("auth/logout/", views.logout_view, name="logout"),
    # Teacher dashboard & folders
    path("dashboard/", views.dashboard, name="dashboard"),
    path("folders/<int:folder_id>/", views.folder_detail, name="folder_detail"),
    path("links/<int:link_id>/messages/", views.link_messages, name="link_messages"),
    path("links/<int:link_id>/<str:slug>/", views.link_detail, name="link_detail"),
    # Student
    path("student/<uuid:token>/", views.student_connect, name="student_connect"),
]
