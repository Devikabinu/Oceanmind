from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.user import UserCreate


class EmailAlreadyRegisteredError(Exception):
    pass


class InvalidCredentialsError(Exception):
    pass


class AuthService:
    def __init__(self, user_repository: UserRepository):
        self.user_repository = user_repository

    def register(self, user_in: UserCreate) -> User:
        if self.user_repository.get_by_email(user_in.email) is not None:
            raise EmailAlreadyRegisteredError(f"{user_in.email} is already registered")
        return self.user_repository.create(user_in, hash_password(user_in.password))

    def authenticate(self, email: str, password: str) -> User:
        user = self.user_repository.get_by_email(email)
        if user is None or not user.is_active or not verify_password(password, user.hashed_password):
            raise InvalidCredentialsError("Incorrect email or password")
        return user

    def issue_token(self, user: User) -> str:
        return create_access_token(subject=str(user.id), extra_claims={"role": user.role.value})
