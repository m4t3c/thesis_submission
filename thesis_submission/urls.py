"""Percorsi di primo livello del progetto.

Qui stanno solo l'area amministrativa e il form di login locale; tutto il
resto e' delegato a appelli/urls.py.
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    # Form di login di Django: in produzione non si usa (si passa da
    # Shibboleth), ma resta la sola via di accesso all'area amministrativa e
    # l'unico modo di provare l'applicazione in locale.
    path(
        "login/",
        auth_views.LoginView.as_view(template_name="registration/login.html"),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("", include("appelli.urls")),
]

# Solo in sviluppo: i file caricati (tesi e video) vengono serviti dal server
# di Django. In produzione se ne occupano le view di download, che ne
# verificano i permessi.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
