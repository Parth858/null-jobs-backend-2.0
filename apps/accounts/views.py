import datetime

# from django.urls import reverse
import urllib.parse
import logging
import traceback
import requests
from django.conf import settings
from django.contrib.auth import authenticate
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from apps.accounts.models import *
from apps.accounts.renderers import UserRenderer
from apps.accounts.serializers import *
from apps.accounts.utils import *
from apps.jobs.models import User as user_profile
from apps.jobs.constants import response, values

# from django.shortcuts import render


# #google auth
# from allauth.socialaccount.providers.google.views import GoogleOAuth2Adapter
# from allauth.socialaccount.providers.oauth2.client import OAuth2Client
# from dj_rest_auth.registration.views import SocialLoginView
# Generate token Manually

logger = logging.getLogger("accounts")


class GenerateToken:
    logger = logging.getLogger("accounts.GenerateToken")

    @staticmethod
    def get_tokens_for_user(user):
        try:
            logger.info("Generating tokens for user")
            refresh = RefreshToken.for_user(user)
            # custom_payload={"name":user.name,"email":user.email}
            # refresh.payload.update(custom_payload)
            return {
                "refresh": str(refresh),
                "access": str(refresh.access_token),
            }
        except Exception as e:
            logger.critical(f"Error generating tokens: {e}")
            logger.critical(traceback.format_exc())
            return response.create_response(
                response.SOMETHING_WENT_WRONG, status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @staticmethod
    def generate_dummy_jwt_token(Cpayload):
        # creating custom payload with 5 minutes expiration time
        try:
            custom_payload = {
                "exp": datetime.datetime.utcnow() + datetime.timedelta(minutes=5)
            }
            custom_payload.update(Cpayload)
            # Create a new AccessToken with the custom payload
            access_token = AccessToken()
            access_token.payload.update(custom_payload)
            return str(access_token)
        except Exception as e:
            logger.critical(f"Error generating dummy JWT token: {e}")
            logger.critical(traceback.format_exc())
            return response.create_response(
                response.SOMETHING_WENT_WRONG, status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @staticmethod
    def add_payload(token, payload):
        try:
            access_token = AccessToken(token)
            access_token.payload.update(payload)
            return str(access_token)
        except Exception as e:
            logger.critical(f"Not able to add payload to Token: {e}")
            logger.critical(traceback.format_exc())
            return response.create_response(
                response.SOMETHING_WENT_WRONG, status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @staticmethod
    def verify_and_get_payload(token):
        try:
            # Decode the token and verify its validity
            access_token = AccessToken(token)
            # Getting payload
            payload = access_token.payload
            return payload
        except InvalidToken:
            # Token is invalid
            raise InvalidToken("Invalid token")
        except TokenError:
            # Some other token-related error
            raise TokenError("Token expired")


def generate_guest_token(user, purpose):
    try:
        logger.info("Generating guest token")
        payload = {
            "email": user.email,
            "user_id": str(user.id),
            "user_type": user.user_type,
        }
        token = GenerateToken.generate_dummy_jwt_token(payload)

        # for old user
        if user.otp_secret:
            otp = OTP.generate_otp(user)
            user.save()
        # for new user
        else:
            otp, secret = OTP.generate_secret_with_otp()
            user.otp_secret = secret
            user.save()

        # Send Email
        if purpose == "verify":
            subject = "Verify your account"
            body = f"""OTP to verify your account {otp}
            This otp is valid only for 5 minutes
            """
        elif purpose == "reset-password":
            subject = "OTP to confirm your account"
            body = f"""OTP is {otp}
            This otp is valid only for 5 minutes.
            """
        data = {"subject": subject, "body": body, "to_email": user.email}
        Util.send_email(data)
        return token
    except Exception as e:
        logger.critical(f"Error generating guest token: {e}")
        logger.critical(traceback.format_exc())
        return response.create_response(
            response.SOMETHING_WENT_WRONG, status.HTTP_500_INTERNAL_SERVER_ERROR
        )


# Registering the user with otp verification and directly log in the user
class UserRegistrationView(APIView):
    renderer_classes = [UserRenderer]
    logger = logging.getLogger("accounts.UserRegistrationView")

    def post(self, request, format=None):
        try:
            serializer = UserRegistrationSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            email = serializer.save()

            user = User.objects.get(email=email)
            user.provider = "local"
            token = generate_guest_token(user, "verify")

            # Add an entry in the tbl_user_profile with dummy data
            dummy_data = {
                "user_id": user.id,
                "name": user.name,
                "email": user.email,
                "user_type": user.user_type,
            }

            try:
                user_instance = user_profile(**dummy_data)
                user_instance.custom_save(override_uuid={"uuid": dummy_data["user_id"]})
            except Exception:
                self.logger.warning("Something went wrong")
                return Response(
                    {"msg": "Something went wrong"}, status=status.HTTP_400_BAD_REQUEST
                )

            return Response(
                {
                    "msg": "OTP Sent Successfully. Please Check your Email",
                    "url": "otp/verify/",
                    "token": token,
                },
                status=status.HTTP_200_OK,
            )
        except Exception as e:
            self.logger.error(f"User Registration Failed {e}")
            self.logger.error(traceback.format_exc())
            return response.create_response(
                response.SOMETHING_WENT_WRONG, status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class OTPVerificationCheckView(APIView):
    renderer_classes = [UserRenderer]
    logger = logging.getLogger("accounts.OTPVerificationCheck")

    def post(self, request, format=None):
        dummy_token = request.query_params.get("token")
        try:
            payload = GenerateToken.verify_and_get_payload(dummy_token)
            # print(payload)
        except InvalidToken as e:
            self.logger.error(f" token invalid: {str(e)}")
            return Response(
                {"errors": {"token": str(e)}}, status=status.HTTP_401_UNAUTHORIZED
            )
        except TokenError as e:
            self.logger.error(f"Token error : {str(e)}")
            return Response(
                {"errors": {"token": str(e)}}, status=status.HTTP_400_BAD_REQUEST
            )

        serializer = OTPVerificationCheckSerializer(
            data=request.data, context={"email": payload.get("email")}
        )
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        token = GenerateToken.get_tokens_for_user(user)
        self.logger.info("OTP Verified Successfully")
        return Response(
            {"msg": "OTP Verified Successfully!", "token": token},
            status=status.HTTP_201_CREATED,
        )


# Login the user and generate JWT token
class UserLoginView(APIView):
    renderer_classes = [UserRenderer]
    logger = logging.getLogger("accounts.UserLoginView")

    def post(self, request, format=None):
        try:
            serializer = UserLoginSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            email = serializer.data.get("email")
            password = serializer.data.get("password")
            user = authenticate(email=email, password=password)
            if user is not None:
                self.logger.info(f"User {user} successfully logged in.")
                if user.is_verified:
                    token = GenerateToken.get_tokens_for_user(user)
                    return Response(
                        {"token": token, "msg": "Login Success", "verify": True},
                        status=status.HTTP_200_OK,
                    )
                else:
                    token = generate_guest_token(user, "verify")
                    return Response(
                        {"msg": "User not verified", "token": token, "verify": False},
                        status=status.HTTP_200_OK,
                    )
            else:
                self.logger.warning(
                    f"user {email} Login attempt failed. Invalid email or password."
                )
                return Response(
                    {
                        "errors": {
                            "non_field_errors": ["Email or Password is not valid"]
                        }
                    },
                    status=status.HTTP_404_NOT_FOUND,
                )
        except Exception as e:
            self.logger.error(f"An error occurred during login: {e}")
            self.logger.error(traceback.format_exc())
            return Response(
                {"errors": {"non_field_errors": ["An error occurred during login"]}},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


# Show profile of logged in user
class UserProfileView(APIView):
    renderer_classes = [UserRenderer]
    permission_classes = [IsAuthenticated]

    def get(self, request, format=None):
        try:
            serializer = UserProfileSerializer(request.user)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Exception as e:
            self.logger.warning("Profile view failed")


# LogOut User
class UserLogOutView(APIView):
    renderer_classes = [UserRenderer]
    permission_classes = [IsAuthenticated]
    logger = logging.getLogger("accounts.UserLogOutView")

    def post(self, request, format=None):
        # breakpoint()
        try:
            # token = request.META['HTTP_AUTHORIZATION'].split(' ')[1]
            # print(token)
            # access_token = AccessToken(token)
            # access_token.set_exp(lifetime=datetime.timedelta(minutes=1))
            # print(access_token)
            # breakpoint()
            self.logger.info("Logging Out")
            refresh_token = request.data["refresh_token"]
            token_obj = RefreshToken(refresh_token)
            token_obj.blacklist()
            self.logger.info("LogOut Successfully")
            return Response(
                {
                    "msg": "LogOut Successfully",
                    # "token":access_token,
                },
                status=status.HTTP_200_OK,
            )
        except Exception as e:
            self.logger.warning(f"{'msg': str(e)}")
            return Response(
                {"errors": {"msg": str(e)}}, status=status.HTTP_400_BAD_REQUEST
            )


# Password Reset functionality (forget password)
class SendPasswordResetOTPView(APIView):
    renderer_classes = [UserRenderer]
    logger = logging.getLogger("accounts.SendPasswordResetOTPView")

    def post(self, request, format=None):
        try:
            serializer = SendPasswordResetOTPSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            user = serializer.validated_data["user"]
            token = generate_guest_token(user, "reset-password")
            self.logger.info("OTP Send Successfully")
            return Response(
                {
                    "msg": "OTP Sent Successfully. Please Check your Email",
                    "token": token,
                },
                status=status.HTTP_200_OK,
            )
        except Exception as e:
            self.logger.critical("Error sending OTP")
            self.logger.critical(traceback.format())


# View for verifying the otp to reset password
class ResetPasswordOtpVerifyView(APIView):
    renderer_classes = [UserRenderer]
    logger = logging.getLogger("accounts.ResetPasswordOtpVerifyView")

    def post(self, request, format=None):
        try:
            dummy_token = request.query_params.get("token")
            try:
                payload = GenerateToken.verify_and_get_payload(dummy_token)
            except InvalidToken as e:
                return Response(
                    {"errors": {"token": str(e)}}, status=status.HTTP_401_UNAUTHORIZED
                )
            except TokenError as e:
                return Response(
                    {"errors": {"token": str(e)}}, status=status.HTTP_400_BAD_REQUEST
                )

            serializer = ResetPasswordOtpVerifySerializer(
                data=request.data, context={"email": payload.get("email")}
            )
            serializer.is_valid(raise_exception=True)
            uid = serializer.validated_data["uid"]
            token = serializer.validated_data["token"]
            return Response(
                {"msg": "Verified Successfully!", "token": token, "uid": uid},
                status=status.HTTP_200_OK,
            )
        except Exception as e:
            self.logger.error(f"Reset Password Failed: {e}")
            self.logger.error(traceback.format_exc())
            return response.create_response(
                response.SOMETHING_WENT_WRONG, status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class UserPasswordResetView(APIView):
    renderer_classes = [UserRenderer]
    logger = logging.getLogger("accounts.UserPasswordResetView")

    def post(self, request, format=None):
        try:
            uid = request.query_params.get("uid")
            token = request.query_params.get("token")
            serializer = UserPasswordResetSerializer(
                data=request.data, context={"uid": uid, "token": token}
            )
            serializer.is_valid(raise_exception=True)
            user = serializer.validated_data["user"]
            body = "Your password is successfully changed.\nLogin to your account to access your account."
            data = {
                "subject": "Reset Your Password",
                "body": body,
                "to_email": user.email,
            }
            Util.send_email(data)
            return Response(
                {"msg": "Password Reset Successfully"}, status=status.HTTP_200_OK
            )
        except Exception as e:
            self.logger.critical(f"Password reset failed: {e}")
            self.logger.critical(traceback.format_exc())
            return Response(
                {"error": "Internal Server Error"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


# Password Changed functionality with otp verification
class UserChangePasswordView(APIView):
    renderer_classes = [UserRenderer]
    permission_classes = [IsAuthenticated]
    logger = logging.getLogger("accounts.UserChangePasswordView")

    def post(self, request, format=None):
        try:
            serializer = UserChangePasswordSerializer(
                data=request.data, context={"user": request.user}
            )
            serializer.is_valid(raise_exception=True)
            return Response(
                {"msg": "OTP Sent Successfully. Please Check your Email"},
                status=status.HTTP_200_OK,
            )
        except Exception as e:
            self.logger.critical(f"Password change failed: {e}")
            self.logger.critical(traceback.format_exc())
            return Response(
                {"error": "Internal Server Error"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class UserChangePasswordOTPView(APIView):
    renderer_classes = [UserRenderer]
    permission_classes = [IsAuthenticated]
    logger = logging.getLogger("accounts.UserChangePasswordOTPView")

    def post(self, request, format=None):
        try:
            serializer = UserChangePasswordOTPSerializer(
                data=request.data, context={"user": request.user}
            )
            serializer.is_valid(raise_exception=True)
            self.logger.info("Password changed successfully")
            return Response(
                {"msg": "Password Changed Successfully"}, status=status.HTTP_200_OK
            )
        except Exception as e:
            self.logger.error(f"Error in UserChangePasswordOTPView: {e}")
            self.logger.error(traceback.format_exc())
            return Response(
                {"error": "Internal Server Error"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


# Hit on that url to get the callback
# https://accounts.google.com/o/oauth2/v2/auth?client_id=<google-client-id>&response_type=code&scope=https://www.googleapis.com/auth/userinfo.email https://www.googleapis.com/auth/userinfo.profile&access_type=offline&redirect_uri=http://localhost:8000/api/user/google/login/callback/


class GoogleHandle(APIView):
    renderer_classes = [UserRenderer]
    logger = logging.getLogger("accounts.GoogleHandle")

    def get(self, request):
        try:
            client_id = os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
            response_type = "code"
            scope = f"https://www.googleapis.com/auth/userinfo.email "
            scope += f"https://www.googleapis.com/auth/userinfo.profile"
            access_type = "offline"
            redirect_uri = settings.GOOGLE_REDIRECT_URI

            google_redirect_url = "https://accounts.google.com/o/oauth2/v2/auth"
            google_redirect_url += f"?client_id={urllib.parse.quote(client_id)}"
            google_redirect_url += f"&response_type={urllib.parse.quote(response_type)}"
            google_redirect_url += f"&scope={urllib.parse.quote(scope)}"
            google_redirect_url += f"&access_type={urllib.parse.quote(access_type)}"
            google_redirect_url += f"&redirect_uri={urllib.parse.quote(redirect_uri)}"
            return Response(
                {"google_redirect_url": google_redirect_url}, status=status.HTTP_200_OK
            )
        except Exception as e:
            self.logger.critical(f"Error in GoogleHandle: {e}")
            self.logger.critical(traceback.format_exc())
            return Response(
                {"error": "Internal Server Error"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class CallbackHandleView(APIView):
    renderer_classes = [UserRenderer]
    logger = logging.getLogger("accounts.CallbackHandleView")

    def get(self, request):
        try:
            code = request.query_params.get("code")
            data = {
                "code": code,
                "client_id": os.environ.get("GOOGLE_OAUTH_CLIENT_ID"),
                "client_secret": os.environ.get("GOOGLE_OAUTH_SECRET"),
                "redirect_uri": settings.GOOGLE_REDIRECT_URI,
                "grant_type": "authorization_code",
            }

            token_response = requests.post(
                "https://oauth2.googleapis.com/token", data=data
            )
            token_data = token_response.json()

            if "error" in token_data:
                self.logger.critical("Failed to get access token from Google")
                return Response(
                    {"error": "Failed to get access token from Google."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Get the access token from the response
            access_token = token_data.get("access_token", None)
            # print(access_token)
            if not access_token:
                self.logger.critical("Failed to get access token from Google response.")
                return Response(
                    {"error": "Failed to get access token from Google response."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Use the access token to retrieve user information from Google
            user_info_response = requests.get(
                f"https://www.googleapis.com/oauth2/v2/userinfo?access_token={access_token}"
            )
            user_info = user_info_response.json()
            # print(user_info)
            # Extract the email and name from the user information
            email = user_info.get("email", None)
            name = user_info.get("name", None)
            if not email:
                return Response(
                    {"error": "Failed to get email from Google user info."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if not name:
                return Response(
                    {"error": "Failed to get name from Google user info."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            try:
                # Login the user
                user = User.objects.get(email=email)
                jwt_token = GenerateToken.get_tokens_for_user(user)
                return Response(
                    {"token": jwt_token, "msg": "Login Success"},
                    status=status.HTTP_200_OK,
                )

            except User.DoesNotExist:
                userdata = {"email": email, "name": name}
                serializer = GoogleAuthSerializer(
                    data=request.data, context={"userdata": userdata}
                )
                serializer.is_valid(raise_exception=True)
                user = serializer.save()
                user.provider = "google"
                user.is_verified = True
                user.save()
                token = GenerateToken.get_tokens_for_user(user)
                self.logger.info("Registration Complete")
                return Response(
                    {"msg": "Registration Completed", "token": token},
                    status=status.HTTP_201_CREATED,
                )

            except:
                self.logger.error("Invalid user")
                return Response(
                    {"errors": "Invalid user"}, status=status.HTTP_400_BAD_REQUEST
                )
        except Exception as e:
            self.logger.error(f"Error in CallbackHandleView: {e}")
            self.logger.error(traceback.format_exc())
            return Response(
                {"error": "Internal Server Error"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class RestrictedPage(APIView):
    renderer_classes = [UserRenderer]
    permission_classes = [IsAuthenticated] if settings.ENABLE_AUTHENTICATION else []
    logger = logging.getLogger("accounts.RestrictedPage")

    def get(self, request, format=None):
        return Response({"msg": "I am a restricted page"}, status=status.HTTP_200_OK)
