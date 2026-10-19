"""Batch 7: Eldrazi que se barajan, hexproof de jugador, daño dividido, anthems
globales (Slivers, fichas, 'all creatures have haste') y estáticas varias."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import G, U, B, R, W  # noqa: E402
from cards import creature, land  # noqa: E402
from test_parser_corpus import build, new_game, run, put, give_lands  # noqa: E402


def test_eldrazi_shuffles_back_from_graveyard():
    g, me, ops = new_game()
    ul = build("Titan", "{10}", "Legendary Creature — Eldrazi",
               "When this creature is put into a graveyard from anywhere, shuffle it into its "
               "owner's library.", 10, 10)
    me.graveyard.append(ul)
    g.sba()
    assert ul not in me.graveyard and ul in me.library


def test_player_hexproof_blocks_targeting():
    g, me, ops = new_game()
    put(g, build("Sanctity", "{1}{W}{W}", "Enchantment", "You have hexproof."), ops[0])
    assert ops[0].has_hexproof()
    assert g.targetable_opponents(me) == []


def test_divided_damage_kills_and_goes_face():
    g, me, ops = new_game()
    a = put(g, creature("A", "1B", 1, 2), ops[0])
    sp = build("Boulderfall", "{6}{R}{R}", "Instant",
               "Boulderfall deals 5 damage divided as you choose among any number of targets.")
    assert "removal" in sp.tags
    life = ops[0].life
    sp.on_cast_resolve(g, me, [])
    assert a not in ops[0].battlefield and ops[0].life == life - 3


def test_global_anthems_and_haste():
    g, me, ops = new_game()
    put(g, build("Muscle Sliver", "{1}{G}", "Creature — Sliver", "All Sliver creatures get +1/+1.",
                 1, 1), me)
    theirs = put(g, build("Other Sliver", "{1}{R}", "Creature — Sliver", "", 1, 1), ops[0])
    assert theirs.power == 2
    put(g, build("Fervor", "{2}{R}", "Enchantment", "All creatures have haste."), me)
    bear = put(g, creature("Bear", "1G", 2, 2), ops[0])
    assert bear.has("haste")
    put(g, build("Anthem", "{1}{W}", "Enchantment", "Creature tokens get +1/+1."), me)
    import cards
    tok = cards.make_token(g, me, "Soldier", 1, 1)
    assert tok.power == 2


def test_life_double_enter_tapped_extra_draw():
    g, me, ops = new_game()
    put(g, build("Archive", "{4}", "Artifact",
                 "If you would gain life, you gain twice that much life instead."), me)
    life = me.life
    g.gain_life(me, 3)
    assert me.life == life + 6
    put(g, build("Blind Obedience", "{1}{W}", "Enchantment",
                 "Creatures your opponents control enter tapped."), me)
    foe = put(g, creature("Foe", "1B", 2, 2), ops[0])
    assert foe.tapped
    put(g, build("Kruphix", "{2}{U}{U}", "Enchantment",
                 "At the beginning of each player's draw step, that player draws an additional "
                 "card."), me)
    g.turn = 3
    h = len(ops[0].hand)
    g.begin_turn(ops[0])
    assert len(ops[0].hand) == h + 2


def test_first_strike_while_attacking_and_graveyard_cost():
    g, me, ops = new_game()
    k = put(g, build("Knight", "{1}{W}", "Creature — Human Knight",
                     "This creature has first strike as long as it's attacking.", 2, 2), me)
    assert not k.has("first_strike")
    k.attacking = ops[0]
    assert k.has("first_strike")
    rev = build("Reveler", "{6}{R}", "Sorcery", "This spell costs {1} less to cast for each instant "
                "and sorcery card in your graveyard.\nDraw two cards.")
    me.graveyard += [build("I1", "{R}", "Instant", "Draw a card."),
                     build("S1", "{R}", "Sorcery", "Draw a card.")]
    assert g.effective_cost(me, rev).cmc == 5
