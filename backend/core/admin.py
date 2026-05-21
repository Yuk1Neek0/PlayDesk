from django.contrib import admin

from .models import Booking, Conversation, GameMenu, KnowledgeChunk, Message, Resource, Store

admin.site.register(Store)
admin.site.register(Resource)
admin.site.register(GameMenu)
admin.site.register(Booking)
admin.site.register(Conversation)
admin.site.register(Message)
admin.site.register(KnowledgeChunk)
