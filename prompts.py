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


INTERVIEW_QUESTIONS = [
    "Tell me about yourself.",
    "Why do you want this role?",
    "Tell me about a time you faced a challenge and how you handled it.",
    "What is your greatest strength, and how have you used it?",
    "Describe a time you worked on a team and there was a conflict.",
    "Where do you see yourself in five years?",
    "Tell me about a mistake you made and what you learned.",
    "Why should we hire you?",
]


def random_prompt() -> str:
    return random.choice(PROMPTS)


def interview_question_set(n: int = 4) -> list[str]:
    n = max(1, min(n, len(INTERVIEW_QUESTIONS)))
    return random.sample(INTERVIEW_QUESTIONS, n)
