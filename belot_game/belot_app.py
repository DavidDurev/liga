"""Flask сървър: стаи, места, ботове и API за играта.

Браузърите питат за състоянието на всеки ~0.7 сек (polling), затова приложението
работи и на хостинги без WebSockets, например PythonAnywhere.
Ботовете и паузите между взятките се движат в tick(), извиквано при всяка заявка,
така че не са нужни фонови нишки.
"""
import random
import secrets
import socket
import string
import threading
import time

from flask import Flask, abort, jsonify, render_template, request

from belot import bots
from belot.engine import Game, sort_hand, trick_winner

app = Flask(__name__)

BOT_DELAY = 0.6          # сек. между ходовете на ботовете
TRICK_PAUSE = 1.3        # сек. колко се вижда завършената взятка
ANNOUNCE_TIME = 2.5      # сек. табела с играта след обявяването – дотогава никой не играе
ROOM_TTL = 6 * 3600
BOT_NAMES = ["Бот Пешо", "Бот Гошо", "Бот Мими", "Бот Тошо"]

rooms = {}
rooms_lock = threading.Lock()


class Room:
    def __init__(self, code):
        self.code = code
        self.seats = [None] * 4        # {"name", "token", "bot", "seen"}
        self.host = None
        self.game = None
        self.notice = None             # съобщение в лобито, напр. кой е прекратил играта
        self.version = 0
        self.last_action = time.time()
        self.announce_until = 0        # до кога се показва табелата с обявената игра
        self.lock = threading.Lock()

    def touch(self):
        self.version += 1
        self.last_action = time.time()

    def bid(self, seat, action):
        g = self.game
        g.bid(seat, action)
        if g.phase == "playing":       # обявяването току-що приключи
            self.announce_until = time.time() + ANNOUNCE_TIME

    def announcing(self):
        return self.game is not None and self.game.phase == "playing" and time.time() < self.announce_until

    def seat_of(self, token):
        for i, s in enumerate(self.seats):
            if s and s.get("token") == token:
                return i
        return None

    def tick(self):
        g = self.game
        if not g:
            return
        now = time.time()
        if g.trick_complete():
            if now - self.last_action >= TRICK_PAUSE:
                g.collect_trick()
                self.touch()
            return
        if self.announcing():
            return
        if g.phase in ("bidding", "playing"):
            seat = self.seats[g.turn]
            if seat and seat["bot"] and now - self.last_action >= BOT_DELAY:
                if g.phase == "bidding":
                    self.bid(g.turn, bots.choose_bid(g, g.turn))
                else:
                    g.play(g.turn, bots.choose_card(g, g.turn))
                self.touch()
        elif g.phase == "hand_over":
            if all(s["bot"] for s in self.seats) and now - self.last_action >= 4:
                g.next_hand()
                self.touch()

    def state_for(self, token):
        me = self.seat_of(token)
        now = time.time()
        seats = [None if not s else {
            "name": s["name"], "bot": s["bot"],
            "online": s["bot"] or now - s.get("seen", 0) < 8,
            "host": s.get("token") == self.host and not s["bot"],
        } for s in self.seats]
        st = {
            "code": self.code, "version": self.version, "seats": seats, "me": me,
            "is_host": token == self.host, "game": None, "notice": self.notice,
        }
        g = self.game
        if g:
            hand = g.hands[me] if me is not None else []
            st["game"] = {
                "phase": g.phase, "dealer": g.dealer, "turn": g.turn, "announce": self.announcing(),
                "contract": g.contract, "bidder": g.bidder, "multiplier": g.multiplier,
                "bids": g.bids[-12:],
                "hand": sort_hand(hand, g.contract if g.phase != "bidding" else None),
                "counts": [len(h) for h in g.hands],
                "legal": g.legal(me) if me is not None and not self.announcing() else [],
                "can_claim": me is not None and not self.announcing() and g.can_claim(me),
                "belots": g.belots,
                "bid_options": g.bid_options(me) if me is not None else [],
                "trick": g.trick, "last_trick": g.last_trick,
                "trick_win": trick_winner(g.trick, g.contract)[0] if len(g.trick) == 4 else None,
                "announced": g.announced, "tricks_won": g.tricks_won,
                "scores": g.scores, "hanging": g.hanging, "history": g.history,
                "hand_result": g.hand_result, "winner": g.winner, "log": g.log[-25:],
            }
        return st


def get_room(code):
    room = rooms.get(code.upper())
    if not room:
        abort(404, "Няма такава стая.")
    return room


def cleanup():
    now = time.time()
    for code in [c for c, r in rooms.items() if now - r.last_action > ROOM_TTL]:
        del rooms[code]


def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))       # не изпраща нищо, само избира мрежовия интерфейс
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return None


# ---------- страници ----------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/r/<code>")
def room_page(code):
    get_room(code)
    return render_template("room.html", code=code.upper())


# ---------- API ----------
@app.post("/api/rooms")
def create_room():
    with rooms_lock:
        cleanup()
        while True:
            code = "".join(random.choices(string.digits, k=4))
            if code not in rooms:
                break
        rooms[code] = Room(code)
    return jsonify({"code": code})


@app.get("/api/info")
def info():
    return jsonify({"lan_ip": lan_ip(), "port": request.host.split(":")[-1] if ":" in request.host else None})


@app.get("/api/rooms/<code>/state")
def state(code):
    room = get_room(code)
    token = request.args.get("token", "")
    with room.lock:
        room.tick()
        me = room.seat_of(token)
        if me is not None:
            room.seats[me]["seen"] = time.time()
        return jsonify(room.state_for(token))


@app.post("/api/rooms/<code>/action")
def action(code):
    room = get_room(code)
    data = request.get_json(force=True) or {}
    token = data.get("token") or ""
    kind = data.get("type")
    with room.lock:
        try:
            result = handle_action(room, token, kind, data)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        room.touch()
        out = room.state_for(result.get("token", token))
        out.update(result)
        return jsonify(out)


def handle_action(room, token, kind, data):
    me = room.seat_of(token)
    g = room.game

    if kind == "sit":
        seat = int(data.get("seat", -1))
        name = (data.get("name") or "").strip()[:20]
        if not name:
            raise ValueError("Въведи име.")
        if g:
            raise ValueError("Играта вече е започнала.")
        if not 0 <= seat < 4 or room.seats[seat]:
            raise ValueError("Мястото е заето.")
        token = token or secrets.token_urlsafe(16)
        if me is not None:
            room.seats[me] = None
        room.seats[seat] = {"name": name, "token": token, "bot": False, "seen": time.time()}
        if room.host is None or room.seat_of(room.host) is None:
            room.host = token
        return {"token": token}

    if kind == "leave":
        if g:
            raise ValueError("Не може да се стане по време на игра.")
        if me is not None:
            room.seats[me] = None
            if room.host == token:
                humans = [s for s in room.seats if s and not s["bot"]]
                room.host = humans[0]["token"] if humans else None
        return {}

    if kind in ("add_bot", "remove_bot", "start"):
        if token != room.host:
            raise ValueError("Само домакинът може да прави това.")
        if g:
            raise ValueError("Играта вече е започнала.")
        if kind == "add_bot":
            seat = int(data.get("seat", -1))
            if not 0 <= seat < 4 or room.seats[seat]:
                raise ValueError("Мястото е заето.")
            room.seats[seat] = {"name": BOT_NAMES[seat], "bot": True}
        elif kind == "remove_bot":
            seat = int(data.get("seat", -1))
            if room.seats[seat] and room.seats[seat]["bot"]:
                room.seats[seat] = None
        else:
            if not all(room.seats):
                raise ValueError("Нужни са 4 играчи (може да добавиш ботове).")
            room.game = Game()
            room.notice = None
        return {}

    if kind == "new_game":
        if token != room.host:
            raise ValueError("Само домакинът може да започне нова игра.")
        room.game = Game()
        return {}

    if me is None or not g:
        raise ValueError("Не участваш в тази игра.")
    if kind == "end_game":
        # Всеки играч на масата може да прекрати; местата се запазват и всички се връщат в лобито.
        room.notice = (f"{room.seats[me]['name']} прекрати играта при резултат "
                       f"{g.scores[0]} : {g.scores[1]} (отбор 1 : отбор 2).")
        room.game = None
        return {}
    if kind == "bid":
        room.bid(me, data.get("bid"))
    elif kind == "play":
        if room.announcing():
            raise ValueError("Изчакай – показва се на какво се играе.")
        g.play(me, data.get("card"))
    elif kind == "claim":
        g.claim(me)
    elif kind == "next_hand":
        g.next_hand()
    else:
        raise ValueError("Непознато действие.")
    return {}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, threaded=True)
