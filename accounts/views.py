from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.permissions import IsAdminUser
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

User = get_user_model()


class AdminLoginView(APIView):
    """POST /api/admin/login/ {email, password} — equivalente a login() en
    lib/auth.ts del frontend. Responde {token, email} (mismo shape que
    AdminSession) más refreshToken para renovar sesión más adelante."""

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'login'

    def post(self, request):
        email = (request.data.get('email') or '').strip().lower()
        password = request.data.get('password') or ''

        matches = User.objects.filter(email__iexact=email)
        if matches.count() != 1:
            return Response({'detail': 'Correo o contraseña incorrectos.'}, status=status.HTTP_401_UNAUTHORIZED)
        user = matches.first()

        if not user or not user.is_active or not user.is_staff or not user.check_password(password):
            return Response({'detail': 'Correo o contraseña incorrectos.'}, status=status.HTTP_401_UNAUTHORIZED)

        refresh = RefreshToken.for_user(user)
        return Response(
            {
                'email': user.email,
                'token': str(refresh.access_token),
                'refreshToken': str(refresh),
            }
        )


class AdminSessionView(APIView):
    """Valida el access token y devuelve la identidad de la sesión."""

    permission_classes = [IsAdminUser]

    def get(self, request):
        return Response({'email': request.user.email})


class AdminLogoutView(APIView):
    """Revoca el refresh token para que no pueda reutilizarse tras salir."""

    permission_classes = [AllowAny]

    def post(self, request):
        token = request.data.get('refresh')
        if token:
            try:
                RefreshToken(token).blacklist()
            except Exception:
                # Logout es idempotente: un token vencido o ya revocado no debe
                # impedir que el cliente elimine sus cookies.
                pass
        return Response(status=status.HTTP_204_NO_CONTENT)
