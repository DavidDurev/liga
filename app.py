# -*- coding: utf-8 -*-
"""
Селска Футболна Лига
---------------------
Уеб приложение за седмични прогнози на футболни мачове в приятелска група.

Точкуване:
  - Познат резултат (1 / X / 2)  -> 1 точка * коефициент на betano.bg за този изход
  - Познат точен резултат        -> 3 точки * коефициент на betano.bg за този изход
  - Непознат изход                -> 0 точки

Стартиране:
  pip install -r requirements.txt
  python app.py
  -> отвори http://127.0.0.1:5000

Първият регистриран потребител автоматично става администратор.
"""

import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from flask import Flask, render_template, redirect, url_for, flash, request, abort
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import IntegrityError
from flask_login import (
    LoginManager, UserMixin, login_user, logout_user,
    login_required, current_user
)
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "smeni-tozi-kljuch-v-produkcia")
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(BASE_DIR, "liga.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

# Всички часове (краен срок, начален час на мач) се третират като българско време,
# независимо къде физически работи сървърът (напр. PythonAnywhere е на UTC).
TZ = ZoneInfo("Europe/Sofia")
PREDICTION_CUTOFF = timedelta(minutes=5)


def now_local():
    """Текущото време по българско часово време, като 'наивен' datetime (без tzinfo),
    за да може директно да се сравнява с часовете, въведени от админа."""
    return datetime.now(TZ).replace(tzinfo=None)

login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Моля, влезте в профила си, за да продължите."
login_manager.login_message_category = "warning"


# ---------------------------------------------------------------------------
# Модели
# ---------------------------------------------------------------------------

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    predictions = db.relationship(
        "Prediction", backref="user", lazy=True, cascade="all, delete-orphan"
    )

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Week(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.Integer, unique=True, nullable=False)
    is_closed = db.Column(db.Boolean, default=False, nullable=False)  # ръчно затворена от админ

    matches = db.relationship(
        "Match", backref="week", lazy=True,
        order_by="Match.kickoff_time", cascade="all, delete-orphan"
    )

    def all_matches_finished(self):
        return len(self.matches) > 0 and all(m.is_finished() for m in self.matches)


class Match(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    week_id = db.Column(db.Integer, db.ForeignKey("week.id"), nullable=False)

    home_team = db.Column(db.String(80), nullable=False)
    away_team = db.Column(db.String(80), nullable=False)
    kickoff_time = db.Column(db.DateTime, nullable=False)

    # Коефициенти от betano.bg
    odd_1 = db.Column(db.Float, nullable=False)
    odd_x = db.Column(db.Float, nullable=False)
    odd_2 = db.Column(db.Float, nullable=False)

    # Резултат (нищо, докато не е въведен от админ)
    actual_home = db.Column(db.Integer, nullable=True)
    actual_away = db.Column(db.Integer, nullable=True)

    predictions = db.relationship(
        "Prediction", backref="match", lazy=True, cascade="all, delete-orphan"
    )

    def is_finished(self):
        return self.actual_home is not None and self.actual_away is not None

    def prediction_deadline(self):
        return self.kickoff_time - PREDICTION_CUTOFF

    def is_open_for_prediction(self):
        if self.week.is_closed or self.is_finished():
            return False
        return now_local() < self.prediction_deadline()

    def actual_sign(self):
        if not self.is_finished():
            return None
        if self.actual_home > self.actual_away:
            return "1"
        if self.actual_home < self.actual_away:
            return "2"
        return "X"

    def odd_for_sign(self, sign):
        return {"1": self.odd_1, "X": self.odd_x, "2": self.odd_2}.get(sign)

    def label(self):
        return f"{self.home_team} – {self.away_team}"


class Prediction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    match_id = db.Column(db.Integer, db.ForeignKey("match.id"), nullable=False)

    pred_home = db.Column(db.Integer, nullable=False)
    pred_away = db.Column(db.Integer, nullable=False)
    points = db.Column(db.Float, nullable=True)  # изчислява се, когато мачът приключи

    __table_args__ = (db.UniqueConstraint("user_id", "match_id", name="uq_user_match"),)

    def pred_sign(self):
        if self.pred_home > self.pred_away:
            return "1"
        if self.pred_home < self.pred_away:
            return "2"
        return "X"

    def compute_points(self):
        m = self.match
        if not m.is_finished():
            self.points = None
            return
        actual_sign = m.actual_sign()
        odd = m.odd_for_sign(actual_sign)
        if self.pred_sign() != actual_sign:
            self.points = 0.0
            return
        exact = (self.pred_home == m.actual_home and self.pred_away == m.actual_away)
        self.points = round((3 if exact else 1) * odd, 2)


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            abort(403)
        return view(*args, **kwargs)
    return wrapped


# ---------------------------------------------------------------------------
# Помощни функции
# ---------------------------------------------------------------------------

def current_week():
    """Най-новата седмица, която не е затворена ръчно; иначе последната създадена."""
    open_week = (
        Week.query.filter_by(is_closed=False)
        .order_by(Week.number.desc())
        .first()
    )
    if open_week:
        return open_week
    return Week.query.order_by(Week.number.desc()).first()


def standings(week_id=None):
    """Връща списък (потребител, точки) сортиран по точки низходящо."""
    query = db.session.query(User)
    result = []
    for user in query.all():
        preds = [p for p in user.predictions if p.points is not None]
        if week_id is not None:
            preds = [p for p in preds if p.match.week_id == week_id]
        total = round(sum(p.points for p in preds), 2)
        played = len(preds)
        result.append({"user": user, "total": total, "played": played})
    result.sort(key=lambda r: r["total"], reverse=True)
    return result


@app.context_processor
def inject_globals():
    return {"now": now_local()}


# ---------------------------------------------------------------------------
# Автентикация
# ---------------------------------------------------------------------------

@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")

        if not username or not password:
            flash("Попълни потребителско име и парола.", "danger")
        elif password != confirm:
            flash("Паролите не съвпадат.", "danger")
        elif User.query.filter_by(username=username).first():
            flash("Това потребителско име вече е заето.", "danger")
        else:
            is_first_user = User.query.count() == 0
            user = User(username=username, is_admin=is_first_user)
            user.set_password(password)
            db.session.add(user)
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                flash("Това потребителско име вече е заето — опитай с друго или влез в профила си.", "danger")
                return render_template("register.html")
            flash(
                "Регистрацията е успешна! Вече си администратор на лигата."
                if is_first_user else "Регистрацията е успешна, влез в профила си.",
                "success",
            )
            return redirect(url_for("login"))
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            flash(f"Добре дошъл, {user.username}!", "success")
            return redirect(url_for("index"))
        flash("Грешно потребителско име или парола.", "danger")
    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Излезе от профила си.", "info")
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# Основни страници
# ---------------------------------------------------------------------------

@app.route("/")
@login_required
def index():
    week = current_week()
    existing = {}
    if week:
        rows = Prediction.query.filter_by(user_id=current_user.id).join(Match).filter(
            Match.week_id == week.id
        ).all()
        existing = {p.match_id: p for p in rows}
    return render_template("index.html", week=week, existing=existing)


@app.route("/predict/<int:week_id>", methods=["POST"])
@login_required
def predict(week_id):
    week = db.session.get(Week, week_id)
    if not week:
        abort(404)

    saved, skipped = 0, 0
    for match in week.matches:
        h_raw = request.form.get(f"home_{match.id}")
        a_raw = request.form.get(f"away_{match.id}")
        if h_raw is None or a_raw is None or h_raw == "" or a_raw == "":
            continue  # този мач не е бил в отворената форма (или е пропуснат нарочно)

        if not match.is_open_for_prediction():
            skipped += 1
            continue

        try:
            h, a = int(h_raw), int(a_raw)
            if h < 0 or a < 0:
                raise ValueError
        except ValueError:
            flash(f"Невалиден резултат за {match.label()}.", "danger")
            continue

        pred = Prediction.query.filter_by(user_id=current_user.id, match_id=match.id).first()
        if pred is None:
            pred = Prediction(user_id=current_user.id, match_id=match.id)
            db.session.add(pred)
        pred.pred_home = h
        pred.pred_away = a
        saved += 1

    db.session.commit()

    if saved:
        flash(f"Запазени прогнози: {saved}.", "success")
    if skipped:
        flash(f"{skipped} мач(а) вече не приемат прогнози (до 5 мин. преди начален час) и не бяха запазени.", "warning")
    if not saved and not skipped:
        flash("Няма подадени промени.", "info")
    return redirect(url_for("index"))


@app.route("/standings")
@login_required
def standings_view():
    weeks = Week.query.order_by(Week.number.asc()).all()
    week_id = request.args.get("week", type=int)
    overall = standings()
    weekly = standings(week_id) if week_id else None
    selected_week = db.session.get(Week, week_id) if week_id else None
    return render_template(
        "standings.html", overall=overall, weeks=weeks,
        weekly=weekly, selected_week=selected_week
    )


@app.route("/history")
@login_required
def history():
    rows = (
        Prediction.query.filter_by(user_id=current_user.id)
        .join(Match).join(Week)
        .order_by(Week.number.desc(), Match.kickoff_time.asc())
        .all()
    )
    return render_template("history.html", rows=rows)


# ---------------------------------------------------------------------------
# Администраторски панел
# ---------------------------------------------------------------------------

@app.route("/admin")
@login_required
@admin_required
def admin_dashboard():
    weeks = Week.query.order_by(Week.number.desc()).all()
    return render_template("admin/dashboard.html", weeks=weeks)


@app.route("/admin/week/new", methods=["POST"])
@login_required
@admin_required
def admin_new_week():
    last = Week.query.order_by(Week.number.desc()).first()
    next_number = (last.number + 1) if last else 1

    week = Week(number=next_number)
    db.session.add(week)
    db.session.commit()
    flash(f"Седмица {next_number} е създадена.", "success")
    return redirect(url_for("admin_week", week_id=week.id))


@app.route("/admin/week/<int:week_id>")
@login_required
@admin_required
def admin_week(week_id):
    week = db.session.get(Week, week_id)
    if not week:
        abort(404)
    return render_template("admin/week.html", week=week)


@app.route("/admin/week/<int:week_id>/add_match", methods=["POST"])
@login_required
@admin_required
def admin_add_match(week_id):
    week = db.session.get(Week, week_id)
    if not week:
        abort(404)
    if len(week.matches) >= 5:
        flash("Тази седмица вече има 5 мача.", "warning")
        return redirect(url_for("admin_week", week_id=week.id))

    try:
        home = request.form["home_team"].strip()
        away = request.form["away_team"].strip()
        odd_1 = float(request.form["odd_1"])
        odd_x = float(request.form["odd_x"])
        odd_2 = float(request.form["odd_2"])
        kickoff = datetime.strptime(request.form["kickoff_time"], "%Y-%m-%dT%H:%M")
        if not home or not away or odd_1 <= 0 or odd_x <= 0 or odd_2 <= 0:
            raise ValueError
    except (KeyError, ValueError):
        flash("Провери въведените данни за мача (начален час, отбори, коефициенти от betano.bg).", "danger")
        return redirect(url_for("admin_week", week_id=week.id))

    match = Match(
        week_id=week.id, home_team=home, away_team=away,
        odd_1=odd_1, odd_x=odd_x, odd_2=odd_2, kickoff_time=kickoff,
    )
    db.session.add(match)
    db.session.commit()
    flash("Мачът е добавен.", "success")
    return redirect(url_for("admin_week", week_id=week.id))


@app.route("/admin/match/<int:match_id>/delete", methods=["POST"])
@login_required
@admin_required
def admin_delete_match(match_id):
    match = db.session.get(Match, match_id)
    if not match:
        abort(404)
    week_id = match.week_id
    db.session.delete(match)
    db.session.commit()
    flash("Мачът е изтрит.", "info")
    return redirect(url_for("admin_week", week_id=week_id))


@app.route("/admin/match/<int:match_id>/result", methods=["POST"])
@login_required
@admin_required
def admin_set_result(match_id):
    match = db.session.get(Match, match_id)
    if not match:
        abort(404)
    try:
        home = int(request.form["actual_home"])
        away = int(request.form["actual_away"])
        if home < 0 or away < 0:
            raise ValueError
    except (KeyError, ValueError):
        flash("Невалиден резултат.", "danger")
        return redirect(url_for("admin_week", week_id=match.week_id))

    match.actual_home = home
    match.actual_away = away
    db.session.commit()

    for pred in match.predictions:
        pred.compute_points()
    db.session.commit()

    flash(f"Резултатът за {match.label()} е въведен и точките са преизчислени.", "success")
    return redirect(url_for("admin_week", week_id=match.week_id))


@app.route("/admin/users")
@login_required
@admin_required
def admin_users():
    users = User.query.order_by(User.username.asc()).all()
    return render_template("admin/users.html", users=users)


@app.route("/admin/user/<int:user_id>/delete", methods=["POST"])
@login_required
@admin_required
def admin_delete_user(user_id):
    user = db.session.get(User, user_id)
    if not user:
        abort(404)
    if user.id == current_user.id:
        flash("Не можеш да изтриеш собствения си профил.", "danger")
        return redirect(url_for("admin_users"))
    if user.is_admin and User.query.filter_by(is_admin=True).count() <= 1:
        flash("Трябва да остане поне един администратор.", "danger")
        return redirect(url_for("admin_users"))

    db.session.delete(user)
    db.session.commit()
    flash(f"Потребителят {user.username} е изтрит заедно с прогнозите му.", "info")
    return redirect(url_for("admin_users"))


@app.route("/admin/week/<int:week_id>/toggle_close", methods=["POST"])
@login_required
@admin_required
def admin_toggle_close(week_id):
    week = db.session.get(Week, week_id)
    if not week:
        abort(404)
    week.is_closed = not week.is_closed
    db.session.commit()
    flash(
        "Седмицата е затворена за прогнози." if week.is_closed else "Седмицата отново приема прогнози.",
        "info",
    )
    return redirect(url_for("admin_week", week_id=week.id))


# ---------------------------------------------------------------------------
# Грешки
# ---------------------------------------------------------------------------

@app.errorhandler(403)
def forbidden(e):
    return render_template("error.html", code=403, message="Нямаш достъп до тази страница."), 403


@app.errorhandler(404)
def not_found(e):
    return render_template("error.html", code=404, message="Страницата не е намерена."), 404


# ---------------------------------------------------------------------------

with app.app_context():
    db.create_all()

if __name__ == "__main__":
    # host="0.0.0.0" -> сайтът приема връзки от всяка мрежова карта, не само локално.
    # debug=False    -> задължително, когато сайтът е достъпен от интернет (debug режимът
    #                    позволява изпълнение на код отдалечено при грешка).
    app.run(host="0.0.0.0", port=5000, debug=False)
