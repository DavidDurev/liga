"""Прости ботове, които заместват липсващи играчи."""
from .engine import (CONTRACTS, SUITS, card_order, card_points, rank, suit, team,
                     trick_winner)


def _suit_strength(hand, s):
    cards = [c for c in hand if suit(c) == s]
    ranks = {rank(c) for c in cards}
    score = len(cards) + 3 * ("J" in ranks) + 2 * ("9" in ranks) + ("A" in ranks) + ("10" in ranks)
    score += sum(1 for c in hand if rank(c) == "A" and suit(c) != s)
    return score


def choose_bid(game, seat):
    opts = game.bid_options(seat)
    if game.bidder is not None and team(game.bidder) == team(seat):
        return "pass"                      # не надвикваме партньора
    hand = game.hands[seat]
    wanted = []
    for s in SUITS:
        if _suit_strength(hand, s) >= 7:
            wanted.append(s)
    aces = sum(1 for c in hand if rank(c) == "A")
    tens = sum(1 for c in hand if rank(c) == "10")
    if aces >= 3 or (aces == 2 and tens >= 2):
        wanted.append("NT")
    if sum(1 for c in hand if rank(c) in ("J", "9")) >= 4:
        wanted.append("AT")
    choices = [b for b in wanted if b in opts]
    if not choices:
        return "pass"
    if game.contract is None:
        # предпочитаме най-силната боя, а не най-високата обява
        return max(choices, key=lambda b: _suit_strength(hand, b) if b in SUITS else 9)
    return min(choices, key=CONTRACTS.index)


def choose_card(game, seat):
    legal = game.legal(seat)
    c = game.contract
    trick = game.trick
    if not trick:
        aces = [x for x in legal if rank(x) == "A" and not (c in SUITS and suit(x) == c)]
        if aces:
            return aces[0]
        if c in SUITS:
            top = [x for x in legal if suit(x) == c and rank(x) == "J"]
            if top:
                return top[0]
        return min(legal, key=lambda x: (card_points(x, c), card_order(x, c)))

    win_seat, _ = trick_winner(trick, c)
    winners = [x for x in legal if trick_winner(trick + [(seat, x)], c)[0] == seat]
    partner_wins = team(win_seat) == team(seat)
    last = len(trick) == 3
    if partner_wins and (last or len(trick) == 2):
        return max(legal, key=lambda x: (card_points(x, c), -card_order(x, c)))
    if winners and not partner_wins:
        if last:
            return min(winners, key=lambda x: (card_order(x, c), card_points(x, c)))
        return max(winners, key=lambda x: card_order(x, c))
    return min(legal, key=lambda x: (card_points(x, c), card_order(x, c)))
