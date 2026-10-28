"""
backend/rag_pipeline/helper/response_variants.py

Single source of truth for every static, user-facing conversational line the
backend emits without calling an LLM: greetings, wellbeing replies, pleasantries,
farewells, bot identity, off-topic steering, clarifying prompts, and the lead-in
sentence shown above recommendation cards.

Rules for every line in this module:
- British English, Brand Kit 04 Plain voice, no em-dashes.
- No user names and no time-of-day wording (shared caches must never leak
  personalisation; personalisation stays client-side).
- Variants are picked at random per call so repeated turns do not feel canned.
"""

import random
from typing import Dict, Tuple

GREETING: Tuple[str, ...] = (
    "Hello, I am Kanseiku. What kind of mood or story are you in the mood for today?",
    "Hi there, Kanseiku here. Tell me a feeling, a genre, or a favourite title and I will find something to watch.",
    "Welcome in. I am Kanseiku, and I can help you find an anime that fits your mood. Where shall we start?",
    "Hello, and welcome. I am Kanseiku. Share a vibe or a title you loved and we will go from there.",
    "Hey, Kanseiku here. Looking for something cosy, thrilling, or somewhere in between?",
    "Good to see you. I am Kanseiku, your anime discovery guide. What would you like to feel while you watch?",
    "Hello. I am Kanseiku. Describe the kind of story you want and I will pick a few to try.",
)

WELLBEING: Tuple[str, ...] = (
    "Doing well, thank you. I am Kanseiku, and I would love to help you find an anime. What are you in the mood for?",
    "All good here, thanks for asking. Tell me a mood, a genre, or a title you enjoyed and I will find something.",
    "I am well, thank you. Kanseiku is ready whenever you want a recommendation. Any particular feeling in mind?",
    "Very well, thanks. Want me to find you something to watch? A mood or a favourite title is plenty to go on.",
    "Happy to be here. I am Kanseiku. What sort of story would you like to settle into?",
    "Doing nicely. If you tell me what you are in the mood for, I will line up a few anime to try.",
)

PLEASANTRY: Tuple[str, ...] = (
    "Happy to help. Share a mood, genre, or premise whenever you want more anime.",
    "Glad that helped. Tell me what you feel like watching next and I will look.",
    "Any time. If you would like another recommendation, just describe the mood.",
    "Lovely. Whenever you are ready, give me a vibe or a favourite title to start from.",
    "You are welcome. Ask for something new whenever you like, such as a genre, a feeling, or a story you liked.",
    "No problem at all. I am here when you want to find your next anime.",
    "Nice. Let me know if you would like more picks, or something quite different.",
)

FAREWELL: Tuple[str, ...] = (
    "Goodbye for now. Come back whenever you want your next anime.",
    "See you soon. Your next favourite is out there waiting.",
    "Take care. Kanseiku will be here when you want another recommendation.",
    "Bye for now. Enjoy whatever you watch next.",
    "Until next time. Enjoy one more episode for me.",
    "Farewell for now. Come back with a mood and I will find something good.",
)

BOT_IDENTITY: Tuple[str, ...] = (
    "I am Kanseiku, an anime discovery guide. I find series and films by mood, atmosphere, and theme. What are you in the mood for?",
    "Kanseiku here. I help you find anime that suit how you feel, from cosy slice of life to tense thrillers. What would you like to try?",
    "I am Kanseiku, a quiet place for anime recommendations. Describe a feeling or a favourite title and I will suggest where to go next.",
    "I am an anime recommendation guide called Kanseiku. Tell me the mood, and I will find a few titles that fit it.",
    "My name is Kanseiku. I match anime to your mood and taste, and I explain why each pick suits you. Where shall we begin?",
    "I am Kanseiku. I do one thing: help you find anime you will enjoy. Give me a mood, a genre, or a title to start from.",
    "Kanseiku is an anime discovery assistant. I look for stories by tone and theme rather than only by genre. What are you after?",
)

OFF_TOPIC: Tuple[str, ...] = (
    "That one is outside my area. I only help with anime, so tell me a mood or a genre and I will find something.",
    "I stick to anime recommendations, so I will have to pass on that. Want me to suggest something to watch instead?",
    "I am not the right guide for that, but I can find you an anime. What kind of story are you after?",
    "Anime is all I know well. Share a feeling or a favourite title and I will take it from there.",
    "I cannot help with that, but I would be glad to recommend an anime to watch. Any genre in mind?",
    "That is beyond what I can help with. If you would like an anime pick, describe the mood and I will search.",
    "I only cover anime, I am afraid. Tell me what you enjoy and I will suggest a few titles.",
)

CLARIFY: Tuple[str, ...] = (
    "Could you tell me a bit more? A mood, a genre, or a title you liked is plenty.",
    "I need a little more to go on. What kind of story are you in the mood for?",
    "Tell me a little more, such as a feeling or a favourite anime, and I will find something.",
    "That was a short one. Could you give me a mood, a genre, or a title to start from?",
    "Could you say a bit more about what you would like to watch? Even a few words about the mood will help.",
    "Say a little more and I will get looking. What are you hoping to feel while you watch?",
)

LEAD_IN: Tuple[str, ...] = (
    "Based on what you asked, here are {n} recommended anime.",
    "Here are {n} anime that fit what you described.",
    "I found {n} anime that suit that mood.",
    "From what you told me, these {n} anime should be worth a look.",
    "These {n} anime match what you asked for.",
    "Here are {n} anime picks for the mood you described.",
    "Taking your request into account, here are {n} anime to try.",
)

LEAD_IN_SINGLE: Tuple[str, ...] = (
    "Based on what you asked, here is 1 recommended anime.",
    "Here is 1 anime that fits what you described.",
    "I found 1 anime that suits that mood.",
)

_POOLS: Dict[str, Tuple[str, ...]] = {
    "greeting": GREETING,
    "wellbeing": WELLBEING,
    "pleasantry": PLEASANTRY,
    "farewell": FAREWELL,
    "bot_identity": BOT_IDENTITY,
    "off_topic": OFF_TOPIC,
    "clarify": CLARIFY,
}


def pick_response(pool_name: str) -> str:
    """Return a random static reply from the named pool.

    Single source of truth for non-LLM conversational copy. Raises KeyError for
    unknown pool names so typos fail loudly instead of returning empty text.
    """
    return random.choice(_POOLS[pool_name])


def pick_lead_in(count: int) -> str:
    """Return a random lead-in sentence for a recommendation turn.

    Returns an empty string when there are no recommendations, so callers can
    include the value unconditionally.
    """
    if count <= 0:
        return ""
    if count == 1:
        return random.choice(LEAD_IN_SINGLE)
    return random.choice(LEAD_IN).format(n=count)
