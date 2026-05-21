"""
URL routes for the PlayDesk agent app.

Include in config/urls.py with:
    path("api/", include("agent.urls")),
"""

from django.urls import path

from . import views

urlpatterns = [
    path("conversations/", views.create_conversation, name="agent-create-conversation"),
    path(
        "conversations/<int:conversation_id>/messages/",
        views.stream_message,
        name="agent-stream-message",
    ),
]
