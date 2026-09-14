from django.contrib.auth.models import User
from rest_framework import status
from rest_framework.test import APITestCase


class AdminLoginTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='editor', email='editor@elhacedor.pe', password='clave-segura', is_staff=True)

    def test_login_success_returns_token_and_refresh_token(self):
        res = self.client.post('/api/admin/login/', {'email': 'editor@elhacedor.pe', 'password': 'clave-segura'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['email'], 'editor@elhacedor.pe')
        self.assertTrue(res.data['token'])
        self.assertTrue(res.data['refreshToken'])

    def test_login_wrong_password_is_rejected(self):
        res = self.client.post('/api/admin/login/', {'email': 'editor@elhacedor.pe', 'password': 'incorrecta'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_login_unknown_email_is_rejected(self):
        res = self.client.post('/api/admin/login/', {'email': 'nadie@elhacedor.pe', 'password': 'x'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_login_is_case_insensitive_on_email(self):
        res = self.client.post('/api/admin/login/', {'email': 'EDITOR@elhacedor.pe', 'password': 'clave-segura'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_non_staff_user_cannot_login_to_admin(self):
        User.objects.create_user(username='reader', email='reader@elhacedor.pe', password='clave-segura')
        res = self.client.post('/api/admin/login/', {'email': 'reader@elhacedor.pe', 'password': 'clave-segura'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_duplicate_case_insensitive_emails_are_rejected_without_server_error(self):
        User.objects.create_user(username='duplicate', email='EDITOR@ELHACEDOR.PE', password='otra-clave', is_staff=True)
        res = self.client.post('/api/admin/login/', {'email': 'editor@elhacedor.pe', 'password': 'clave-segura'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_session_requires_valid_access_token(self):
        anonymous = self.client.get('/api/admin/session/')
        self.assertEqual(anonymous.status_code, status.HTTP_401_UNAUTHORIZED)
        login = self.client.post('/api/admin/login/', {'email': 'editor@elhacedor.pe', 'password': 'clave-segura'}, format='json')
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {login.data["token"]}')
        authenticated = self.client.get('/api/admin/session/')
        self.assertEqual(authenticated.status_code, status.HTTP_200_OK)
        self.assertEqual(authenticated.data['email'], self.user.email)


class TokenRefreshTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='editor', email='editor@elhacedor.pe', password='clave-segura', is_staff=True)
        login = self.client.post('/api/admin/login/', {'email': 'editor@elhacedor.pe', 'password': 'clave-segura'}, format='json')
        self.refresh_token = login.data['refreshToken']

    def test_refresh_with_valid_token_returns_new_access_token(self):
        res = self.client.post('/api/admin/refresh/', {'refresh': self.refresh_token}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data['access'])

    def test_refresh_with_invalid_token_is_rejected(self):
        res = self.client.post('/api/admin/refresh/', {'refresh': 'no-es-un-token-valido'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_logout_blacklists_refresh_token(self):
        res = self.client.post('/api/admin/logout/', {'refresh': self.refresh_token}, format='json')
        self.assertEqual(res.status_code, status.HTTP_204_NO_CONTENT)
        retry = self.client.post('/api/admin/refresh/', {'refresh': self.refresh_token}, format='json')
        self.assertEqual(retry.status_code, status.HTTP_401_UNAUTHORIZED)
