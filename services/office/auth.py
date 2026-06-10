import os
from urllib.parse import urlparse, urljoin
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user

auth_bp = Blueprint("auth", __name__)
login_manager = LoginManager()


class AdminUser(UserMixin):
    def __init__(self):
        self.id = "admin"


@login_manager.user_loader
def load_user(user_id):
    if user_id == "admin":
        return AdminUser()
    return None


def _is_safe_url(target: str) -> bool:
    ref = urlparse(request.host_url)
    test = urlparse(urljoin(request.host_url, target))
    return test.scheme in ("http", "https") and ref.netloc == test.netloc


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        _user = os.getenv("ADMIN_USERNAME")
        _pass = os.getenv("ADMIN_PASSWORD")
        if not _user or not _pass:
            raise RuntimeError("ADMIN_USERNAME and ADMIN_PASSWORD environment variables must be set")
        if username == _user and password == _pass:
            session.permanent = True
            login_user(AdminUser(), remember=True)
            next_url = request.args.get("next", "")
            if next_url and _is_safe_url(next_url):
                return redirect(next_url)
            return redirect(url_for("dashboard"))
        flash("نام کاربری یا رمز عبور اشتباه است", "danger")
    return render_template("login.html")


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))
