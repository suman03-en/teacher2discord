from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

admin.site.site_header = "Teacher2Discord Admin"
admin.site.site_title = "Teacher2Discord Admin Portal"
admin.site.index_title = "Welcome to Teacher2Discord"

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('broadcast.urls')),
]

if settings.DEBUG:
    import debug_toolbar
    urlpatterns += [
        path('__debug__/', include(debug_toolbar.urls)),
    ]
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
