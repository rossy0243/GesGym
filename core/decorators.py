from django.shortcuts import redirect

def role_required(allowed_roles):

    def decorator(view_func):

        def wrapper(request, *args, **kwargs):

            if request.user.role not in allowed_roles:
                return redirect("compte:login")

            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator