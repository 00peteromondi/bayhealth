from functools import wraps

from django.core.exceptions import PermissionDenied

from .models import User


def role_required(*roles: str):
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                raise PermissionDenied("Authentication is required.")
            if request.user.role not in roles:
                raise PermissionDenied("You do not have permission to access this resource.")
            return view_func(request, *args, **kwargs)

        return _wrapped

    return decorator


patient_required = role_required(User.Role.PATIENT)
doctor_required = role_required(User.Role.DOCTOR)
counselor_required = role_required(User.Role.COUNSELOR)
pharmacist_required = role_required(User.Role.PHARMACIST)
emergency_operator_required = role_required(User.Role.EMERGENCY_OPERATOR)
