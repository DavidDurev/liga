"""Логика на българския белот: раздаване, обявяване, игра, анонси и точкуване.

Местата са 0..3. Отбор 0 = места 0 и 2, отбор 1 = места 1 и 3.
Играе се обратно на часовниковата стрелка: след място s идва (s + 1) % 4.
Картите са низове от ранг + боя, например "JH" (вале купа), "10S" (десетка пика).
"""
import itertools
import random

SUITS = ["C", "D", "H", "S"]
RANKS = ["7", "8", "9", "10", "J", "Q", "K", "A"]   # естествен ред (за терци/кварти/квинти)
PLAIN_ORDER = ["7", "8", "9", "J", "Q", "K", "10", "A"]
TRUMP_ORDER = ["7", "8", "Q", "K", "10", "A", "9", "J"]
PLAIN_POINTS = {"7": 0, "8": 0, "9": 0, "J": 2, "Q": 3, "K": 4, "10": 10, "A": 11}
TRUMP_POINTS = {"7": 0, "8": 0, "Q": 3, "K": 4, "10": 10, "A": 11, "9": 14, "J": 20}

CONTRACTS = ["C", "D", "H", "S", "NT", "AT"]          # по сила
CONTRACT_NAMES = {"C": "Спатия", "D": "Каро", "H": "Купа", "S": "Пика",
                  "NT": "Без коз", "AT": "Всичко коз"}
CARRE_VALUES = {"J": 200, "9": 150, "A": 100, "10": 100, "K": 100, "Q": 100}
SEQ_VALUES = {3: 20, 4: 50, 5: 100}
SEQ_NAMES = {3: "Терца", 4: "Кварта", 5: "Квинта"}
WIN_SCORE = 151


def rank(card):
    return card[:-1]


def suit(card):
    return card[-1]


def team(seat):
    return seat % 2


def is_trump(card, contract):
    return contract == "AT" or suit(card) == contract


def card_order(card, contract):
    order = TRUMP_ORDER if is_trump(card, contract) else PLAIN_ORDER
    return order.index(rank(card))


def card_points(card, contract):
    table = TRUMP_POINTS if is_trump(card, contract) else PLAIN_POINTS
    return table[rank(card)]


def new_deck():
    return [r + s for s in SUITS for r in RANKS]


def trick_winner(trick, contract):
    """trick: списък от (seat, card). Връща (seat, card) на печелившата карта."""
    lead = suit(trick[0][1])
    if contract in SUITS:
        trumps = [p for p in trick if suit(p[1]) == contract]
        if trumps:
            return max(trumps, key=lambda p: card_order(p[1], contract))
    followers = [p for p in trick if suit(p[1]) == lead]
    return max(followers, key=lambda p: card_order(p[1], contract))


def legal_cards(hand, trick, contract, seat):
    if not trick:
        return list(hand)
    lead = suit(trick[0][1])
    follow = [c for c in hand if suit(c) == lead]
    win_seat, win_card = trick_winner(trick, contract)

    def higher_than_winner(cards):
        return [c for c in cards if suit(c) == suit(win_card)
                and card_order(c, contract) > card_order(win_card, contract)]

    if contract == "NT":
        return follow or list(hand)
    if contract == "AT":
        if follow:
            return higher_than_winner(follow) or follow
        return list(hand)

    # Игра на цвят
    if lead == contract:
        if follow:
            return higher_than_winner(follow) or follow
        return list(hand)
    if follow:
        return follow
    trumps = [c for c in hand if suit(c) == contract]
    if team(win_seat) == team(seat) or not trumps:
        return list(hand)          # партньорът държи ръката или нямаме коз
    if suit(win_card) == contract:
        return higher_than_winner(trumps) or list(hand)   # не сме длъжни да подцакваме
    return trumps


def find_declarations(hand):
    """Карета и поредици (терца/кварта/квинта) в ръка от 8 карти."""
    decls, used = [], set()
    for r, value in CARRE_VALUES.items():
        cards = [r + s for s in SUITS]
        if all(c in hand for c in cards):
            decls.append({"type": "carre", "name": "Каре", "rank": r, "value": value,
                          "cards": cards, "key": (0, 0)})
            used.update(cards)
    for s in SUITS:
        idx = sorted(RANKS.index(rank(c)) for c in hand if suit(c) == s and c not in used)
        run = []
        for i in idx + [None]:
            if run and i is not None and i == run[-1] + 1:
                run.append(i)
                continue
            if len(run) >= 3:
                length = min(len(run), 5)
                decls.append({"type": "seq", "name": SEQ_NAMES[length], "rank": RANKS[run[-1]],
                              "value": SEQ_VALUES[length],
                              "cards": [RANKS[j] + s for j in run],
                              "key": (SEQ_VALUES[length], run[-1])})
            run = [i] if i is not None else []
    return decls


def round_points(points, contract):
    q, r = divmod(points, 10)
    threshold = {"NT": 5, "AT": 4}.get(contract, 6)
    return q + (1 if r >= threshold else 0)


RED_SUITS = {"H", "D"}


def _alternating_suits(suits):
    """Подрежда наличните бои така, че черни и червени да се редуват, доколкото може."""
    base = ["S", "H", "C", "D"]

    def clashes(order):
        return sum((a in RED_SUITS) == (b in RED_SUITS) for a, b in zip(order, order[1:]))

    perms = itertools.permutations(sorted(suits, key=base.index))
    return min(perms, key=lambda p: (clashes(p), [base.index(s) for s in p]))


def sort_hand(hand, contract=None):
    order = {s: i for i, s in enumerate(_alternating_suits({suit(c) for c in hand}))}
    return sorted(hand, key=lambda c: (order[suit(c)],
                                       -card_order(c, contract) if contract else -PLAIN_ORDER.index(rank(c))))


class _SearchBudget(Exception):
    pass


class _ClaimSearch:
    """Пълно претърсване на остатъка от раздаването: играчът `claimer` избира картите си,
    а останалите трима (и партньорът!) играят каквото и да е позволено.
    wins() е True, ако отборът на claimer взима всички оставащи ръце."""

    def __init__(self, contract, claimer, budget):
        self.contract, self.claimer, self.budget = contract, claimer, budget
        self.memo, self.nodes = {}, 0

    def wins(self, hands, trick, leader):
        """hands: ръцете (кортежи); trick: изиграното във взятката; leader: кой я е започнал."""
        if len(trick) == 4:
            w, _ = trick_winner(list(trick), self.contract)
            if team(w) != team(self.claimer):
                return False
            return not hands[w] or self.wins(hands, (), w)
        key = (hands, trick, leader)
        if key in self.memo:
            return self.memo[key]
        self.nodes += 1
        if self.budget is not None and self.nodes > self.budget:
            raise _SearchBudget
        turn = (leader + len(trick)) % 4
        options = legal_cards(list(hands[turn]), list(trick), self.contract, turn)
        results = (self.wins(self._without(hands, turn, c), trick + ((turn, c),), leader) for c in options)
        res = any(results) if turn == self.claimer else all(results)
        self.memo[key] = res
        return res

    def winning_card(self, hands, trick, leader):
        options = legal_cards(list(hands[self.claimer]), list(trick), self.contract, self.claimer)
        for c in options:
            if self.wins(self._without(hands, self.claimer, c), trick + ((self.claimer, c),), leader):
                return c
        return options[0]

    @staticmethod
    def _without(hands, seat, card):
        return tuple(tuple(x for x in h if x != card) if i == seat else h for i, h in enumerate(hands))


class Game:
    """Цяла игра до 151 точки, състояща се от раздавания."""

    def __init__(self, rng=None):
        self.rng = rng or random.Random()
        self.scores = [0, 0]
        self.hanging = 0               # висящи точки, отиват при победителя на следващото раздаване
        self.dealer = self.rng.randrange(4)
        self.history = []              # резултати от раздаванията
        self.log = []
        self.winner = None
        self.start_hand()

    # ---------- раздаване и обявяване ----------
    def start_hand(self):
        self.phase = "bidding"
        self.deck = new_deck()
        self.rng.shuffle(self.deck)
        self.hands = [[] for _ in range(4)]
        self.contract = None           # "C".."AT"
        self.bidder = None
        self.multiplier = 1            # 1, 2 (контра), 4 (реконтра)
        self.bids = []                 # (seat, action)
        self.passes = 0
        self.trick, self.last_trick = [], None
        self.tricks_won = [0, 0]
        self.taken = [[], []]
        self.declarations = [[] for _ in range(4)]
        self.announced = [[] for _ in range(4)]   # обявени анонси (видими за всички)
        self.belots = []               # (seat, suit)
        self.played_first = [False] * 4
        self.hand_result = None
        self._claim_cache = {}
        self._deal_round([3, 2])
        self.turn = (self.dealer + 1) % 4
        self.add_log(f"Раздава {{p{self.dealer}}}.")

    def _deal_round(self, counts):
        for n in counts:
            for i in range(1, 5):
                seat = (self.dealer + i) % 4
                for _ in range(n):
                    self.hands[seat].append(self.deck.pop())

    def bid_options(self, seat):
        if self.phase != "bidding" or seat != self.turn:
            return []
        opts = ["pass"]
        start = CONTRACTS.index(self.contract) + 1 if self.contract else 0
        opts += CONTRACTS[start:]
        if self.contract and team(seat) != team(self.bidder) and self.multiplier == 1:
            opts.append("double")
        if self.contract and team(seat) == team(self.bidder) and self.multiplier == 2:
            opts.append("redouble")
        return opts

    def bid(self, seat, action):
        if action not in self.bid_options(seat):
            raise ValueError("Невалидна обява.")
        self.bids.append((seat, action))
        if action == "pass":
            self.passes += 1
            self.add_log(f"{{p{seat}}}: пас")
        elif action == "double":
            self.multiplier, self.passes = 2, 0
            self.add_log(f"{{p{seat}}}: контра!")
        elif action == "redouble":
            self.multiplier, self.passes = 4, 0
            self.add_log(f"{{p{seat}}}: реконтра!")
        else:
            self.contract, self.bidder, self.multiplier, self.passes = action, seat, 1, 0
            self.add_log(f"{{p{seat}}}: {CONTRACT_NAMES[action]}")

        if self.contract is None and self.passes == 4:
            self.add_log("Всички пасуваха – ново раздаване.")
            self.dealer = (self.dealer + 1) % 4
            self.start_hand()
            return
        if self.contract is not None and self.passes == 3:
            self._start_play()
            return
        self.turn = (seat + 1) % 4

    def _start_play(self):
        self._deal_round([3])
        self.phase = "playing"
        self.turn = (self.dealer + 1) % 4
        if self.contract != "NT":
            self.declarations = [find_declarations(h) for h in self.hands]
        extra = {2: " (контра)", 4: " (реконтра)"}.get(self.multiplier, "")
        self.add_log(f"Играе се {CONTRACT_NAMES[self.contract]}{extra}, обявено от {{p{self.bidder}}}.")

    # ---------- игра ----------
    def legal(self, seat):
        if self.phase != "playing" or seat != self.turn or len(self.trick) == 4:
            return []
        return legal_cards(self.hands[seat], self.trick, self.contract, seat)

    def play(self, seat, card):
        if card not in self.legal(seat):
            raise ValueError("Тази карта не може да се играе.")
        hand = self.hands[seat]
        # Белот: поп и дама от коз (при всичко коз – от изиграната боя)
        if rank(card) in ("K", "Q") and self.contract != "NT":
            other = ("Q" if rank(card) == "K" else "K") + suit(card)
            lead_ok = not self.trick or suit(self.trick[0][1]) == suit(card)
            trump_ok = self.contract == "AT" or suit(card) == self.contract
            if other in hand and trump_ok and lead_ok and (seat, suit(card)) not in self.belots:
                self.belots.append((seat, suit(card)))
                self.announced[seat].append("Белот")
                self.add_log(f"{{p{seat}}}: Белот!")
        if not self.played_first[seat]:
            self.played_first[seat] = True
            for d in self.declarations[seat]:
                label = f"{d['name']} ({d['value']})"
                self.announced[seat].append(label)
                self.add_log(f"{{p{seat}}} обявява {label}.")
        hand.remove(card)
        self.trick.append((seat, card))
        if len(self.trick) < 4:
            self.turn = (seat + 1) % 4

    def trick_complete(self):
        return self.phase == "playing" and len(self.trick) == 4

    def collect_trick(self):
        win_seat, _ = trick_winner(self.trick, self.contract)
        t = team(win_seat)
        self.tricks_won[t] += 1
        self.taken[t].extend(c for _, c in self.trick)
        self.last_trick = {"cards": self.trick, "winner": win_seat}
        self.trick = []
        self.turn = win_seat
        if not self.hands[win_seat]:
            self._score_hand(last_team=t)

    # ---------- сваляне на картите ----------
    def can_claim(self, seat):
        """Може ли играчът да свали картите: той е на ход, започва взятка, остават поне 2 ръце
        и отборът му гарантирано взима всички, каквото и да играят другите (вкл. партньорът)."""
        if (self.phase != "playing" or seat != self.turn or self.trick
                or len(self.hands[seat]) < 2):
            return False
        key = (seat, len(self.hands[seat]))
        if key not in self._claim_cache:
            try:
                self._claim_cache[key] = self._claim_search(seat).wins(self._claim_state(), (), seat)
            except _SearchBudget:
                self._claim_cache[key] = False     # твърде сложно за изчисляване – не предлагаме
        return self._claim_cache[key]

    def claim(self, seat):
        if not self.can_claim(seat):
            raise ValueError("Не е сигурно, че всички ръце са твои.")
        self.add_log(f"{{p{seat}}} свали картите – всички ръце са за отбора му.")
        search = self._claim_search(seat, budget=None)
        while self.phase == "playing":
            if self.trick_complete():
                self.collect_trick()
            elif self.turn == seat:
                leader = self.trick[0][0] if self.trick else seat
                self.play(seat, search.winning_card(self._claim_state(), tuple(self.trick), leader))
            else:
                self.play(self.turn, self.legal(self.turn)[0])

    def _claim_state(self):
        return tuple(tuple(sorted(h)) for h in self.hands)

    def _claim_search(self, seat, budget=40000):
        return _ClaimSearch(self.contract, seat, budget)

    # ---------- точкуване ----------
    def _score_hand(self, last_team):
        c = self.contract
        cards = [sum(card_points(x, c) for x in self.taken[t]) for t in (0, 1)]
        cards[last_team] += 10
        if c == "NT":
            cards = [x * 2 for x in cards]
        # Капото носи 90 (9 точки) и не се удвоява при без коз: 260 + 90 = 35
        capot = None
        for t in (0, 1):
            if self.tricks_won[t] == 8:
                cards[t] += 90
                capot = t

        decl = [0, 0]
        decl_text = [[], []]
        if c != "NT":
            # Поредиците се зачитат само за отбора с най-високата поредица
            best = [max([d["key"] for s in (t, t + 2) for d in self.declarations[s] if d["type"] == "seq"],
                        default=None) for t in (0, 1)]
            seq_team = None
            if best[0] and (not best[1] or best[0] > best[1]):
                seq_team = 0
            elif best[1] and (not best[0] or best[1] > best[0]):
                seq_team = 1
            for seat in range(4):
                for d in self.declarations[seat]:
                    if d["type"] == "carre" or team(seat) == seq_team:
                        decl[team(seat)] += d["value"]
                        decl_text[team(seat)].append(f"{d['name']} {d['value']}")
            for seat, _ in self.belots:
                decl[team(seat)] += 20
                decl_text[team(seat)].append("Белот 20")

        raw = [cards[t] + decl[t] for t in (0, 1)]
        bt, ot = team(self.bidder), 1 - team(self.bidder)
        game_pts = [round_points(raw[t], c) for t in (0, 1)]
        total_pts = game_pts[0] + game_pts[1]
        result = [0, 0]
        note = ""
        hang_now = 0
        if self.multiplier > 1:
            win = bt if raw[bt] > raw[ot] else ot
            result[win] = total_pts * self.multiplier
            note = ("Контра" if self.multiplier == 2 else "Реконтра") + \
                   (" – обявилите изкараха." if win == bt else " – обявилите са вътре!")
        elif raw[bt] > raw[ot]:
            result = game_pts[:]
            note = "Обявилите изкараха играта."
        elif raw[bt] < raw[ot]:
            result[ot] = total_pts
            note = "Обявилите са вътре!"
        else:
            result[ot] = game_pts[ot]
            hang_now = game_pts[bt]
            note = f"Равенство – {hang_now} точки остават висящи."

        hand_winner = 0 if result[0] > result[1] else 1
        if self.hanging and result[hand_winner] > 0:
            result[hand_winner] += self.hanging
            note += f" Висящите {self.hanging} точки отиват при победителите."
            self.hanging = 0
        self.hanging += hang_now

        for t in (0, 1):
            self.scores[t] += result[t]
        self.hand_result = {
            "contract": c, "bidder": self.bidder, "multiplier": self.multiplier,
            "cards": cards, "decl": decl, "decl_text": decl_text, "raw": raw,
            "points": result, "note": note, "capot": capot,
        }
        self.history.append({"contract": c, "bidder": self.bidder, "points": result})
        self.phase = "hand_over"
        self.add_log(f"Край на раздаването: {result[0]} : {result[1]}. {note}")

        if max(self.scores) >= WIN_SCORE and self.scores[0] != self.scores[1]:
            leader = 0 if self.scores[0] > self.scores[1] else 1
            msg = None
            if capot is not None:
                # При капо никога не се излиза
                msg = "При капо не се излиза – играе се още едно раздаване."
            elif self.multiplier > 1 and hand_winner != leader:
                # Контрата дава шанс на изоставащите да догонят: излиза се само ако
                # отборът, взел контрата, е и водещ. Иначе – още едно раздаване.
                kind = "контрата" if self.multiplier == 2 else "реконтрата"
                msg = (f"{kind.capitalize()} е взета, но взелите я още са назад "
                       f"– играе се още едно раздаване.")
            if msg:
                self.hand_result["note"] += " " + msg
                self.add_log(msg)
                return
            self.winner = leader
            self.phase = "game_over"
            self.add_log("Край на играта!")

    def next_hand(self):
        if self.phase != "hand_over":
            return
        self.dealer = (self.dealer + 1) % 4
        self.start_hand()

    def add_log(self, text):
        self.log.append(text)
        self.log = self.log[-60:]
