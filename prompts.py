# prompts.py
import random

PROMPTS = [
    "Describe your ideal weekend.",
    "Explain a topic you know well to someone new to it.",
    "Tell me about a challenge you overcame recently.",
    "Pitch your favorite product or app in 30 seconds.",
    "Describe a place you would love to travel to and why.",
    "Talk about a book, film, or show that influenced you.",
    "Explain what you do for work as if to a 10-year-old.",
    "Argue for or against working from home.",
]


def random_prompt() -> str:
    return random.choice(PROMPTS)
